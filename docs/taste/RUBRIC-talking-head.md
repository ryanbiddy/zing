# Talking-Head Rubric (v1.0, 2026-07-18)

This rubric evaluates the "Creator Talking-Head" genre (e.g., educational, productivity, and talking-head explainer videos). Scoring is on a 1–5 scale per criterion, using a combination of quantitative telemetry and qualitative LLM judgment.

---

## Rubric Breakdown

### G-TH-1: Cold-Open Hook & Pacing (Weight: 20%)
* **Description:** A front-loaded verbal hook introducing a curiosity gap or problem statement within the first 6 seconds, avoiding intro graphics or branding.
* **Zing Measures:**
  * Number of cuts in the first 0–3s (target: high visual variance/re-framing).
  * Word count and time-to-proposition (target: first sentence verbal hook, under 3s).
* **AI Judges:**
  * Hook classification type (e.g., curiosity gap, story open, problem frame).
  * Hook efficacy: is the premise engaging and clear?
* **Confidence Tier:** T1 (Front-loading / YouTube Playbook / TikTok practices) | T3 (Practitioner teardowns).
* **Source Trace:**
  * Framework: H1, H2.
  * Teardown: Cleo Abram (Antarctica cold-open), Thomas Frank (Notion workflow BLUF), Ali Abdaal (reading 100 books problem/pain point frame).

### G-TH-2: Hook-Promise Congruence (Weight: 15%)
* **Description:** The alignment between the title/thumbnail promise and the video body. The video must immediately address and eventually resolve the hook's premise.
* **Zing Measures:**
  * Key terms in metadata (title) matching terms in the transcript within the first 10 seconds.
* **AI Judges:**
  * Semantic alignment: does the hook match the user's expectations set by the title?
  * Resolution check: does the video deliver a satisfying payoff to the initial hook?
* **Confidence Tier:** T1 (YouTube retention docs) | T3 (Practitioner-consensus).
* **Source Trace:**
  * Framework: H3, E4.
  * Teardown: Cleo Abram (setup/payoff resolution).

### G-TH-3: Cut Motivation and Rhythm (Weight: 15%)
* **Description:** Cuts must align with narrative changes, new arguments, or visual slides rather than occurring at mechanical time intervals. Alternates between high-energy visual explanations and steady talking-head shots.
* **Zing Measures:**
  * Cut frequency (average cut interval; target: 5–8s for standard talking head, 0.5–1.5s for graphical slides).
  * Coincidence of cuts with silence/pause boundaries.
* **AI Judges:**
  * Motivation: are cuts semantic (aligned with script shifts) or arbitrary (metronome cuts)?
* **Confidence Tier:** T3 (Walter Murch's Rule of Six / Practitioner-consensus).
* **Source Trace:**
  * Framework: E1.
  * Teardown: Cleo Abram (alternating pacing), Ali Abdaal (5–8s conversational shots), Thomas Frank (cut paced to zoom on code/UI).

### G-TH-4: Visual Organization & Cozy Aesthetic (Weight: 10%)
* **Description:** High-quality, balanced framing and lighting that projects credibility and authority. The workspace or studio setup must look intentional and clean.
* **Zing Measures:**
  * Aspect ratio (9:16 vertical target), resolution (>=720p).
  * Light brightness and contrast stability across frames.
* **AI Judges:**
  * Aesthetic framing: evaluates composition (cozy home office, bookshelf backdrop vs cluttered/distracting background).
* **Confidence Tier:** T3 (Practitioner-consensus).
* **Source Trace:**
  * Teardown: Ali Abdaal (warm studio lighting, bookshelves), Dave2D (minimalist pastel desk setup).

### G-TH-5: Caption Craft & Formatting (Weight: 15%)
* **Description:** Clear, legible, high-contrast subtitles. Typographic style must be clean and modern (sans-serif), avoiding excessive neon colors or constant screen flashing except for emphasis.
* **Zing Measures:**
  * Screen space occupied by subtitles (target: within bottom safe zones, minimal face blockage).
  * Word count per frame (target: low word density per card).
* **AI Judges:**
  * Readability and styling: does it match the minimalist aesthetic or distract from the speaker?
* **Confidence Tier:** T1 (Instagram downranking text-heavy content) | T3 (Practitioner-consensus).
* **Source Trace:**
  * Framework: P2.
  * Teardown: Ali Abdaal (minimal cursive/serif), Cleo Abram (center-aligned modern sans-serif).

### G-TH-6: Vocal Presence & Sound Design (Weight: 10%)
* **Description:** Clean, intelligible voiceovers paired with low-volume, relaxing background beats (e.g., lo-fi). Subtle sound effects (keyboard click, page turn) must highlight transitions without cluttering the vocal space.
* **Zing Measures:**
  * Speech-to-noise ratio and background track DB volume (target: music mixed low, -14 LUFS target).
  * Presence of background music ducking during active speech.
* **AI Judges:**
  * Soundtrack suitability: are background beats unobtrusive?
  * Foley integration: do transition sounds feel natural?
* **Confidence Tier:** T1 (TikTok sound/music requirements) | T3 (Practitioner-consensus).
* **Source Trace:**
  * Framework: P1.
  * Teardown: Ali Abdaal (relaxing lo-fi beats), Thomas Frank (UI ticks).

### G-TH-7: Human Vision & Anti-Slop (Weight: 15%)
* **Description:** The video must present an original, human perspective rather than a templated, automated AI script or generic stock slideshow.
* **Zing Measures:**
  * Synthetic voice detection score.
  * Image/clip repetition rate across the timeline.
* **AI Judges:**
  * Originality check: is there a personal stance, real-world case study, or unique storytelling angle that a basic template cannot replicate?
* **Confidence Tier:** T1 (YouTube monetization policies) | T3 (Practitioner-consensus).
* **Source Trace:**
  * Framework: A1, A2.
  * Teardown: Cleo Abram (wonder-proxy persona), Ali Abdaal (self-effacing friend authority).
