"""Seeded, offline starting points ported from MemeForge's eight formulas.

These are formula substitutions. The user's AI supplies editorial judgment.
Template grammar expands beyond MemeForge's two-field fallback where needed.
Topics are read as a thing ("release day", "deploying on a friday") or as a
situation ("when the build finally passes"); each shape gets formulas whose
grammar works for it, and a long topic is cut at a word, never mid-phrase
with an ellipsis.
"""

from __future__ import annotations

import hashlib
import re

from . import MemeError
from .score import idea_score
from .templates import get_template
from .validate import check_texts


TOPIC_LIMIT = 40  # the longest formula adds 30 characters: 40 + 30 = the 70 cap
# "when ..." prefixes always mean a situation; the subject after them is kept
# ("when you commit" stays "you commit").
WHEN = re.compile(r"^(?:me\s+when|that\s+feeling\s+when|the\s+moment\s+when|when)\s+", re.I)
POV = re.compile(r"^(?:pov\s*:?|the\s+moment)\s+", re.I)
TRYING = re.compile(r"^(?:trying\s+to|time\s+to|how\s+to|learning\s+to)\s+", re.I)
WH = {"how", "why", "what", "where", "who", "which", "whether"}
# Words that make a topic a situation (a clause), not a thing.
FINITE = {"is", "are", "was", "were", "am", "has", "have", "had", "does", "did", "won't", "can't",
          "doesn't", "don't", "isn't", "aren't", "didn't", "wasn't", "finally", "passes", "works",
          "breaks", "fails", "crashes", "goes", "gets", "compiles", "ships", "lands", "dies",
          "starts", "stops", "says", "asks", "tries", "wants", "needs", "thinks", "knows", "hits",
          "merges", "deploys", "loads", "runs", "returns", "happens", "comes", "leaves", "replies",
          "will", "would", "could", "should", "can", "never", "still"}
IRREGULAR_PAST = {"went", "broke", "came", "got", "took", "made", "said", "ran", "fell", "left", "forgot",
                  "lost", "sent", "wrote", "saw", "found", "built", "began", "drank", "ate", "froze",
                  "threw", "knew", "told", "thought", "brought", "bought", "caught", "taught", "felt",
                  "kept", "slept", "won", "shut", "quit", "hit", "spent", "stood", "understood"}
# Base verbs that finish a clause after "the/my/... <noun>" ("the tests pass").
BASE_VERBS = {"pass", "fail", "break", "work", "crash", "go", "get", "run", "compile", "load", "ship",
              "land", "die", "start", "stop", "merge", "deploy", "return", "happen", "come", "leave",
              "win", "lose", "time", "hang", "freeze"}
DETERMINERS = {"the", "my", "our", "your", "their", "his", "her", "its", "this", "these", "those", "all"}
PRONOUNS = {"i", "you", "we", "they", "he", "she", "it", "someone", "everyone", "nobody", "somebody",
            "everybody", "anyone"}
RELATIVE = {"that", "who", "which", "whose", "whom"}
# What can follow a verb (object or particle), as opposed to a noun in a compound.
OBJECT_STARTERS = {"the", "a", "an", "my", "our", "your", "their", "his", "her", "its", "this", "that",
                   "these", "those", "it", "them", "me", "us", "him", "everything", "something",
                   "nothing", "all", "some", "on", "in", "to", "up", "down", "out", "off", "with",
                   "for", "again", "at", "from", "into", "before", "after", "without", "every",
                   "each", "one", "two", "prod", "production", "main", "back", "over", "away"}
VERBS = {"fix", "ship", "deploy", "write", "debug", "merge", "review", "finish", "start", "make", "run",
         "test", "push", "update", "refactor", "rewrite", "migrate", "clean", "plan", "launch", "learn",
         "read", "try", "explain", "find", "delete", "install", "upgrade", "answer", "organize", "cancel",
         "book", "pay", "file", "move", "sort", "cook", "do", "get", "go", "touch", "train", "name",
         "commit", "submit", "format", "rebase", "be", "see", "close", "open", "rename", "revert",
         "ask", "call", "check", "join", "leave", "quit", "stop", "begin", "forget", "edit", "exit",
         "center", "use", "argue", "panic", "sync", "build", "release", "reply", "approve"}
# Verb + bare plural noun reads as a task only for these ("fix bugs", not "merge conflicts").
OBJECT_VERBS = {"fix", "ship", "write", "delete", "rename", "answer", "cook", "find", "read",
                "migrate", "refactor", "rewrite", "install", "upgrade", "approve"}
# Two-syllable verbs stressed on the last syllable double their consonant.
DOUBLES = {"commit", "submit", "admit", "permit", "omit", "emit", "transmit", "forget", "begin",
           "refer", "prefer", "occur", "incur", "recur", "deter", "control", "patrol", "compel",
           "expel", "propel", "rebel", "regret", "upset", "equip", "debug", "unplug", "format",
           "program", "kidnap", "acquit", "abet", "allot", "defer", "confer", "infer", "transfer",
           "quit", "rerun", "outrun", "overrun"}
GERUNDS = {"be": "being", "see": "seeing", "flee": "fleeing", "agree": "agreeing", "free": "freeing",
           "dye": "dyeing", "eye": "eyeing", "toe": "toeing", "hoe": "hoeing", "singe": "singeing"}
DANGLING_END = {"a", "an", "the", "of", "to", "for", "in", "on", "at", "and", "or", "with", "my", "your", "after"}
VOWELS = "aeiou"


def _syllables(word: str) -> int:
    groups, previous = 0, False
    for i, char in enumerate(word):
        vowel = char in VOWELS or (char == "y" and i > 0)
        groups += vowel and not previous
        previous = vowel
    if word.endswith("e") and groups > 1 and not word.endswith(("le", "ee")):
        groups -= 1  # silent final e
    return max(1, groups)


def _gerund(verb: str) -> str:
    """Spelling rules: be/see -> being/seeing, drop a silent final e, ie -> ying,
    -ic -> -icking, and double the consonant only after a stressed CVC
    ending (ship -> shipping, commit -> committing, visit -> visiting)."""
    verb = verb.casefold()
    if verb in GERUNDS:
        return GERUNDS[verb]
    if verb.endswith("ie"):
        return verb[:-2] + "ying"
    if verb.endswith(("ee", "ye", "oe")):
        return verb + "ing"
    if verb.endswith("e") and len(verb) > 2:
        return verb[:-1] + "ing"
    if verb.endswith("ic"):
        return verb + "king"
    plain = verb.replace("qu", "q")
    cvc = (len(plain) >= 3 and plain[-1] not in VOWELS + "wxy" and plain[-2] in VOWELS
           and plain[-3] not in VOWELS)
    if verb in DOUBLES or (cvc and _syllables(verb) == 1):
        return verb + verb[-1] + "ing"
    return verb + "ing"


def _bare(word: str) -> str:
    return word.casefold().strip(",.!?;:\"'")


def _clause_like(words: list[str]) -> bool:
    """A subject plus a finite verb before any relative clause."""
    bare = [_bare(w) for w in words]
    if not bare:
        return False
    if bare[0] in PRONOUNS:
        return True
    for i, word in enumerate(bare):
        if word in RELATIVE:
            return False  # "the meeting that ran long" is a thing
        after = bare[i + 1] if i + 1 < len(bare) else None
        if word in FINITE or word in IRREGULAR_PAST and i > 0:
            return True
        if i > 0 and len(word) > 4 and word.endswith("ed") and (after is None or after in OBJECT_STARTERS):
            return True  # "the deploy failed", "the intern pushed to main"
        if (i == 2 and bare[0] in DETERMINERS and word in BASE_VERBS
                and (after is None or after in OBJECT_STARTERS)):
            return True  # "the tests pass"
    return False


def _task(words: list[str]) -> bool:
    """A verb phrase: "fix the flaky test", "be on call", "fix bugs"."""
    first = _bare(words[0])
    if first not in VERBS or not words[0].isalpha():
        return False
    if len(words) == 1:
        return True
    second = _bare(words[1])
    return second in OBJECT_STARTERS or (
        first in OBJECT_VERBS and second.endswith("s") and not second.endswith("ss"))


BREAKS = {"and", "but", "while", "because", "so", "until", "after", "before", "then", "or",
          "which", "who", "when"}


def _clip(text: str, limit: int) -> str:
    """Shorten at a clause break ("the meeting runs long | and everyone..."),
    else at a word; never mid-word and never with an ellipsis."""
    if len(text) <= limit:
        return text
    words = text.split(" ")
    clause = None
    for i in range(1, len(words)):
        prefix = " ".join(words[:i]).rstrip(",;:")
        if len(prefix) > limit:
            break
        if len(prefix) >= 12 and (words[i].casefold() in BREAKS or words[i - 1].endswith((",", ";", ":"))):
            clause = prefix
    if clause:
        return clause
    words = text[:limit + 1].split(" ")[:-1] or [text[:limit]]
    while len(words) > 1 and words[-1].casefold() in DANGLING_END:
        words.pop()
    return " ".join(words)


def _topic(value: str) -> tuple[str, str]:
    """(shape, text). Shape is ``situation`` (a clause: "you commit", "the
    build finally passes"), ``wh`` (a wh-clause used as a noun: "how it
    works"), or ``thing`` (a noun phrase or a gerund: "release day",
    "fixing the flaky test")."""
    text = " ".join(value.split()).rstrip(".!?")
    shape = None
    match = WHEN.match(text)
    if match:
        text, shape = text[match.end():], "situation"
    else:
        match = POV.match(text)
        if match:
            text = text[match.end():]
    trying = TRYING.match(text)
    if trying:
        text = text[trying.end():]
    words = text.split()
    if not words:
        return "thing", ""
    if _bare(words[0]) in WH:
        shape = "wh"  # never "when how it works"
    elif trying or (shape is None and _task(words)):
        words[0] = _gerund(words[0])  # "fix a bug" -> "fixing a bug"
        text, shape = " ".join(words), "thing"
    elif shape is None:
        shape = "situation" if _clause_like(words) else "thing"
    return shape, _clip(text, TOPIC_LIMIT)


def _short(value: str, limit: int = TOPIC_LIMIT) -> str:
    return _clip(_topic(value)[1], limit)


def _template_texts(key: str, count: int, topic: str, index: int, pair: list[str]) -> list[str]:
    if key == "drake":
        options = [
            [f"a 47-slide plan for {topic}", "one meme"],
            [f"doing {topic}", "building a system first"],
            ["a sensible bedtime", f"{topic} at 2am"],
            ["reading the instructions", "trusting the vibes"],
            ["one quick fix", "a complete rewrite"],
            ["finishing the task", "renaming the project"],
            ["asking for help", "opening another tab"],
            ["the working version", "one tiny improvement"],
        ]
        return options[index]
    if key in ("db", "dg"):
        return [[topic, "me", "my actual priorities"], ["one more tab", "me", topic],
                ["a new system", "me", topic], [topic, "my brain", "sleep"],
                ["a side quest", "me", topic], [topic, "me at 2am", "tomorrow"],
                ["a rewrite", "me", topic], [topic, "the team", "the deadline"]][index]
    if key == "ds":
        return [["do the sensible thing", f"{topic} at 2am", "me"],
                [f"finish {topic}", "start over", "me"],
                ["ask for help", "open another tab", topic],
                ["ship it", "one more tweak", topic],
                ["read the docs", "guess again", topic],
                ["go to bed", "fix one thing", topic],
                ["use the old version", "rewrite everything", topic],
                ["do the work", "make a spreadsheet", topic]][index]
    if key == "gb":
        return [topic, ["planning", "researching", "scheduling", "optimizing"][index % 4],
                ["building a system", "making a dashboard"][index // 4], "calling the chaos iterative"]
    if key == "astronaut":
        # The upstream catalog has four regions; leave scene labels empty.
        return ["", "", f"wait, it's all {topic}?", "always has been"]
    if count == 1:
        return [pair[0]]
    if count == 2:
        return pair
    # Generic multi-panel progression: complete slots, never pretend a two-line
    # idea is a three-label or six-panel composition.
    middle = ["the plan", "the first attempt", "one small fix", "the rewrite"][:count - 2]
    return [topic, *middle, pair[1]]


def generate_ideas(topic: str, template: str = "", n: int = 6,
                   tone: str = "dry", audience: str = "", *, seed: str = "") -> list[dict]:
    if not isinstance(topic, str) or not topic.strip():
        raise MemeError("topic must be a non-empty string")
    if type(n) is not int or not 1 <= n <= 8:
        raise MemeError("n must be an integer from 1 to 8")
    if not isinstance(tone, str) or not isinstance(audience, str):
        raise MemeError("tone and audience must be strings")
    if not isinstance(seed, str):
        raise MemeError("seed must be a string")
    selected = get_template(template) if template else None
    shape, short = _topic(topic)
    # Multi-panel templates share the 110-character budget across up to six boxes.
    short = (_clip(short, 30) if selected else short) or "looking productive"
    crowd = _clip(" ".join(audience.split()), 18)
    asked = f"{crowd}: how's {short} going" if crowd else f"how's {short} going"
    if len(asked) > 70:
        asked = f"how's {short} going"
    if shape == "wh" and not selected:
        # A wh-clause works as a noun: "me explaining how it works".
        formulas = [
            ([f"me explaining {short}", "(i have no idea)"], "bluff", "Confidence without knowledge."),
            ([f"me pretending to know {short}"], "pretend", "One line; the photo sells the bluff."),
            ([f"nobody knows {short}", "and at this point i'm afraid to ask"], "afraid_to_ask",
             "A shared secret nobody admits."),
            ([f"pov: you finally understand {short}", "nobody move"], "understatement",
             "A frozen beat adds tension."),
            ([f"day 1 of figuring out {short}", "day 47"], "time_jump", "The number jump supplies the reversal."),
            ([f"the docs on {short}", "one sentence"], "docs", "The gap between need and help."),
            ([short, "great question. next slide."], "deflection", "A deflection carries the payoff."),
            ([f"the senior dev explaining {short}", "the junior dev nodding"], "nodding",
             "Two roles, one misunderstanding."),
        ]
    elif shape == "situation" and not selected:
        # The photo is the reaction; the situation is the setup.
        # Varied setups, so six concepts are not one setup with six payoffs.
        formulas = [
            ([f"when {short}"], "reaction", "One line; the photo is the reaction."),
            ([f"pov: {short}", "nobody move"], "understatement", "A frozen beat adds tension."),
            ([short, "and nobody knows why"], "mystery", "Shared confusion is the joke."),
            ([f"me explaining why {short}", "(i changed nothing)"], "confession",
             "The aside undercuts the explanation."),
            ([short, "me, acting like i planned this"], "self_own", "Taking credit for luck."),
            ([f"me acting surprised that {short}"], "deadpan", "One line of feigned surprise."),
            ([f"the whole team when {short}"], "group_reaction", "The photo stands in for everyone."),
            ([short, "we are so back"], "celebration", "An outsized reaction to a small win."),
        ]
    else:
        formulas = [
            ([f"day 1 of {short}", "day 47"], "time_jump", "The number jump supplies the reversal."),
            ([f"{short}: should take five minutes", "six hours later"], "underestimate",
             "A short time jump exposes the mistake."),
            (["the plan", short], "expectation", "The image supplies the gap between plan and reality."),
            ([f"pov: {short}, so far so good", "nobody move"], "understatement", "A cautious payoff adds tension."),
            ([f'"{short} can\'t hurt you"', f"{short}:"], "personification", "The image delivers the unfinished threat."),
            ([f'"how hard can {short} be"', "me, building a system first"], "self_own",
             "Overengineering gets in the way of doing it."),
            ([asked, '"define going"'], "evasion", "A tiny evasive answer carries the payoff."),
            ([f"{short} actually worked", "we are so back"], "celebration", "An unexpectedly easy win earns a reaction."),
        ]
    # A fixed hash avoids Python's per-process hash salt and RNG-version drift.
    seed_text = f"{topic.strip()}\0{tone}\0{audience}\0{selected['id'] if selected else ''}"
    if seed:
        seed_text += f"\0{seed}"
    seed = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    offset = int(seed[:8], 16) % len(formulas)
    ideas = []
    for index in range(n):
        pair, formula, why = formulas[(offset + index) % len(formulas)]
        texts = _template_texts(selected["id"], selected["box_count"], short, index, pair) if selected else pair
        validation = check_texts(texts, box_count=selected["box_count"] if selected else None)
        ideas.append({
            "id": f"offline-{seed[:12]}-{index}",
            "title": ["Best fit", "Sharper", "Self-own", "Understated", "Wildcard", "Minimal", "Variation", "Last try"][index],
            "texts": texts, "template": selected["id"] if selected else None,
            "formula": f"{selected['id']}:{formula}" if selected else formula,
            "why": why if not selected else f"Starting point for {selected['name']}; review the image and label order.",
            "score": idea_score(texts, tone), "score_kind": "compression_heuristic",
            "validation": validation, "provider": "offline_formulas",
        })
    return ideas
