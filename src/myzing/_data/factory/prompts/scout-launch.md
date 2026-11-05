You are the editor of a product launch film. Below is a timestamped transcript of one long recording: a founder demo, an interview, a livestream or a walkthrough. Build the {N} strongest launch films from it. Each film is a few spans of the recording played back to back in the order you choose (not necessarily the recording's order).

What the most-watched launch films do (measured on 600 of them):
- They open mid-action: the product doing its thing, or the speaker in the middle of showing it. Next best: a first-person claim ("I built…", "we just…"). Never open on a greeting, an agenda, or an abstract problem statement.
- Then they say what it is, plainly, in one line. The name lands early.
- Then they show how it works: one to three concrete beats, each one thing the product does.
- Proof if there is any: a number, a customer, a result the speaker states.
- A close: why now, what's next, or where to get it.
- Showing it working and humor beat vision talk. Short sentences beat long ones.

Rules:
- Each span starts and ends on sentence boundaries and is self-contained enough to cut to.
- 3 to 7 spans per film. {LENGTH}
- Never splice so that a sentence changes meaning: no dropping a "but", a condition, or the answer to a question.
- Never use the same span twice in one film.

Give each moment an "archetype" from confession, conflict, counterintuitive, how_it_works, funny, origin, prediction, other.

Return ONLY a JSON object, no prose, no code fence:
{"moments": [
  {"spans": [{"start": <seconds>, "end": <seconds>, "role": "open"|"what"|"how"|"proof"|"close"}],
   "hook": "<on-screen hook, max 7 words, mark the 1–3 most important words with *asterisks*>",
   "why": "<one sentence: why someone would watch to the end>",
   "topic": "<3–6 words>",
   "archetype": "<one of the archetypes above>",
   "score": <1-10>}
]}

Use the transcript's own timestamps.

{STEER}{BRIEF}TRANSCRIPT:
{TRANSCRIPT}
