# Raw-mode filler RECALL: what real speakers say that we miss

The precision work (RAW-FILLER-PRECISION) measured whether the fillers
we count are real. This is the other half: whether the fillers real
speakers use are counted at all. Both halves matter — a list can be
perfectly precise and still useless if it misses most of what people
actually say.

## Method

Frequency over the studied corpus (every stored breakdown with ≥100
transcribed words, 12+ real videos including a 62-minute interview),
then context sampling for each candidate. Corpus counts matter more
than raw frequency: a marker concentrated in ONE speaker is that
speaker's idiosyncrasy, not a general filler.

## The one addition: `basically`

| Word | Hits | Transcripts | Verdict |
|---|---|---|---|
| `literally` (already counted) | 8 | 4 | — |
| **`basically`** | **20** | **10** | **ADD** |

**CORRECTED 2026-07-20** (originally published as 14/7 and 22/12).
Writing `filler_corpus_audit.py` exposed the error: my ad-hoc scan
globbed every workspace without deduplicating by slug, so videos
studied into more than one scratch workspace were counted repeatedly.
The deduplicated figures are above. The conclusion does not just
survive — it strengthens: `basically` reaches 10 distinct speakers'
transcripts against `literally`'s 4, a wider margin than the inflated
numbers showed. Regeneration:
`python handoff/research/filler_corpus_audit.py <workspace-root>`.

`basically` is the same hedging class as `literally`, appears in MORE
speakers' transcripts, at comparable volume, and every sampled use is
a hedge: "tim basically told me this", "basically what we're doing
is", "basically enhance the future of". It has no common non-filler
sense, so unlike `like` and `kind of` it needs no guard.

Counting `literally` while ignoring `basically` was an inconsistency,
not a decision — the same shape as the uncapped-read finding.

## Deliberately NOT added, with reasons

| Word | Hits | Transcripts | Why not |
|---|---|---|---|
| `obviously` | 13 | **2** | 12 of 13 hits are ONE speaker — idiosyncrasy. And its uses assert something IS obvious ("he obviously was tipped off"): removing it changes meaning. |
| `actually` | 31 | 9 | Broad, but usually contrastive and meaning-bearing: "the newsletter is **actually** free", "hopefully they **actually** do something". |
| `just` | 126 | 21 | Dominant sense is the adverb ("I just arrived"). |
| `well` | 46 | 9 | Discourse-marker use is real ("well, I think…") but competes with adverb/noun senses. |
| `right` | 42 | 12 | Tag-question use is real ("right?") but competes with "the right way". |
| `yeah` | 41 | 7 | Often a genuine answer, not a tic. |

Each of these would import exactly the ambiguity that the `like` and
`kind of` guards had to undo — and every guard costs a false negative
somewhere. The conservative rule stands: a word enters the list only
when its filler sense dominates in measured speech.

These exclusions are PINNED by a test
(`test_ambiguous_markers_stay_out_of_the_filler_list`) so a future
"just add more fillers" change has to argue with this evidence rather
than silently widen the net.

## Honest limits

- The corpus is what Zing happened to study, not a designed sample:
  heavily English, mostly single-speaker, one long interview
  dominating the word count.
- Context sampling was 5–6 per candidate, enough to see a dominant
  sense, not enough for a precision figure.
- Recall against a LABELED filler set is still unmeasured. This note
  narrows the gap using available evidence; it does not close it.
- Non-English filler behaviour is entirely unexamined.
- **CLOSED 2026-07-20:** the corpus itself is not in the repo (scratch
  workspaces, third-party transcripts), which meant these figures were
  not independently checkable — Lane B reported exactly that in SG-1
  round 9, honestly declining to claim a verification they could not
  perform. Fixed by committing `filler-corpus-counts.json`: per
  transcript, the slug, source URL, word count and per-candidate
  counts — enough to re-derive every hits/spread figure here WITHOUT
  redistributing anyone's transcript. `filler_corpus_audit.py` with
  no argument now verifies against it; with a workspace argument it
  recomputes from source. Both agree (basically 20/10, literally
  8/4).
- The reproducible method: `filler_corpus_audit.py` recomputes hits AND spread over any
  workspace, and the source URLs are listed in the manifest below, so
  the finding can be re-derived on a fresh corpus even after link rot
  takes individual videos (SW-2 says it will).

## Evidence manifest — the corpus these figures came from

29 studied videos, 25,516 transcribed words. Largest contributors:

| Words | Source |
|---|---|
| 10,088 | https://x.com/ShawnRyanShow/status/1875286149788573873 |
| 3,110 | https://www.youtube.com/watch?v=22wlLy7hKP4 |
| 2,052 | https://www.youtube.com/watch?v=C25g53PC5QQ |
| 1,339 | https://www.youtube.com/watch?v=Xn-gtHDsaPY |
| 1,215 | https://www.youtube.com/watch?v=-UC6b5owmCA |
| 1,198 | https://www.youtube.com/watch?v=Rybj0X8eLH0 |
| 1,046 | https://www.youtube.com/watch?v=-01ZCTt-CJw |

The remaining 22 are short-form (43–360s) from the S5 sweep and the
preset-pack curation; every one is listed with its slug in
`S5-SWEEP-LANE-A.md` and `PRESET-PACK-REFERENCES.md`. Regenerate any
of them with `zing study <url> --workspace <ws>`.
