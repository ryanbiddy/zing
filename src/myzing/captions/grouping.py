"""Width-constrained cue grouping and balanced line breaks.

AutoSubs' split_into_cue_groups, break_priority, choose_line_break and
schedule_min_duration (MIT, Tom Moroney) inform the boundary priorities,
balanced target/tolerance and non-overlapping duration extension here.
Zing adds a dynamic program, font advances and protected English pairs.
See docs/THIRD-PARTY-NOTICES.md for the upstream notice.
"""

import math
import re


STOPWORDS = frozenset("a an the this that these those my your his her its our their some any each every to of in on at by for from with into onto over under through between among about as and but or nor so yet if because although while than without within during until since before after above below across against near around behind beside beneath beyond despite except per via upon toward towards throughout alongside underneath whether unless when whenever wherever whereas".split())
BOUND = frozenset("i you he she it we they am is are was were be been being do does did have has had can could may might shall should will would must not".split())
ABBREVIATIONS = frozenset("mr mrs ms dr prof st vs etc".split())


def token(word):
    return word.text.strip().strip('.,;:!?"“”()').lower()


def terminal(word):
    return bool(re.search(r'[.!?。？！]["”\)]*$', word.text.strip())) and token(word) not in ABBREVIATIONS


def protected(left, right):
    return (token(left) in STOPWORDS | BOUND or bool(re.fullmatch(r"[\d,.]+", token(left)))
            or (left.text.istitle() and right.text.istitle()))


def priority(words, index, hard_gap):
    if index == len(words) or terminal(words[index-1]):
        return 3
    left, right = words[index-1:index+1]
    if left.text.rstrip().endswith((",", ";", ":", "—")) or right.start-left.end >= hard_gap/2:
        return 2
    return 1 if token(right) in STOPWORDS else 0


def choose_lines(words, measure, width, cap, max_lines, hard_gap=.5):
    texts = [w.text.strip() for w in words]
    whole = " ".join(texts)
    if len(whole) <= cap and measure(whole) <= width:
        return [whole]
    if max_lines == 1:
        return None
    candidates = []
    target = len(whole)/2
    for i in range(1, len(words)):
        if token(words[i-1]) in STOPWORDS:
            continue
        a, b = " ".join(texts[:i]), " ".join(texts[i:])
        if max(len(a), len(b)) > cap or max(measure(a), measure(b)) > width:
            continue
        # AutoSubs: natural breaks within cap/3 of the balanced target win.
        natural = priority(words, i, hard_gap) if abs(len(a)-target) <= cap/3 else 0
        cost = (100 if protected(words[i-1], words[i]) else 0) - 10*natural
        cost += abs(measure(a)-measure(b))/width + (2 if len(a) > len(b) else 0)
        cost += 30 if min(i, len(words)-i) == 1 else 0
        candidates.append((cost, i, [a, b]))
    return min(candidates)[2] if candidates else None


def group_words(words, measure, width, *, preset, portrait=True, end=None, fps=30):
    """Return (word groups, explicit lines, display ends, warnings).

    Hard width and word limits never silently shrink or wrap pop styles.
    Infeasible protected runs fail with a remedy; unavoidable single-word
    utterances and timing shortages are reported, not hidden by retiming ASR.
    """
    if not words:
        return [], [], [], []
    clean = preset == "clean"
    limit, cap = (24, 30 if portrait else 42) if clean else (3 if preset == "punch" else 4, 1000)
    gap, minimum, maximum = (.5, 5/6, 4.) if clean else (.35, .3, 2.)
    end = words[-1].end + .5 if end is None else end
    # Port AutoSubs' sentence/pause/speaker boundaries, without discarding words.
    hard = {i for i in range(1, len(words)) if terminal(words[i-1])
            or (words[i].start-words[i-1].end >= gap and token(words[i-1]) not in STOPWORDS)
            or getattr(words[i], "speaker", None) != getattr(words[i-1], "speaker", None)}
    best = [math.inf] * (len(words)+1)
    paths = [None] * (len(words)+1)
    best[0] = 0
    for j in range(1, len(words)+1):
        if j < len(words) and token(words[j-1]) in STOPWORDS:
            continue
        for i in range(max(0, j-limit), j):
            if not math.isfinite(best[i]) or any(i < k < j for k in hard):
                continue
            part = words[i:j]
            lines = choose_lines(part, measure, width, cap, 2 if clean else 1, gap)
            if lines is None or part[-1].end-part[0].start > maximum:
                continue
            available = (words[j].start - (2/fps if clean else 0) if j < len(words) else end) - part[0].start
            chars = sum(len(s) for s in lines)
            need = max(minimum, chars/20, len(part)*.3 if clean else 0)
            duration_cost = 10000 * max(0, minimum-available)**2 + 200 * max(0, need-available)**2
            orphan = 1000 if len(part) == 1 else 0
            boundary = 100 if j < len(words) and protected(words[j-1], words[j]) else 0
            target = 42 if clean else 12 if preset == "punch" else 18
            cost = best[i] + ((chars-target)/target)**2*8 + duration_cost + orphan + boundary
            cost += 6 - 2*priority(words, j, gap)
            if cost < best[j]:
                best[j], paths[j] = cost, (i, lines)
    if paths[-1] is None:
        raise ValueError(f"Caption {preset} cannot fit a protected phrase at this width; choose clean or correct the transcript boundaries.")
    groups, lines = [], []
    j = len(words)
    while j:
        i, visual = paths[j]
        groups.insert(0, words[i:j])
        lines.insert(0, visual)
        j = i
    ends, warnings = [], []
    for i, (part, visual) in enumerate(zip(groups, lines)):
        chars = sum(map(len, visual))
        need = max(minimum, chars/20, len(part)*.3 if clean else 0)
        next_start = groups[i+1][0].start if i+1 < len(groups) else end
        available = min(end, next_start - (2/fps if clean and i+1 < len(groups) else 0))
        desired = max(part[-1].end + .3, part[0].start + need)
        if i+1 < len(groups) and next_start-part[-1].end < .5:
            desired = available
        finish = max(part[-1].end, min(available, desired, part[0].start+maximum))
        ends.append(finish)
        if clean and i+1 < len(groups) and next_start-finish < 2/fps-1e-6:
            warnings.append("Clean caption gap is under two frames; preserving the final spoken word takes priority.")
        duration = finish-part[0].start
        if len(part) == 1:
            warnings.append(f"Single-word utterance or width constraint: {visual[0]!r}.")
        if duration + 1e-6 < minimum or chars/duration > 20 + 1e-6:
            warnings.append(f"Caption reading limit: {' '.join(visual)!r}, {duration:.2f}s, {chars/duration:.1f} cps; speech/cut limits the hold.")
    return groups, lines, ends, warnings
