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
| `literally` (already counted) | 14 | 7 | — |
| **`basically`** | **22** | **12** | **ADD** |

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
| `just` | 39 | many | Dominant sense is the adverb ("I just arrived"). |
| `well` | 28 | many | Discourse-marker use is real ("well, I think…") but competes with adverb/noun senses. |
| `right` | 19 | many | Tag-question use is real ("right?") but competes with "the right way". |
| `yeah` | 33 | many | Often a genuine answer, not a tic. |

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
