"""Rank transcript windows with Jev (or the open Simple Jev demo) so the scout gets a shortlist of strong standalone moments."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from myzing import __version__

from .network import Network
from .tools import FactoryError

LOW, HIGH, STRIDE = 40.0, 90.0, 30.0
TYPESAFE = "https://api.typesafe.ai/v1/systemone"
FEATHERLESS = "https://api.featherless.ai/v1/classifier"
DEMO = "https://simple-jev-demo-api.featherless.ai/v1/classifier"
CLASSIFIER = "featherless-ai/gemma-4-26B-A4B-classifier"
LATEST = "jev-latest"
PURPOSE = "jev window scoring"
PACE = .55                                          # the free demo allows 2 requests a second
TRIES = 5
QUESTIONS = {
    "substance": {"type": "score", "instructions": "As a short social video clip, what is the strongest thing this excerpt contains?",
                  "criteria": ["Generic explanation, small talk or vision talk", "Somewhat interesting point",
                               "A surprising fact, strong opinion or concrete example",
                               "A story with a turn, real tension, a confession or a shocking number"]},
    "hook": {"type": "score", "instructions": "Read only the first sentence. Would a stranger scrolling short videos stop to hear the rest?",
             "criteria": ["No", "Maybe", "Probably", "Definitely"]},
    "payoff": {"type": "score", "instructions": "How does the excerpt end?",
               "criteria": ["Mid-thought or trailing off", "On an ordinary complete thought", "On a payoff, punchline or striking line"]},
}
WEIGHT = {"substance": .5, "hook": .3, "payoff": .2}
LEVELS = {k: len(v["criteria"]) - 1 for k, v in QUESTIONS.items()}
sleep, clock = time.sleep, time.monotonic           # tests swap these


def windows(segments: list[dict]) -> list[dict]:
    """40-90 s windows that end on a sentence end where one fits, starting about every 30 s."""
    out, after = [], float("-inf")
    for i, seg in enumerate(segments):
        a = seg["s"]
        if a < after:
            continue
        text, end = [], None
        for s in segments[i:]:
            if s["e"] - a > HIGH:
                break
            text.append(s["text"].strip())
            end = s["e"]
            if end - a >= LOW and text[-1][-1:] in ".?!":
                break
        if end is not None and end - a >= LOW:
            out.append({"start": a, "end": end, "text": " ".join(text)})
            after = a + STRIDE
    return out


def endpoint() -> tuple[str, str | None, str]:
    """The url, the key (None on the free demo) and the model."""
    model = os.environ.get("ZING_JEV_MODEL")
    key = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if key:
        return TYPESAFE, key, model or LATEST
    if os.environ.get("FEATHERLESS_API_KEY"):
        return FEATHERLESS, os.environ["FEATHERLESS_API_KEY"], model or CLASSIFIER
    return DEMO, None, model or CLASSIFIER


class _Pace:
    def __init__(self, gap: float):
        self.gap, self.last, self.lock = gap, float("-inf"), threading.Lock()

    def wait(self) -> None:
        with self.lock:
            wait = self.last + self.gap - clock()
            if wait > 0:
                sleep(wait)
            self.last = clock()


def _ask(net: Network, url: str, key: str | None, model: str, text: str, pace: _Pace | None) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": f"myzing/{__version__} (+https://myzing.app)"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({"model": model, "state": "Podcast transcript excerpt: " + text, "questions": QUESTIONS}).encode("utf-8")
    for attempt in range(TRIES):
        if pace:
            pace.wait()
        try:
            with net.open(url, PURPOSE, method="POST", data=body, headers=headers) as response:
                return json.loads(response.read())["answers"]
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403):
                raise FactoryError(f"Jev scoring was rejected ({code}). " + (
                    "The key looks wrong." if key else "The free demo refused the request; set JEV_API_KEY.")) from None
            if code != 429 and code < 500:
                raise FactoryError(f"Jev scoring failed with HTTP {code}") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        except (ValueError, KeyError, TypeError):
            raise FactoryError("Jev scoring returned an answer Zing could not read") from None
        sleep(1.5 * 2 ** attempt)                   # rate limited or a hiccup: back off
    raise FactoryError("Jev scoring kept failing after retries")


def _total(scores: dict) -> float:
    return round(sum(WEIGHT[k] * scores[k] / LEVELS[k] for k in WEIGHT), 3)


def score(project: Path, segments: list[dict], say=None) -> dict:
    """Score every window once; answers/jev.json keeps the result until 'redo jev'."""
    project = Path(project)
    wins = windows(segments)
    path = project / "answers" / "jev.json"
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if [(w["start"], w["end"]) for w in saved["windows"]] == [(w["start"], w["end"]) for w in wins]:
                return saved
        except (ValueError, KeyError, TypeError):
            pass
    if not wins:
        raise FactoryError("the transcript has no 40-90 second stretch to score")
    url, key, model = endpoint()
    net = Network(project)
    net.check(PURPOSE)
    pace, stop = None if key else _Pace(PACE), threading.Event()
    if say:
        say(f"Scoring {len(wins)} transcript windows with Jev ({urlsplit(url).hostname})")

    def one(w):
        if stop.is_set():
            return w
        try:
            answers = _ask(net, url, key, model, w["text"], pace)
            scores = {k: round(float(answers[k]["score"]), 3) for k in WEIGHT}   # expected rubric level, fractional
        except FactoryError:
            stop.set()
            raise
        except (KeyError, TypeError, ValueError):
            stop.set()
            raise FactoryError("Jev scoring returned an answer Zing could not read") from None
        return {**w, "scores": scores, "total": _total(scores)}

    with ThreadPoolExecutor(4 if key else 1) as pool:
        done = list(pool.map(one, wins))
    result = {"model": model, "host": urlsplit(url).hostname, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "windows": done}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def shortlist(result: dict, n: int = 15) -> list[dict]:
    """The best windows that do not overlap, best first."""
    chosen = []
    for w in sorted(result["windows"], key=lambda w: -w["total"]):
        if all(w["end"] <= c["start"] or w["start"] >= c["end"] for c in chosen):
            chosen.append(w)
        if len(chosen) == n:
            break
    return chosen


def block(ranked: list[dict]) -> str:
    lines = "\n".join(f"[{w['start']:g}-{w['end']:g}] {w['total']:.2f} - " + " ".join(w["text"].split()[:14]) + "..." for w in ranked)
    return ("A classifier ranked these spans as the strongest standalone moments (score 0-1). Prefer them unless a "
            "clearly stronger moment exists elsewhere:\n" + lines)
