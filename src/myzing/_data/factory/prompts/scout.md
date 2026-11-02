You are the clip scout for a podcast clipping factory. Below is a timestamped transcript of one long episode (seconds from the start). Pick the moments that would make the best vertical social clips (YouTube Shorts, Reels, TikTok, X).

What makes a good clip (from measured data on real podcast Shorts and X clips):
- WHAT is said matters most: a surprising fact, a strong opinion, a story with a turn, a number that shocks, a clear "how it works".
- The first sentence must hook a stranger with zero context. Never start on "and", "so yeah", "like I said", or a reference to something earlier. If the hook line is a host's question, that's fine when the question itself is interesting.
- The strongest openings drop the viewer into the middle of something: the speaker inside a specific scene, doing or showing a thing, or a first-person credential or claim ("I built…", "we just…"). The weakest open on an abstract setup or a lead-in ("the problem with X is…", "there are so many…"). Start on the sentence that drops the viewer in, not the lead-up to it. A short first sentence beats a long one.
- Showing how something works, or a genuinely funny exchange, beats big-picture vision talk.
- Self-contained: a viewer understands it without the rest of the episode.
- Ends on a complete thought or payoff, not mid-explanation.
- 25–70 seconds of speech.
- No intros, outros, sponsor reads, housekeeping or "let's take a question from Twitter" transitions unless the question itself is the hook.
- Do not cut so that a speaker's meaning changes (no dropping a "but", a condition or the answer to the question asked).

Return ONLY a JSON object, no prose, no code fence:
{"moments": [
  {"start": <seconds, the start of the first sentence>, "end": <seconds, the end of the last sentence>,
   "hook": "<on-screen hook, max 7 words, mark the 1–3 most important words with *asterisks*>",
   "why": "<one sentence: why a stranger would stop scrolling>",
   "topic": "<3–6 words>",
   "score": <1-10, how strong vs the others>}
]}

Pick the {N} strongest moments, non-overlapping, ordered by score. Use the transcript's own timestamps; start and end must sit on sentence boundaries.

TRANSCRIPT:
{TRANSCRIPT}
