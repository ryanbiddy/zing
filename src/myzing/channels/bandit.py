"""Small, independent Normal posteriors for a channel's choices."""
from __future__ import annotations

import math
import random
from collections import Counter
from pathlib import Path

from myzing.factory.pipeline import _read
from myzing.playbook.common import number, parse_time

DIMENSIONS = ("archetype", "title_pattern", "length", "density", "pack", "hour")
FEATURES = {"name_claim": ("has_name", "past_tense"), "how_why": ("how_or_why",),
            "superlative": ("superlative",), "question": ("has_question",), "quote": ("has_quote",)}


def prior(channel: dict) -> dict:
    from . import registry
    if not channel.get("prior"):
        return {}
    path = Path(channel["prior"]).expanduser()
    if not path.is_absolute():
        path = registry.directory(channel["slug"]) / path
    data = _read(path)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("lifts"), list) or not isinstance(data.get("guidance"), list)
            or any(not isinstance(s, str) for s in data["guidance"])):
        raise registry.ChannelError("prior must point to a playbook PRIOR.json file")
    return data


def history(slug: str) -> list[dict]:
    from . import outcomes, queue
    rows = {r["id"]: r for r in outcomes.read(slug)}
    for row in queue.read(slug):
        arms = row.get("arms") or _read(Path(row["project"]) / row["clip"] / "arms.json", {"archetype": "other"})
        rows[row["id"]] = {**row, "arms": arms, **rows.get(row["id"], {}), "status": row["status"]}
    return list(rows.values())


def value(row: dict, dimension: str):
    return row.get("arms", {}).get(dimension, row.get(dimension))


def when(row: dict, field="queued_at") -> float:
    at = row.get(field) or row.get("posted_at") or row.get("slot")
    return parse_time(at).timestamp() if at else 0


def allowed(dimension: str, candidates, rows: list[dict]) -> list:
    candidates = list(dict.fromkeys(candidates))
    recent = sorted((r for r in rows if r.get("status", "posted") in ("queued", "kit", "posted")), key=when)[-10:]
    counts = Counter(value(r, dimension) for r in recent)
    return [v for v in candidates if len(candidates) == 1 or counts[v] < 5]


def usable(row: dict) -> bool:
    return not row.get("masked", False) and number(row.get("reward")) and row.get("status") != "skipped"


def posterior(dimension: str, candidates, rows: list[dict], prior: dict | None = None) -> dict:
    lifts = {r["feature"]: r for r in (prior or {}).get("lifts", []) if isinstance(r, dict) and "feature" in r}
    result = {}
    for candidate in dict.fromkeys(candidates):
        start = 0.0
        features = [lifts.get(f, {}) for f in FEATURES.get(candidate, ())] if dimension == "title_pattern" else []
        if features and all(r.get("weak") is False and number(r.get("lift")) and r["lift"] >= 0 for r in features):
            lift = min(r["lift"] for r in features)
            start = max(-1, min(1, .5 * math.log2(lift))) if lift else -1
        rewards = [r["reward"] for r in rows if usable(r) and value(r, dimension) == candidate]
        n = len(rewards)
        result[candidate] = {"n": n, "mean_reward": sum(rewards) / n if n else None,
                             "posterior_mean": (2 * start + sum(rewards)) / (2 + n),
                             "posterior_sd": math.sqrt(1 / (2 + n))}
    return result


def _sample(stats: dict, rng: random.Random):
    return max(stats, key=lambda v: rng.gauss(stats[v]["posterior_mean"], stats[v]["posterior_sd"]))


def best(stats: dict, draws=2000) -> dict:
    rng = random.Random(0)
    counts = Counter(_sample(stats, rng) for _ in range(draws)) if stats else {}
    return {v: counts.get(v, 0) / draws for v in stats}


def probabilities(stats: dict, baseline=None) -> dict:
    if not stats:
        return {}
    share = .1 if baseline is not None and baseline in stats else 0
    return {v: share * (v == baseline) + .15 / len(stats) + (1 - share - .15) * p
            for v, p in best(stats, 400).items()}


def choose(dimension, candidates, rows, rng, baseline=None, *, prior=None) -> tuple:
    candidates = allowed(dimension, candidates, rows)
    if not candidates:
        raise ValueError("No choices remain after the variety rule.")
    stats = posterior(dimension, candidates, rows, prior)
    share = .1 if baseline is not None and baseline in stats else 0
    draw = rng.random()
    if draw < share:
        chosen, policy = baseline, "baseline"
    elif draw < share + .15:
        chosen, policy = rng.choice(candidates), "explore"
    else:
        chosen, policy = _sample(stats, rng), "bandit"
    return chosen, probabilities(stats, baseline)[chosen], policy
