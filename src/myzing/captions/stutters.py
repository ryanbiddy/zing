"""Display-only immediate ASR repeats; raw studies and transcripts stay intact."""

from dataclasses import replace
import re

from myzing.timing import transform_word

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
GRAMMATICAL = {"that", "had"}


def collapse(words):
    """Merge case-insensitive adjacent words with a 0..350 ms end/start gap.

    Punctuation between tokens blocks merging (including standalone tokens).
    'that that' and 'had had' are always preserved. Keep the first start and
    spelling, the second end, and provenance on a copy of the displayed word.
    """
    result = []
    for word in words:
        text = word.text.strip()
        match = WORD.match(text)
        token = match.group() if match else ''
        suffix = text[len(token):]
        previous = result[-1] if result else None
        if (previous and token and not any(ch.isalnum() for ch in suffix) and WORD.fullmatch(previous.text.strip())
                and token.casefold() == previous.text.strip().casefold()
                and token.casefold() not in GRAMMATICAL
                and -1e-8 <= word.start - previous.end <= .35 + 1e-8):
            result[-1] = replace(transform_word(previous, previous.start, word.end,
                "caption_stutter_collapse", repeated=word.text), text=previous.text+suffix)
        else:
            result.append(word)
    return result
