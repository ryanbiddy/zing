# R1-C — Render and evaluation engineering

This round turns the Sprint 1 render and evaluation requirements into choices that can be implemented and tested on Linux and Windows.

## Confidence labels

- **verified-data** — directly documented by a primary source or observable in a deterministic probe.
- **practitioner-consensus** — a broadly used engineering practice supported by primary product documentation, but still sensitive to content and environment.
- **single-opinion** — a proposed project choice or inference that needs validation in Zing.

## Decisions that should shape C-1 and C-2

1. **[verified-data] Use ASS rendered by libass for karaoke captions, not one `drawtext` filter per word.** FFmpeg’s `subtitles` and `ass` filters render through libass; `drawtext` has separate font, shaping, and escaping concerns, including three layers of escaping when text is embedded in a filtergraph. ([FFmpeg subtitles/ass filters](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [FFmpeg drawtext filter](https://ffmpeg.org/ffmpeg-filters.html#drawtext), [FFmpeg escaping rules](https://ffmpeg.org/ffmpeg-utils.html#Quoting-and-escaping))
2. **[single-opinion] Mix and duck first, then apply two-pass `loudnorm` to the complete programme.** This ordering lets the final loudness pass measure the signal listeners will receive; FFmpeg documents the measured values required for a linear second pass and warns that it can fall back to dynamic mode when the target conditions are not met. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress))
3. **[single-opinion] Make aspect-preserving fit-and-pad the Sprint 1 default.** FFmpeg provides an explicit decrease-to-fit mode and centered padding; increase-and-crop is valid but discards source edges and should wait for an explicit composition policy. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg pad](https://ffmpeg.org/ffmpeg-filters.html#pad), [FFmpeg crop](https://ffmpeg.org/ffmpeg-filters.html#crop))
4. **[practitioner-consensus] Judge decoded semantics rather than encoded-file hashes.** FFmpeg’s FATE guidance favors small regression samples, while its hash muxers operate on decoded packets or frames; an encoded MP4 hash therefore answers a different and more fragile question than whether cuts, captions, streams, pixels, and audio are correct. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html), [FFmpeg hash and framehash muxers](https://ffmpeg.org/ffmpeg-formats.html#hash-1))
5. **[single-opinion] Do not add a mutation-testing package in Sprint 1.** Mutmut currently requires `fork` and directs Windows users to WSL, while the Sprint 1 scorer needs deliberate domain corruptions such as shifted cuts, missing captions, and wrong aspect ratios. A small pytest fault matrix is cheaper and more portable. ([mutmut README](https://github.com/boxed/mutmut), [mutmut package metadata](https://github.com/boxed/mutmut/blob/main/pyproject.toml))

## 1. Karaoke captions: ASS/libass versus drawtext

### Recommended representation

**[verified-data] ASS has native karaoke timing.** `\k` durations are centiseconds; `\k` changes the syllable fill at its start, while `\K`/`\kf` sweep the secondary color to the primary color from left to right and `\ko` changes outline behavior. `\kt` is not supported by all renderers, so it is a poor portability choice. ([Aegisub karaoke tags](https://aegisub.org/docs/latest/ass_tags/#karaoke-effect))

**[verified-data] Pop or bounce is separate from karaoke fill.** ASS `\t` can animate scale (`\fscx`, `\fscy`), color, alpha, outline, and other override tags over millisecond ranges relative to an event; `\move` is constant-speed and limited to one movement instruction per line. ([Aegisub animated transforms](https://aegisub.org/docs/latest/ass_tags/#animated-transform), [Aegisub movement](https://aegisub.org/docs/latest/ass_tags/#movement))

**[single-opinion] Encode one ASS event per active word, retaining the whole caption line as context, when a word needs a discrete pop.** Give that event a short scale envelope such as 100% → 118% → 100% with `\t`, and use `\kf` only when a left-to-right fill is wanted. Event-per-word costs more events but avoids relying on multiple mutually exclusive tags whose behavior may vary by renderer. ([Aegisub animated transforms](https://aegisub.org/docs/latest/ass_tags/#animated-transform), [Aegisub override-tag caveat](https://aegisub.org/docs/latest/ass_tags/#override-tags))

**[single-opinion] Keep the first implementation conservative: instant active-word color plus a small scale pop, no moving baseline.** This uses transform properties explicitly documented by ASS and avoids `\move` limitations and line-to-line geometry surprises. ([Aegisub animated transforms](https://aegisub.org/docs/latest/ass_tags/#animated-transform), [Aegisub movement](https://aegisub.org/docs/latest/ass_tags/#movement))

### Authoring boundary

**[verified-data] `pysubs2` is MIT-licensed, dependency-free, and can serialize ASS events containing raw override tags.** Its documented example places an override tag directly in `SSAEvent.text`, and ASS is listed as supporting rich formatting and animation. ([pysubs2 README](https://pysubs2.readthedocs.io/en/latest/), [pysubs2 supported formats](https://pysubs2.readthedocs.io/en/latest/supported-formats.html))

**[verified-data] The high-level `pysubs2` tag parser does not document karaoke or transform tags.** Its `parse_tags` API lists basic style tags such as bold, italic, font name, and reset. ([pysubs2 API reference](https://pysubs2.readthedocs.io/en/latest/api-reference.html#pysubs2.formats.substation.parse_tags))

**[single-opinion] Use `pysubs2` only for ASS file, style, and event serialization; generate and validate raw `\k`/`\kf` and `\t` tokens in Zing code.** That keeps the library boundary aligned with its documented behavior rather than assuming an undocumented karaoke builder. ([pysubs2 API reference](https://pysubs2.readthedocs.io/en/latest/api-reference.html#pysubs2.formats.substation.parse_tags), [Aegisub karaoke tags](https://aegisub.org/docs/latest/ass_tags/#karaoke-effect))

### Fonts, emoji, and Windows

**[verified-data] Reproducible libass rendering requires explicit font inputs.** FFmpeg’s subtitle filter accepts a `fontsdir` in addition to the system font provider, and libass describes itself as a portable ASS/SSA renderer with platform font-provider support. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [libass project](https://github.com/libass/libass))

**[single-opinion] Bundle or provision one licensed caption font, pass its directory through `fontsdir`, and preflight the requested family before rendering.** Do not make the host’s Windows font inventory part of the output contract. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [libass changelog](https://raw.githubusercontent.com/libass/libass/master/Changelog))

**[verified-data] Unicode line breaking is build-sensitive.** FFmpeg documents that `wrap_unicode` needs libass 0.17.0 or newer built with libunibreak, except for native ASS input. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1))

**[single-opinion] Do not depend on host color emoji rendering in Sprint 1.** Noto documents both a color CBDT/CBLC font and a monochrome emoji font, while FFmpeg/libass only promise font lookup and ASS rendering, not a cross-platform color-emoji contract. Prefer a bundled monochrome glyph fallback or a raster overlay, then verify a rendered frame. ([Noto Emoji project](https://github.com/googlefonts/noto-emoji), [FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [libass project](https://github.com/libass/libass))

### Failure modes to guard

| Failure mode | Guard |
|---|---|
| **[verified-data]** Incorrect ASS layout after source aspect-ratio changes. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1)) | **[single-opinion]** Supply `original_size` when rendering authored ASS whose script resolution differs from the output. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1)) |
| **[verified-data]** Shell/filtergraph escaping corrupts direct subtitle text. ([FFmpeg escaping rules](https://ffmpeg.org/ffmpeg-utils.html#Quoting-and-escaping), [FFmpeg filtergraph escaping](https://ffmpeg.org/ffmpeg-filters.html#Notes-on-filtergraph-escaping)) | **[single-opinion]** Write ASS and the complex filtergraph to files instead of interpolating caption text into a shell command. ([FFmpeg escaping rules](https://ffmpeg.org/ffmpeg-utils.html#Quoting-and-escaping)) |
| **[verified-data]** `-filter_complex_script` is deprecated. ([FFmpeg deprecation change](https://ffmpeg.org/pipermail/ffmpeg-cvslog/2024-January/140522.html), [current FFmpeg tool syntax](https://ffmpeg.org/ffmpeg.html)) | **[single-opinion]** Use current file-loaded option syntax, `-/filter_complex graph.txt`. ([FFmpeg deprecation change](https://ffmpeg.org/pipermail/ffmpeg-cvslog/2024-January/140522.html), [current FFmpeg tool syntax](https://ffmpeg.org/ffmpeg.html)) |
| **[practitioner-consensus]** Output varies when font fallback or renderer versions vary. ([libass changelog](https://raw.githubusercontent.com/libass/libass/master/Changelog), [FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1)) | **[single-opinion]** Pin/probe FFmpeg capabilities, provide fonts explicitly, and test rendered semantics rather than trusting container success. ([libass changelog](https://raw.githubusercontent.com/libass/libass/master/Changelog), [FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1)) |

## 2. Voice-over ducking and loudness

### Sidechain semantics and initial settings

**[verified-data] `sidechaincompress` processes its first input according to the level of its second input.** Its documented controls include threshold, ratio, attack, release, knee, RMS/peak detection, channel linking, makeup, sidechain gain, and wet/dry mix. ([FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress))

**[single-opinion] Feed music first and voice second, starting with `threshold=0.1:ratio=8:attack=20:release=250:knee=2.828:detection=rms:link=maximum:makeup=1:mix=1`.** These are tuning seeds, not a universal “correct” preset; validate them against speech audibility, pumping, and post-mix loudness. ([FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress))

**[single-opinion] Delay or trim the voice track to its intended timeline position before it reaches the sidechain.** Because the second input directly controls gain reduction, misaligned voice timing necessarily produces misaligned ducking. ([FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress), [FFmpeg adelay](https://ffmpeg.org/ffmpeg-filters.html#adelay))

**[single-opinion] Define the complete audio timeline before implementation: whether clip audio survives, how gaps sound, whether a music bed loops or pads, and whether `AudioTrack.duration` trims or pads media.** FFmpeg provides distinct trim, delay, silence, loop, and mix operations, so the schema alone cannot safely choose among them. ([FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html#Audio-Filters))

### Two-pass loudness normalization

**[verified-data] FFmpeg `loudnorm` supports single- and double-pass EBU R128 normalization.** A linear second pass requires `measured_I`, `measured_LRA`, `measured_TP`, and `measured_thresh`; when the requested target conditions are not satisfied, FFmpeg reverts to dynamic mode. Dynamic mode upsamples to 192 kHz for true-peak detection, so the output sample rate should be stated explicitly. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))

**[single-opinion] Run pass 1 on the final mixed programme with JSON output, feed every measured value and the reported offset into pass 2, request `linear=true`, write 48 kHz stereo, and run a final measurement-only verification.** The verification catches fallback or target misses instead of assuming the second command did what was requested. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [FFmpeg JSON print format](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))

**[verified-data] Spotify publishes a playback normalization reference of -14 LUFS and advises masters at -14 LUFS to remain below -1 dBTP, or below -2 dBTP for louder masters that may incur more lossy-encoding distortion.** This is a Spotify recommendation, not proof of one shared TikTok, Instagram, and YouTube target. ([Spotify loudness normalization](https://support.spotify.com/sg-en/artists/article/loudness-normalization/))

**[single-opinion] Treat `I=-14`, `TP=-1`, and `LRA=7` as Zing’s house output target for Sprint 1, not as a universal social-platform law.** The loudness and true-peak values have a published streaming reference; the LRA cap is a project choice that should be revisited with actual short-form material. ([Spotify loudness normalization](https://support.spotify.com/sg-en/artists/article/loudness-normalization/), [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))

### Audio pitfalls

- **[verified-data]** Omitting an explicit output sample rate can leave the dynamic normalizer’s 192 kHz rate in the graph. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))
- **[verified-data]** Linear normalization can silently use dynamic mode when its target constraints are not satisfiable. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))
- **[single-opinion]** A voice track used for both audible mix and sidechain control should be split deliberately so graph changes do not consume the only labelled pad. ([FFmpeg split/asplit](https://ffmpeg.org/ffmpeg-filters.html#split_002c-asplit), [FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress))
- **[single-opinion]** Do not normalize voice and music independently to the final programme target; their later mix changes programme loudness and true peak. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [EBU R128](https://tech.ebu.ch/publications/r128))

## 3. Vertical video scaling and encoding

### Fit, pad, and crop

**[verified-data] FFmpeg can preserve aspect ratio while scaling down to fit, make dimensions divisible by two, reset sample aspect ratio, and center the result with `pad`.** These behaviors are explicit `scale` and `pad` options. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg pad](https://ffmpeg.org/ffmpeg-filters.html#pad))

**[single-opinion] Use this conceptual Sprint 1 normalization chain for every visual segment:**

```text
scale=1080:1920:
  force_original_aspect_ratio=decrease:
  force_divisible_by=2:
  reset_sar=1,
pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,
fps=30,
format=yuv420p,
setsar=1
```

**[single-opinion]** The chain chooses a deterministic 1080×1920, 30 fps, square-pixel contract and preserves every source edge. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg pad](https://ffmpeg.org/ffmpeg-filters.html#pad), [FFmpeg fps](https://ffmpeg.org/ffmpeg-filters.html#fps), [FFmpeg format](https://ffmpeg.org/ffmpeg-filters.html#format-1))

**[verified-data] A fill policy is also expressible by scaling with `force_original_aspect_ratio=increase` and applying a centered crop.** It necessarily removes content outside the output rectangle. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg crop](https://ffmpeg.org/ffmpeg-filters.html#crop))

**[single-opinion] Do not silently crop in Sprint 1.** Add fill/crop only after a schema or explicit render option can communicate that composition choice. ([FFmpeg crop](https://ffmpeg.org/ffmpeg-filters.html#crop))

### x264 choices for 1080×1920 at 30 fps

**[verified-data] FFmpeg’s libx264 wrapper exposes both preset and CRF controls.** FFmpeg delegates the full set of encoder choices to x264. ([FFmpeg libx264](https://ffmpeg.org/ffmpeg-codecs.html#libx264_002c-libx264rgb))

**[practitioner-consensus] HandBrake’s x264 guidance places 1080p constant-quality work in RF 20–24, and describes encoder presets as a speed-versus-compression-efficiency tradeoff.** Lower RF means higher quality; a slower preset can usually achieve similar quality at a smaller size. ([HandBrake quality guidance](https://handbrake.fr/docs/en/latest/workflow/adjust-quality.html), [HandBrake presets and tunes](https://handbrake.fr/docs/en/latest/technical/video-presets-tunes.html))

**[single-opinion] Default to `libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart`, with AAC 48 kHz stereo.** CRF 20 favors caption edges at the high-quality end of the documented 1080p range; `medium` is a reasonable initial balance, and `fast` is the first fallback if the low-single-digit-minute runtime budget is missed on the target PC. ([HandBrake quality guidance](https://handbrake.fr/docs/en/latest/workflow/adjust-quality.html), [FFmpeg libx264](https://ffmpeg.org/ffmpeg-codecs.html#libx264_002c-libx264rgb), [FFmpeg faststart](https://ffmpeg.org/ffmpeg-formats.html#mov_002c-mp4_002c-ismv))

**[verified-data] YouTube’s published upload guidance supports MP4, H.264 progressive video, 4:2:0 chroma, the source frame rate, AAC-LC stereo at 48 kHz, and front-loaded metadata for streaming.** It is a compatibility reference rather than a requirement for every Zing destination. ([YouTube encoding settings](https://support.google.com/youtube/answer/1722171?hl=en))

## 4. Evaluation methodology

### Fixture design

**[practitioner-consensus] Keep regression samples tiny and deterministic.** FFmpeg’s FATE instructions explicitly ask for samples to be as small as possible and use them across operating systems and architectures. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html))

**[verified-data] FFmpeg’s lavfi sources can generate deterministic visual and audio fixtures without checked-in media.** `testsrc2` supports more pixel formats than `testsrc`; `color` produces a uniform image; `sine` is documented as bit-exact; and `anullsrc` produces silence. ([FFmpeg video sources](https://ffmpeg.org/ffmpeg-filters.html#Video-Sources), [FFmpeg audio sources](https://ffmpeg.org/ffmpeg-filters.html#Audio-Sources))

**[single-opinion] Generate a 9–12 second fixture at test time with three hard-cut color/test segments, fixed 30 fps, one short spoken sample when speech-ratio scoring is enabled, a sine music bed, and a small truth JSON manifest.** The manifest should separate facts from scorer tolerances and record the generator command and expected segment/caption/audio events. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html), [FFmpeg video sources](https://ffmpeg.org/ffmpeg-filters.html#Video-Sources), [FFmpeg audio sources](https://ffmpeg.org/ffmpeg-filters.html#Audio-Sources))

**[single-opinion] Tone and silence are valid render fixtures but cannot honestly establish a speech-time ratio.** Until a deterministic spoken fixture exists, report that submetric as unavailable rather than treating tone as speech. ([FFmpeg sine source](https://ffmpeg.org/ffmpeg-filters.html#sine), [FFmpeg silence detection](https://ffmpeg.org/ffmpeg-filters.html#silencedetect))

### Tolerances and matching

| Measurement | Sprint 1 scoring rule | Basis |
|---|---|---|
| Cut count | **[single-opinion]** Exact count after one-to-one matching. | Counts are discrete, while FFprobe can expose frames and timestamps in JSON. ([FFprobe output](https://ffmpeg.org/ffprobe.html)) |
| Cut timing | **[single-opinion]** Pass at ±0.15 s per the binding sprint requirement; also report the stricter diagnostic error in frames and flag values over one 30 fps frame (≈0.0333 s). | Fixed frame rate gives a frame-sized diagnostic, but the scorer must not silently tighten the specified gate. ([FFmpeg fps](https://ffmpeg.org/ffmpeg-filters.html#fps), [FFprobe frame output](https://ffmpeg.org/ffprobe.html)) |
| ASS event timing | **[single-opinion]** Compare serialized event times within 0.01 s; compare visible onset/offset within one output frame. | Karaoke durations are centiseconds and rendered output is quantized to frames. ([Aegisub karaoke tags](https://aegisub.org/docs/latest/ass_tags/#karaoke-effect), [FFmpeg fps](https://ffmpeg.org/ffmpeg-filters.html#fps)) |
| OCR caption text | **[single-opinion]** Unicode NFKC → casefold → whitespace collapse → punctuation removal, then one-to-one temporal matching with normalized Levenshtein similarity ≥0.8. | OCR output is textual and order-sensitive; the 0.8 threshold comes from the binding sprint requirement, while normalization makes the comparison explicit. ([Unicode normalization report](https://www.unicode.org/reports/tr15/), [Python Unicode normalization](https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize)) |
| OCR timing | **[single-opinion]** Report, but do not add a new gate; at a 4 fps OCR sample rate, observations are quantized to 0.25 s before output-frame uncertainty. | Sampling rate determines observation granularity; FFmpeg’s `fps` filter documents frame selection at a requested rate. ([FFmpeg fps](https://ffmpeg.org/ffmpeg-filters.html#fps)) |
| Speech-time ratio | **[single-opinion]** Use the binding ±0.1 gate only with a real spoken fixture; otherwise mark unavailable. | Silence detection measures levels and durations, not semantic speech. ([FFmpeg silencedetect](https://ffmpeg.org/ffmpeg-filters.html#silencedetect)) |
| Runtime | **[single-opinion]** Record wall time, input duration, real-time factor, platform, CPU, and FFmpeg version; enforce only the sprint’s agreed target machine budget. | FFmpeg exposes benchmark timing, while performance depends on encoder preset and host. ([FFmpeg benchmark option](https://ffmpeg.org/ffmpeg.html), [HandBrake performance discussion](https://handbrake.fr/docs/en/1.7.0/technical/performance.html)) |

**[single-opinion] Use maximum-cardinality one-to-one temporal matching before averaging errors.** Without one-to-one matching, duplicate predictions can claim the same truth event and inflate precision or recall. Report matched, missed, and extra events separately. ([SciPy linear sum assignment documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html))

**[single-opinion] Implement the small matching and normalized-Levenshtein routines in the standard library rather than adding SciPy solely for fixture scoring.** The assignment formulation is useful, but the Sprint 1 fixtures are small enough for a deterministic dynamic-programming or exhaustive matcher. ([SciPy linear sum assignment documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html), [Python standard library policy](https://docs.python.org/3/library/))

### Render assertions

**[verified-data] FFprobe can emit selected container, stream, packet, and frame fields as JSON and can count packets or frames.** Its interval seeking is not guaranteed to be exact, so exact-frame tests should decode/select the desired frame rather than assume `-read_intervals` lands precisely. ([FFprobe documentation](https://ffmpeg.org/ffprobe.html))

**[single-opinion] Each render integration test should assert duration tolerance, exactly one expected video stream, expected audio presence, 1080×1920 dimensions, 30/1 frame rate, square sample aspect ratio, yuv420p pixel format, 48 kHz stereo audio, and non-empty decoded frames.** These are observable fields, not just evidence that FFmpeg exited zero. ([FFprobe documentation](https://ffmpeg.org/ffprobe.html), [YouTube encoding settings](https://support.google.com/youtube/answer/1722171?hl=en))

**[single-opinion] Also probe content semantics: sample a segment midpoint for expected dominant color, measure audio windows for silence/signal and ducking, validate generated ASS text/times directly, and compare a caption-on frame with a nearby caption-off frame.** FFmpeg supplies decoded frame selection plus signal statistics such as `astats`; these checks catch wrong ordering and invisible overlays that container metadata cannot. ([FFmpeg select](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect), [FFmpeg astats](https://ffmpeg.org/ffmpeg-filters.html#astats), [FFprobe documentation](https://ffmpeg.org/ffprobe.html))

**[verified-data] FFmpeg’s `framemd5` and `framehash` muxers hash decoded packets or frames, with MD5 and SHA-256 respectively.** They are useful for a pinned local renderer regression, but they do not replace semantic assertions across FFmpeg/libass builds. ([FFmpeg framemd5/framehash](https://ffmpeg.org/ffmpeg-formats.html#framemd5))

### Mutation matrix

**[single-opinion] The scorer must fail each of these deliberate corruptions in pytest:** delete a cut; add a duplicate cut; shift a cut beyond 0.15 s; reuse one truth event twice; delete a caption; replace caption text below 0.8 similarity; move a caption outside its temporal match window; change speech ratio by more than 0.1; swap width and height; remove audio; and corrupt the report schema. ([FFprobe documentation](https://ffmpeg.org/ffprobe.html), [Unicode normalization report](https://www.unicode.org/reports/tr15/), [mutmut README](https://github.com/boxed/mutmut))

**[single-opinion] Mutation success means the intended submetric and overall gate fail for the intended reason, while unrelated submetrics remain stable.** That distinguishes a sensitive evaluator from one that merely crashes on malformed input. ([mutmut README](https://github.com/boxed/mutmut), [FFmpeg FATE](https://www.ffmpeg.org/fate.html))

### CI and reporting

**[single-opinion] CI should print FFmpeg version/build configuration and fail early when required filters or encoders are absent.** The minimum probe set is `ass` or `subtitles`, `sidechaincompress`, `loudnorm`, `libx264`, and AAC. FFmpeg exposes filter and encoder listings through its command-line tools. ([FFmpeg tool documentation](https://ffmpeg.org/ffmpeg.html), [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html))

**[single-opinion] Run the full deterministic gate on Ubuntu and a focused render smoke on Windows.** The Windows smoke should exercise path quoting, the file-loaded filtergraph, font lookup, and a real FFmpeg subprocess, because those are platform boundaries not covered by pure unit tests. ([FFmpeg escaping rules](https://ffmpeg.org/ffmpeg-utils.html#Quoting-and-escaping), [FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1))

**[single-opinion] Emit both a readable summary and versioned JSON containing fixture hashes, scorer version, FFmpeg version, platform, per-event matches/deltas, unmatched events, submetric scores, runtime, and pass/fail reasons.** FATE’s cross-platform regression model and FFprobe’s machine-readable output support retaining enough provenance to explain drift. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html), [FFprobe JSON output](https://ffmpeg.org/ffprobe.html))

## Concrete engineering picks

1. **[single-opinion] Captions:** generate ASS with `pysubs2`, raw `\kf`/`\t` overrides, explicit script resolution, one provisioned font directory, and a rendered-frame smoke test. ([pysubs2 documentation](https://pysubs2.readthedocs.io/en/latest/), [Aegisub ASS tags](https://aegisub.org/docs/latest/ass_tags/), [FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1))
2. **[single-opinion] Filtergraph transport:** write a UTF-8 graph file and pass it through current `-/filter_complex` syntax; never interpolate transcript text into the command and do not use deprecated `-filter_complex_script`. ([FFmpeg deprecation change](https://ffmpeg.org/pipermail/ffmpeg-cvslog/2024-January/140522.html), [FFmpeg escaping rules](https://ffmpeg.org/ffmpeg-utils.html#Quoting-and-escaping))
3. **[single-opinion] Audio:** align voice on the timeline, sidechain-compress music with voice, mix audible tracks, run two-pass `loudnorm` to the project’s -14 LUFS/-1 dBTP target, force 48 kHz stereo, and verify the final programme. ([FFmpeg sidechaincompress](https://ffmpeg.org/ffmpeg-filters.html#sidechaincompress), [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [Spotify loudness normalization](https://support.spotify.com/sg-en/artists/article/loudness-normalization/))
4. **[single-opinion] Video:** fit-and-pad every segment to 1080×1920 at 30 fps, square pixels, and yuv420p; encode x264 medium/CRF 20 with faststart, moving to preset fast only if the target-PC budget requires it. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg libx264](https://ffmpeg.org/ffmpeg-codecs.html#libx264_002c-libx264rgb), [HandBrake quality guidance](https://handbrake.fr/docs/en/latest/workflow/adjust-quality.html))
5. **[single-opinion] Evaluation:** use generated tiny fixtures plus a truth manifest, exact counts and one-to-one matching, binding Sprint 1 tolerances, deliberate domain mutations, FFprobe metadata, and decoded content probes. Do not add mutmut in Sprint 1. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html), [FFprobe documentation](https://ffmpeg.org/ffprobe.html), [mutmut README](https://github.com/boxed/mutmut))

## Deeper threads

1. **[single-opinion] Should Zing package a known caption font, or should the CLI require and hash a user-supplied font asset?** The answer changes redistribution, provenance, and reproducibility. ([FFmpeg subtitles filter](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1), [Noto Emoji licensing files](https://github.com/googlefonts/noto-emoji))
2. **[single-opinion] Does `AudioTrack.duration` describe source media length, audible placement length, or an expected asset invariant?** Each maps to different trim/pad/loop behavior and different sidechain timing. ([FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html#Audio-Filters))
3. **[single-opinion] Should the render contract expose fit, fill, and background styling explicitly in the schema?** The existing FFmpeg choices have visibly different content-loss behavior. ([FFmpeg scale](https://ffmpeg.org/ffmpeg-filters.html#scale), [FFmpeg crop](https://ffmpeg.org/ffmpeg-filters.html#crop), [FFmpeg pad](https://ffmpeg.org/ffmpeg-filters.html#pad))
4. **[single-opinion] Can Lane A provide a stable spoken fixture and adapter before speech-ratio scoring becomes a merge gate?** Silence-level tools cannot establish speech semantics on a sine-wave fixture. ([FFmpeg silencedetect](https://ffmpeg.org/ffmpeg-filters.html#silencedetect), [FFmpeg sine source](https://ffmpeg.org/ffmpeg-filters.html#sine))
5. **[single-opinion] Which semantic probes deserve stable golden thresholds across FFmpeg/libass upgrades, and which should remain diagnostics?** FATE supports cross-platform regression, but renderer changes can be legitimate and encoded-byte equality is too strict. ([FFmpeg FATE](https://www.ffmpeg.org/fate.html), [libass changelog](https://raw.githubusercontent.com/libass/libass/master/Changelog), [FFmpeg framehash](https://ffmpeg.org/ffmpeg-formats.html#framehash))
