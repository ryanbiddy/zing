# When URL fetches fail (YouTube bot-gating and friends)

Zing fetches reference videos with yt-dlp. Platforms — YouTube
especially — now actively gate automated fetches, and the failures look
confusing ("Sign in to confirm you're not a bot", HTTP 403 on some
videos but not others, `LOGIN_REQUIRED`). This page is the fix order.
Work top to bottom; each step is cheaper and safer than the next.
`zing doctor` diagnoses steps 1–2 automatically.

## 1. Update yt-dlp (fixes the most, costs nothing)

```
python -m pip install -U yt-dlp
```

Platform extractors rot in weeks, not months. Doctor warns when your
version is >90 days old.

## 2. Install deno (YouTube now requires a JS runtime)

Since yt-dlp 2025.11.12, YouTube's signature challenges execute real
JavaScript — without a JS runtime, YouTube fetches fail. **Deno is the
only runtime yt-dlp enables by default:**

```
winget install DenoLand.Deno        # Windows
brew install deno                   # macOS
```

Have node but not deno? yt-dlp won't use it unless you opt in — add
`--js-runtimes node` to your yt-dlp config, or just install deno.
(Symptom of this exact state: SOME YouTube videos 403 while others
work, looking like an intermittent network problem.)

## 3. PO tokens via the bgutil provider plugin (flagged-IP relief)

If fetches still fail with "Sign in to confirm you're not a bot" or
`LOGIN_REQUIRED`, YouTube wants proof-of-origin (PO) tokens. The
community-standard fix is the bgutil provider plugin — it's what
yt-dlp's own wiki recommends first:

```
python -m pip install bgutil-ytdlp-pot-provider
```

plus its token server (Docker or Node ≥20/Deno ≥2 — see the project's
README: github.com/Brainicism/bgutil-ytdlp-pot-provider). yt-dlp picks
the plugin up automatically from its plugin system.

**Why Zing doesn't bundle this:** the plugin is GPL-3.0; Zing is MIT.
Installing it yourself into yt-dlp's plugin system keeps both licenses
happy — same posture TubeArchivist takes. Honest caveat from the
plugin's own docs: PO tokens improve legitimacy, they do not defeat
hard IP flags.

## 4. Cookies — the last resort, with a real warning

```
yt-dlp --cookies-from-browser firefox <url>    # or a cookies.txt
```

This ties fetches to your Google account. It works, but a flagged
fetch pattern can flag the *account*, and it carries more terms-of-
service exposure than anonymous fetching. Use it only when 1–3 fail,
and prefer a throwaway account.

## Still stuck?

Some IPs (VPNs, cloud ranges, shared CGNAT) are hard-flagged: every
client gets `LOGIN_REQUIRED` regardless of tokens. That's a network
problem, not a Zing problem — a different network is the fix. And for
already-studied references, Zing never re-fetches: cached media keeps
working offline.

*The usual disclaimer applies: fetch only content you have the right
to analyze, for personal use — same terms as using yt-dlp directly.*
