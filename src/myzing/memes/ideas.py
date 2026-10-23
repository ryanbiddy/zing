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


# Offline lines are built from the topic's own words (its head noun, clause
# subject or wh-clause) and from measured photo facts. No payoff line comes
# from a fixed list, so two topics never share a line. They remain templates:
# an agent or LLM with the meme-writer prompt writes better jokes.
PREPOSITIONS = {"from", "on", "in", "at", "with", "for", "about", "after", "before", "during",
                "to", "into", "without", "that", "who", "which", "while", "until", "off", "over",
                "under", "around", "through", "across", "near", "like", "than", "vs", "versus"}
POSSESSIVES = {"my", "our", "your", "their", "his", "her"}
GENERIC_HEADS = {"energy", "day", "days", "time", "week", "night", "mode", "season", "vibes", "life",
                 "stuff", "things", "situation", "moment", "era", "feeling", "plan", "thing"}
ARTICLES = DETERMINERS | {"a", "an"}
HONESTY = ("Template-based offline line: topic words and measured photo facts in fixed formulas. "
           "An agent or LLM given the meme-writer prompt writes better ones.")


def _proper(word: str) -> bool:
    return word[:1].isupper() or (word.isupper() and len(word) > 1)


def _noun_phrase(words: list[str]) -> str:
    """'the build', 'prod', 'Kevin': a determiner is kept only when typed."""
    return " ".join(words)


def _clip_words(text: str, limit: int) -> str:
    return _clip(text, limit) if len(text) > limit else text


def _thing_parts(words: list[str]) -> dict:
    """Head noun of a thing topic and how a line names it ("the standup",
    "my cat", "Kevin"). A preposition or participle ends the noun phrase."""
    phrase = words
    for index, word in enumerate(words[1:], 1):
        bare = _bare(word)
        if bare in PREPOSITIONS or (bare.endswith("ing") and len(bare) > 4
                                    and any(_bare(w) not in ARTICLES for w in words[:index])
                                    and not words[0].casefold().endswith("ing")):
            phrase = words[:index]
            break
    content = [w for w in phrase if _bare(w) not in ARTICLES]
    whole = None
    if len(content) == 1 and content[0].casefold().endswith("ing") and len(words) > len(phrase):
        # "being on call", "deploying on a friday": a short phrase names
        # itself; the prepositional object is its head word.
        whole = " ".join(words) if len(" ".join(words)) <= 24 else None
        content = [w for w in words[len(phrase):] if _bare(w) not in ARTICLES | PREPOSITIONS] or content
    if len(content) > 1 and content[0].casefold().endswith("ing"):
        content = content[1:]  # "fixing the flaky test" -> the test
    head = next((w for w in reversed(content) if _bare(w) not in GENERIC_HEADS),
                content[-1] if content else words[-1])
    head = head.strip(",.!?;:\"'")
    owner = _bare(phrase[0]) if phrase and _bare(phrase[0]) in POSSESSIVES and head in phrase else None
    the = whole or (head if _proper(head) else f"{phrase[0] if owner else 'the'} {head}")
    return {"head": _clip_words(head, 18), "the": _clip_words(the, 24)}


def _plural(phrase: str) -> bool:
    """'the tests' is plural; 'the build', 'prod', 'AWS', 'the bus' are not."""
    word = phrase.split()[-1] if phrase.split() else ""
    return (word.islower() and len(word) > 3 and word.endswith("s")
            and not word.endswith(("ss", "us", "is", "ics")))

def _verb_index(words: list[str]) -> int | None:
    """First verb of a clause. A word after an article is a noun ("the
    build"); bare task verbs count only after a subject ("you commit")."""
    for index, word in enumerate(words):
        bare = _bare(word)
        previous = _bare(words[index - 1]) if index else ""
        if index == 0 and bare in PRONOUNS:
            continue
        if index > 0 and previous in ARTICLES:
            continue
        if bare in FINITE or (index > 0 and (bare in IRREGULAR_PAST or (len(bare) > 4 and bare.endswith("ed")))):
            return index
        if index > 0 and (bare in BASE_VERBS or bare in VERBS):
            return index
    # Unknown verbs: a third-person -s word after a noun ("the printer jams").
    for index, word in enumerate(words[1:], 1):
        bare, previous = _bare(word), _bare(words[index - 1])
        if (previous not in ARTICLES | PRONOUNS and len(bare) > 2 and bare.endswith("s")
                and not bare.endswith(("ss", "us", "is"))):
            return index
    return None

def _situation_parts(words: list[str]) -> dict:
    """Subject noun phrase of a clause; a pronoun subject borrows the object
    ("you open the legacy code" -> "the legacy code") or the verb as a noun."""
    index = _verb_index(words)
    if index:
        subject = words[:index]
    else:
        subject = words[:2] if _bare(words[0]) in ARTICLES and len(words) > 1 else words[:1]
    rest = words[index + 1:] if index is not None else []
    if subject and _bare(subject[0]) not in PRONOUNS:
        np = _noun_phrase(subject)
    elif rest and _bare(rest[0]) in ARTICLES:
        np = _noun_phrase(rest[:4])
        for cut, word in enumerate(rest[1:4], 1):
            if _bare(word) in PREPOSITIONS:
                np = _noun_phrase(rest[:cut])
                break
    elif index is not None:
        verb = _bare(words[index])
        np = f"the {verb[:-1] if verb.endswith('s') and not verb.endswith('ss') else verb}"
    else:
        np = _noun_phrase(words[:3])
    return {"np": _clip_words(np, 22)}


def _wh_parts(words: list[str]) -> dict:
    """A determiner noun phrase inside the wh-clause ("why the build broke"
    -> "the build"); None when it has only pronouns ("how it works")."""
    for index, word in enumerate(words[1:-1], 1):
        if _bare(word) in ARTICLES:
            phrase = [word]
            for follower in words[index + 1:]:
                bare = _bare(follower)
                if bare in FINITE or bare in IRREGULAR_PAST or bare.endswith("ed") or bare in BASE_VERBS:
                    break
                phrase.append(follower)
            if len(phrase) > 1:
                return {"np": _clip_words(" ".join(phrase), 22)}
    return {"np": None}

COLOR_NAMES = ((15, "red"), (40, "orange"), (65, "yellow"), (170, "green"), (200, "teal"),
               (255, "blue"), (290, "purple"), (345, "pink"), (360, "red"))


def color_name(value: str) -> str | None:
    """Plain name for a saturated sampled color; None for grays, black, white."""
    import colorsys

    try:
        r, g, b = (int(value.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return None
    hue, light, saturation = colorsys.rgb_to_hls(r, g, b)
    if saturation < .25 or not .15 < light < .9:
        return None
    degrees = hue * 360
    name = next(label for limit, label in COLOR_NAMES if degrees < limit)
    return "brown" if name in ("orange", "red") and light < .35 else name


def photo_facts(photo) -> dict:
    """Measured facts a line may use, from a still Photo record (or dict).

    faces: prominent detected faces (None without the detector); text: OCR
    text read locally (None when OCR did not run); color: the dominant sampled
    color's plain name when saturated; light: dark/bright from mean luma;
    subject: position of a confident non-face subject estimate.
    """
    from .framing import prominent_faces
    from .subject import MIN_CONFIDENCE

    get = photo.get if isinstance(photo, dict) else lambda key, default=None: getattr(photo, key, default)
    faces = None
    if get("face_method") == "yunet":
        faces = len(prominent_faces([[f["x"], f["y"], f["width"], f["height"]] for f in get("faces") or []]))
    estimate = get("subject_estimate")
    brightness = (estimate or {}).get("evidence", {}).get("photo_brightness", get("brightness"))
    colors = get("colors") or []
    text = get("text")
    if text:
        text = _clip(" ".join(text.split()).strip(",.;:!?"), 24) or None
    return {"faces": faces, "text": text or None,
            "color": color_name(colors[0]) if colors else None,
            "light": None if brightness is None else "dark" if brightness < .3 else "bright" if brightness > .72 else None,
            "subject": (estimate["evidence"]["position"], estimate["box"])
            if estimate and estimate.get("confidence", 0) >= MIN_CONFIDENCE and not faces else None}


def _beside(box: list[float]) -> list[list[float]]:
    """Two label regions near, never on, a subject box (normalized)."""
    x, y, w, h = box
    width, height = .42, .13
    left = min(max(.03, x + w / 2 - width / 2), .97 - width)
    if y >= height + .05:
        first = [left, y - height - .03, width, height]
    elif y + h <= .97 - height - .03:
        first = [left, y + h + .03, width, height]
    else:
        side = .03 if x + w / 2 > .5 else .97 - width
        first = [side, .05, width, height]
    def clear(a, b):
        return (a[0] + a[2] <= b[0] or a[0] >= b[0] + b[2] or a[1] + a[3] <= b[1] or a[1] >= b[1] + b[3])

    corners = [[.03, .82, width, height], [.97 - width, .82, width, height], [.03, .05, width, height],
               [.97 - width, .05, width, height], [.03, .44, width, height], [.97 - width, .44, width, height]]
    # The second label goes to the free corner farthest from the subject.
    corners.sort(key=lambda c: -abs(c[0] + width / 2 - (x + w / 2)) - abs(c[1] + height / 2 - (y + h / 2)))
    other = next((c for c in corners if clear(c, box) and clear(c, first)), corners[0])
    return [[round(v, 4) for v in first], [round(v, 4) for v in other]]


def _evidence_formulas(shape: str, short: str, parts: dict, facts: dict) -> list[tuple]:
    """(texts, formula, why, evidence, regions) using measured photo facts."""
    the = parts.get("the") or parts.get("np") or short
    formulas = []
    faces = facts.get("faces")
    if faces and faces >= 2:
        line = {"situation": f"all {faces} of us when {short}", "wh": f"all {faces} of us pretending to know {short}"}
        formulas.append(([line.get(shape, f"all {faces} of us after {short}")], "face_count",
                         f"{faces} prominent faces detected locally; the photo is the group reaction.",
                         [f"faces={faces}"], None))
    elif faces == 1:
        line = {"situation": f"my face when {short}", "wh": f"my face when someone asks {short}"}
        formulas.append(([line.get(shape, f"me, five minutes into {short}")], "one_face",
                         "One prominent face detected locally; the photo is the reaction.", ["faces=1"], None))
    if facts.get("text"):
        quoted = facts["text"]
        formulas.append(([f'the sign said "{quoted}"', f"{short} anyway"], "photo_text",
                         f'Text read locally from the photo by OCR: "{quoted}".', [f"ocr_text={quoted!r}"], None))
    if facts.get("light") == "dark":
        texts = {"situation": [f"{short} at 2am"], "wh": [f"googling {short} at 2am"]}.get(
            shape, [f"{short} at 2am", f"{the} never sleeps"])
        formulas.append((texts, "dark_scene", "Measured scene brightness is dark, so the line is set at night.",
                         ["light=dark"], None))
    elif facts.get("light") == "bright":
        texts = {"situation": [f"{short} in broad daylight"], "wh": [f"explaining {short} in broad daylight"]}.get(
            shape, [f"{short} in broad daylight", f"no hiding from {the}"])
        formulas.append((texts, "bright_scene", "Measured scene brightness is bright, so the line is set in daylight.",
                         ["light=bright"], None))
    if facts.get("subject"):
        position, box = facts["subject"]
        label = {"situation": parts.get("np", short), "wh": short}.get(shape, short)
        other = {"situation": f"me when {short}", "wh": f"me explaining {short}"}.get(shape, f"me, avoiding {the}")
        formulas.append(([label, other], "subject_label",
                         f"Labels sit beside the estimated subject ({position}); the estimate marks a distinct "
                         "region, not what it is.", [f"subject={position}"], _beside(box)))
    if facts.get("color"):
        color = facts["color"]
        texts = {"situation": [f"{short} and everything turns {color}"], "wh": [f"{short}, explained in {color}"]}.get(
            shape, [f"{short}, but everything is {color}"])
        formulas.append((texts, "dominant_color", f"Dominant sampled color is {color}.", [f"color={color}"], None))
    return formulas


def _formulas(shape: str, short: str, parts: dict, asked: str) -> list[tuple]:
    """Eight or more topic-built formulas: (texts, formula, why)."""
    if shape == "wh":
        about = parts["np"] or short
        return [
            ([f"me explaining {short}", f"(i learned {short} an hour ago)"], "bluff", "Confidence without knowledge."),
            ([f"me pretending to know {short}"], "pretend", "One line; the photo sells the bluff."),
            ([f"nobody knows {short}", f"too late to ask about {about} now" if parts["np"] else
              f"too late to ask {short} now"], "afraid_to_ask", "A shared secret nobody admits."),
            ([f"pov: you finally understand {short}", f"nobody explain {short} again"], "understatement",
             "A frozen beat adds tension."),
            ([f"day 1 of figuring out {short}", f"day 47, still asking {short}"], "time_jump",
             "The number jump supplies the reversal."),
            ([f"the docs on {short}", f"one sentence about {about}"], "docs", "The gap between need and help."),
            ([f"someone asks {short}", f"me: {short}? great question"], "deflection",
             "A deflection carries the payoff."),
            ([f"the senior dev explaining {short}", f"the junior dev nodding about {about}"], "nodding",
             "Two roles, one misunderstanding."),
        ]
    if shape == "situation":
        np = parts["np"]
        return [
            ([f"when {short}"], "reaction", "One line; the photo is the reaction."),
            ([f"pov: {short}", f"don't touch {np}"], "understatement", "A frozen beat adds tension."),
            ([short, f"nobody knows why, not even {np}"], "mystery", "Shared confusion is the joke."),
            ([f"me explaining why {short}", f"(i never touched {np})"], "confession",
             "The aside undercuts the explanation."),
            ([short, f"me, taking credit for {np}"], "self_own", "Taking credit for luck."),
            ([f"me acting surprised that {short}"], "deadpan", "One line of feigned surprise."),
            ([f"the whole team when {short}"], "group_reaction", "The photo stands in for everyone."),
            ([short, f"{np} {'deserve' if _plural(np) else 'deserves'} a raise"], "celebration",
             "An outsized reaction to a small win."),
        ]
    the, head = parts["the"], parts["head"]
    return [
        ([f"day 1 of {short}", f"day 47 of {the}"], "time_jump", "The number jump supplies the reversal."),
        ([f"{short}: should take five minutes", f"{the}, three hours later"], "underestimate",
         "A short time jump exposes the mistake."),
        ([f"{short}: the plan", f"{the}: what actually happened"], "expectation",
         "Plan and reality, both named."),
        ([f"pov: {short}, so far so good", f"{the} can sense fear"], "understatement",
         "A cautious setup; the topic itself becomes the threat."),
        ([f'"{short} can\'t hurt you"', f"{short}:"], "personification", "The image delivers the unfinished threat."),
        ([f'"how hard can {short} be"', f"me, still on step one of {the}"], "self_own",
         "Overconfidence meets the first step."),
        ([asked, f'"define {head}"'], "evasion", "A tiny evasive answer carries the payoff."),
        ([f"{short} actually worked", f"saving proof of {the}"], "celebration",
         "An unexpectedly easy win earns a reaction."),
        ([f"nobody asked about {the}", f"me, explaining {short} anyway"], "nobody_asked",
         "The unprompted explainer (the \"nobody:\" setup without its banned filler)."),
        ([f'me hearing "{short}"'], "reaction", "One line; the photo is the reaction."),
    ]

def _fit(texts: list[str], parts: dict, short: str) -> list[str]:
    """Keep 70/110 budgets: a long topic in a later line becomes its short
    name; if that is not enough, the idea keeps its first line only."""
    def fits(lines):
        return all(len(t) <= 70 for t in lines) and sum(map(len, lines)) <= 110

    if fits(texts):
        return texts
    short_form = parts.get("the") or parts.get("np") or short
    fitted = [texts[0]] + [t.replace(short, short_form) for t in texts[1:]]
    return fitted if fits(fitted) else texts[:1]

def generate_ideas(topic: str, template: str = "", n: int = 6,
                   tone: str = "dry", audience: str = "", *, seed: str = "",
                   photo=None) -> list[dict]:
    """Seeded offline ideas. ``photo`` (a still Photo record or dict) adds
    formulas built from its measured facts; see :func:`photo_facts`."""
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
    words = short.split()
    parts = (_wh_parts(words) if shape == "wh" else _situation_parts(words) if shape == "situation"
             else _thing_parts(words))
    formulas = _formulas(shape, short, parts, asked)
    if selected and selected["box_count"] >= 2:
        # Multi-box templates need a setup and a payoff in every idea.
        formulas = [f for f in formulas if len(f[0]) >= 2]
    evidence = _evidence_formulas(shape, short, parts, photo_facts(photo)) if photo is not None and not selected else []
    # A fixed hash avoids Python's per-process hash salt and RNG-version drift.
    seed_text = f"{topic.strip()}\0{tone}\0{audience}\0{selected['id'] if selected else ''}"
    if seed:
        seed_text += f"\0{seed}"
    seed = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    offset = int(seed[:8], 16) % len(formulas)
    # Photo-evidence formulas lead; topic formulas follow from the seeded offset.
    ordered = [(texts, name, why, facts, regions) for texts, name, why, facts, regions in evidence]
    ordered += [(*formulas[(offset + i) % len(formulas)], [], None) for i in range(len(formulas))]
    ideas = []
    for index in range(n):
        pair, formula, why, facts, regions = ordered[index % len(ordered)]
        texts = (_template_texts(selected["id"], selected["box_count"], short, index, pair) if selected
                 else _fit(pair, parts, short))
        for brief in (parts.get("the") or parts.get("np"), parts.get("head")):
            if selected and brief and sum(map(len, texts)) > 110:
                # Multi-panel progressions: later boxes name the topic briefly.
                texts = texts[:1] + [t.replace(short, brief).replace(parts.get("the") or short, brief)
                                     for t in texts[1:]]
        validation = check_texts(texts, box_count=selected["box_count"] if selected else None)
        idea = {
            "id": f"offline-{seed[:12]}-{index}",
            "title": ["Best fit", "Sharper", "Self-own", "Understated", "Wildcard", "Minimal", "Variation", "Last try"][index],
            "texts": texts, "template": selected["id"] if selected else None,
            "formula": f"{selected['id']}:{formula}" if selected else formula,
            "why": why if not selected else f"Starting point for {selected['name']}; review the image and label order.",
            "score": idea_score(texts, tone), "score_kind": "compression_heuristic",
            "validation": validation, "provider": "offline_formulas",
        }
        if not selected:
            idea["evidence"] = ["topic words"] + facts
            idea["note"] = HONESTY
        if regions is not None:
            idea["regions"] = regions
        ideas.append(idea)
    return ideas
