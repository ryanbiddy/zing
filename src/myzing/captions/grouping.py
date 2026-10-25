"""Width-constrained cue grouping, balanced line breaks and cue scheduling.

AutoSubs' split_into_cue_groups, break_priority, choose_line_break and
schedule_min_duration (MIT, Tom Moroney) inform the boundary priorities,
balanced target/tolerance and non-overlapping duration extension here.
Zing adds a dynamic program, font advances, protected English pairs and a
scheduler that borrows lead-in silence before shortening any cue.
See docs/THIRD-PARTY-NOTICES.md for the upstream notice.
"""

import math
import re
import unicodedata


STOPWORDS = frozenset("a an the this that these those my your his her its our their some any each every to of in on at by for from with into onto over under through between among about as and but or nor so yet if because although while than without within during until since before after above below across against near around behind beside beneath beyond despite except per via upon toward towards throughout alongside underneath whether unless when whenever wherever whereas".split())
BOUND = frozenset("i you he she it we they am is are was were be been being do does did have has had can could may might shall should will would must not".split())
ABBREVIATIONS = frozenset("mr mrs ms dr prof st vs etc".split())
# A cue may appear up to LEAD before its first word, using silence or the
# previous cue's surplus hold. Neighbouring cues may give up at most SYNC of
# an edge word's display (three frames at 30 fps) so no cue flashes.
LEAD = .25
SYNC = .1
_NOSPACE = ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1780, 0x17FF), (0x2E80, 0x303F), (0x3040, 0x30FF),
            (0x3100, 0x31FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0xFE30, 0xFE4F),
            (0xFF00, 0xFF60), (0x20000, 0x3FFFF))


def _norm(text):
    return text.replace("’", "'").replace("‘", "'")


def token(word):
    return _norm(word.text.strip()).strip('.,;:!?"“”()¿¡،؟…').lower()


def terminal(word):
    return (bool(re.search(r'[.!?。？！؟۔…]["”’\'\)]*$', word.text.strip()))
            and token(word) not in ABBREVIATIONS
            and not re.fullmatch(r"(?:[A-Za-z]\.){2,}", word.text.strip()))


def nospace(ch):
    """Scripts written without spaces between words (CJK, kana, Thai, ...)."""
    code = ord(ch)
    return any(a <= code <= b for a, b in _NOSPACE)


_CURRENCY = "$£€¥₹"
_INTEGER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_NUMBER = rf"[{_CURRENCY}]?{_INTEGER}(?:\.\d+)?"
_GROUPED = rf"[{_CURRENCY}]?\d{{1,3}}(?:,\d{{3}})*"


def number_continuation(left, right, following=None):
    """Continue a pure numeric run, never punctuation attached to prose.

    Attached trailing punctuation (2026, or 3.) remains a sentence/list
    boundary. Only detached separators get lookahead.
    """
    if not left or not right:
        return False
    if len(left) == 1 and left in _CURRENCY and re.fullmatch(_NUMBER, right):
        return True
    if right in ("%", "‰"):
        return bool(re.fullmatch(_NUMBER, left))
    if re.fullmatch(_GROUPED, left):
        if re.fullmatch(r",\d{3}", right):
            return True
        if right == "," and following and re.fullmatch(r"\d{3}", following):
            return True
    if re.fullmatch(rf"[{_CURRENCY}]?{_INTEGER}", left):
        if re.fullmatch(r"\.\d+", right):
            return True
        if right == "." and following and re.fullmatch(r"\d+", following):
            return True
    return False


def separator(left, right):
    """Display boundary only: currency, grouped numbers, decimals, percent."""
    if not left or not right or (nospace(left[-1]) and nospace(right[0])) or number_continuation(left, right):
        return ""
    return " "


def display_boundaries(texts):
    """Spaces and protected numeric boundaries, in one linear token pass."""
    texts = [t.strip() for t in texts]
    spaces, numeric, run = [""], set(), texts[0] if texts else ""
    for i in range(1, len(texts)):
        right = texts[i]
        continued = number_continuation(run, right, texts[i+1] if i+1 < len(texts) else None)
        # A validated detached separator belongs to the following digits too.
        if texts[i-1] in (",", ".") and i-1 in numeric:
            continued = True
        if continued:
            numeric.add(i)
        spaces.append("" if continued or right in (",", ".", ";", ":", "!", "?")
                      or not run or not right or (nospace(run[-1]) and nospace(right[0])) else " ")
        run = run + right if continued else right
    return spaces[:len(texts)], numeric


def join(texts):
    """Join display words without changing timed tokens."""
    texts = [t.strip() for t in texts]
    spaces, _ = display_boundaries(texts)
    return "".join(space + text for space, text in zip(spaces, texts))


def glued(word):
    """Punctuation- or emoji-only tokens belong with the word before them."""
    return not any(c.isalnum() for c in word.text)


def protected(left, right):
    value = token(left)
    return (value in STOPWORDS | BOUND or "'" in value or bool(re.fullmatch(r"[\d,.]+", value))
            or (left.text.istitle() and right.text.istitle()))


def priority(words, index, hard_gap):
    if index == len(words) or terminal(words[index-1]):
        return 3
    left, right = words[index-1:index+1]
    if left.text.rstrip().endswith((",", ";", ":", "—", "،", "，", "、")) or right.start-left.end >= hard_gap/2:
        return 2
    return 1 if token(right) in STOPWORDS else 0


def choose_lines(words, measure, width, cap, max_lines, hard_gap=.5, split=None):
    """Lines for one cue; measure takes the list of display word texts.

    split forces the only line break (two sentences in one Clean cue).
    """
    texts = [w.text.strip() for w in words]
    whole = join(texts)
    _, numeric = display_boundaries(texts)
    if split is None and len(whole) <= cap and measure(texts) <= width:
        return [whole]
    if max_lines == 1:
        return None
    candidates = []
    target = len(whole)/2
    for i in range(1, len(words)):
        if split is not None and i != split:
            continue
        if token(words[i-1]) in STOPWORDS or glued(words[i]) or i in numeric:
            continue
        a, b = join(texts[:i]), join(texts[i:])
        if max(len(a), len(b)) > cap or max(measure(texts[:i]), measure(texts[i:])) > width:
            continue
        # AutoSubs: natural breaks within cap/3 of the balanced target win.
        natural = priority(words, i, hard_gap) if abs(len(a)-target) <= cap/3 else 0
        cost = (100 if protected(words[i-1], words[i]) else 0) - 10*natural
        cost += abs(measure(texts[:i])-measure(texts[i:]))/width + (2 if len(a) > len(b) else 0)
        cost += 30 if min(i, len(words)-i) == 1 else 0
        candidates.append((cost, i, [a, b]))
    return min(candidates)[2] if candidates else None


def schedule(groups, needs, *, minimum, maximum, chain, start, end, frame):
    """Display (start, end) per cue: never overlapping, never past a cut.

    Holds use following silence first (AutoSubs schedule_min_duration). A cue
    still under the minimum then starts up to LEAD early into silence or the
    previous cue's surplus, and finally borrows at most SYNC from the edge word
    of a neighbouring cue that keeps its own minimum. Shot/video ends are hard.
    """
    n = len(groups)
    s = [g[0].start for g in groups]
    e = [g[-1].end for g in groups]
    a, b = list(s), []
    for k in range(n):
        following = s[k+1] - chain if k+1 < n else end
        desired = max(e[k] + .3, s[k] + needs[k])
        if k+1 < n and s[k+1]-e[k] < .5:
            desired = following
        b.append(max(e[k], min(following, desired, s[k]+maximum)))

    def pull(k, want, depth):
        """Start cue k no later than want, moving earlier cues within limits."""
        if a[k] <= want + 1e-9:
            return
        if k == 0:
            floor = start
        else:
            last = groups[k-1][-1]
            hold = min(minimum, b[k-1]-a[k-1])  # The previous cue keeps its hold.
            if depth and a[k-1] + hold + chain > want + 1e-9:
                pull(k-1, want - chain - hold, depth-1)
            floor = max(last.end - SYNC, last.start + frame, a[k-1] + min(minimum, b[k-1]-a[k-1])) + chain
        earlier = min(a[k], max(want, s[k] - LEAD, floor))
        if earlier < a[k] - 1e-9:
            a[k] = earlier
            if k:
                b[k-1] = min(b[k-1], a[k] - chain)

    for k in range(n):
        if b[k]-a[k] >= needs[k] - 1e-9:
            continue
        pull(k, b[k] - needs[k], n)
        if b[k]-a[k] < minimum - 1e-9 and k+1 < n and b[k] >= a[k+1] - chain - 1e-9:
            later = min(s[k+1] + SYNC, groups[k+1][0].end - frame, a[k] + minimum + chain,
                        b[k+1] - minimum if b[k+1]-a[k+1] >= minimum else a[k+1])
            if later > a[k+1] + 1e-9:
                a[k+1] = later
                b[k] = later - chain
    return a, b


def edge_bound(starts, ends, k, end, chain=0.):
    """True when cue k and every later cue run back to back into the cut/end."""
    for j in range(k, len(ends)):
        following = starts[j+1] - chain if j+1 < len(ends) else end
        if ends[j] < following - 1e-6:
            return False
    return True


def group_words(words, measure, width, *, preset, portrait=True, start=None, end=None, fps=30, solo=()):
    """Return (word groups, explicit lines, display starts, display ends, warnings).

    measure takes a list of display word texts. Hard width and word limits
    never wrap pop styles; solo indices are words that must stand alone (a long
    word shrunk to fit). Sub-minimum cues are a last resort, reported with
    their cause: a shot or video end, or speech too dense to borrow from.
    """
    if not words:
        return [], [], [], [], []
    n = len(words)
    texts = [w.text.strip() for w in words]
    _, numeric = display_boundaries(texts)
    units = [0]
    for i in range(n):
        units.append(units[-1] + (i not in numeric))
    clean = preset == "clean"
    limit, cap = (24, 30 if portrait else 42) if clean else (3 if preset == "punch" else 4, 1000)
    if all(all(nospace(c) or not c.isalnum() for c in w.text) for w in words):
        limit = 24  # Character-token scripts break by measured width, not English word count.
    gap, minimum, maximum = (.5, 5/6, 4.) if clean else (.35, .3, 2.)
    orphan = 5000
    target = 42 if clean else 12 if preset == "punch" else 18
    frame = 1/fps
    chain = 2*frame if clean else 0
    end = words[-1].end + .5 if end is None else end
    start = max(0., words[0].start - LEAD) if start is None else start
    solo = set(solo)
    sentence = {i for i in range(1, n) if terminal(words[i-1]) and i not in numeric}
    # Port AutoSubs' sentence/pause/speaker boundaries, without discarding words.
    hard = {i for i in range(1, n)
            if (words[i].start-words[i-1].end >= gap and token(words[i-1]) not in STOPWORDS)
            or getattr(words[i], "speaker", None) != getattr(words[i-1], "speaker", None)
            or i in solo or i-1 in solo}
    if not clean:
        edges = sorted({0, *sentence, n})
        for a, k, b in zip(edges, edges[1:], edges[2:]):
            if words[k-1].end-words[a].start >= minimum and words[b-1].end-words[k].start >= minimum:
                hard.add(k)
    # Sentence breaks are preferred. Short fragments may join a neighbour;
    # a pause or speaker change remains a hard boundary.
    best = [math.inf] * (n+1)
    paths = [None] * (n+1)
    best[0] = 0
    from bisect import bisect_left
    for j in range(1, n+1):
        if j in numeric:
            continue  # Do not put half a currency/decimal value in another cue.
        for i in range(bisect_left(units, units[j]-limit), j):
            if not math.isfinite(best[i]) or any(i < k < j for k in hard):
                continue
            part = words[i:j]
            if j < n and token(words[j-1]) in STOPWORDS and j not in hard:
                continue
            if j < n and glued(words[j]):
                continue
            # Clean may hold two short sentences, one per line (Netflix style).
            split = [k-i for k in sentence if i < k < j] if clean else []
            if len(split) > 1:
                continue
            lines = choose_lines(part, measure, width, cap, 2 if clean else 1, gap, split[0] if split else None)
            if lines is None or (units[j]-units[i] > 1 and part[-1].end-part[0].start > maximum):
                continue
            chars = sum(len(s) for s in lines)
            need = max(minimum, chars/20, len(part)*.3 if clean else 0)
            floor = start if i == 0 else words[i-1].end - SYNC + chain
            shown = min(part[0].start, max(part[0].start - LEAD, floor))
            available = (words[j].start + SYNC - chain if j < n else end) - shown
            deficit = max(0, minimum-available)
            cost = best[i] + ((chars-target)/target)**2*8 + 200 * max(0, need-available)**2
            cost += 100000000*deficit**2 + 100000000*deficit
            cost += orphan if len(part) == 1 and not glued(part[0]) else 0
            if j < n and j not in hard:
                cost += 2000 if token(words[j-1]) in STOPWORDS else 0
                cost += 100 if protected(words[j-1], words[j]) else 0
                cost += 500 if glued(words[j]) else 0
            cost += 30 if split else 0
            if not clean and any(i < k < j for k in sentence):
                cost += 500  # Prefer separate sentences unless they flash/orphan.
            cost += 6 - 2*priority(words, j, gap)
            if cost < best[j]:
                best[j], paths[j] = cost, (i, lines)
    if paths[-1] is None:
        raise ValueError(f"Caption {preset} cannot fit a word at this width even alone; choose a larger output.")
    groups, lines = [], []
    j = n
    while j:
        i, visual = paths[j]
        groups.insert(0, words[i:j])
        lines.insert(0, visual)
        j = i
    needs = [max(minimum, sum(map(len, visual))/20, len(part)*.3 if clean else 0) for part, visual in zip(groups, lines)]
    starts, ends = schedule(groups, needs, minimum=minimum, maximum=maximum, chain=chain,
                            start=start, end=end, frame=frame)
    warnings = []
    for i, (part, visual) in enumerate(zip(groups, lines)):
        chars = sum(map(len, visual))
        if clean and i+1 < len(groups) and starts[i+1]-ends[i] < chain-1e-6:
            warnings.append("Clean caption gap is under two frames; preserving the final spoken word takes priority.")
        duration = ends[i]-starts[i]
        if len(part) == 1 and i not in solo:
            warnings.append(f"Single-word utterance or width constraint: {visual[0]!r}.")
        if duration + 1e-6 < minimum:
            edge = "the shot or video ends" if i+1 == len(groups) and ends[i] >= end-1e-6 else "speech is too dense to borrow time"
            warnings.append(f"Caption under minimum hold: {' '.join(visual)!r}, {duration:.2f}s; {edge}.")
        if chars/max(duration, 1e-6) > 20 + 1e-6:
            warnings.append(f"Caption reading limit: {' '.join(visual)!r}, {duration:.2f}s, {chars/duration:.1f} cps; speech/cut limits the hold.")
    return groups, lines, starts, ends, warnings
