# Stills and memes

Render your photo with text written by you or your AI:

```sh
python -m pip install "myzing[memes]"
zing meme ideas --topic "one quick bug fix" --n 6
zing meme check --text "one quick fix" --text "six hours later"
zing meme render --image desk.jpg --text "one quick fix" --text "six hours later" --out meme.png
```

Zing makes no model calls. Ideas are seeded formula substitutions; your AI
writes and judges the joke using `zing prompt meme-writer` or MCP
`get_prompt("meme-writer")`. `zing doctor` reports the optional `pillow`
dependency. Templates, ideas, and checks work without Pillow.

```sh
zing meme templates --search drake --json
zing meme ideas --topic "release day" --template drake --json
zing meme render --template drake --text "one more meeting" --text "ship it" --aspect original --out drake.png
```

The catalog ships 101 classic templates as metadata only. Explicitly
rendering `--template <id>` fetches its blank from api.memegen.link on the
first use; the download has a 15-second socket timeout and a 20 MiB limit.
Blanks are cached under `$ZING_HOME/memes/templates/` (default `~/.zing`).
Use `--offline` to require a cached blank. Local photos and catalog searches
never use network. No third-party meme images are bundled.

Repeat `--text` in box order. Empty strings preserve unused slots. Each box
allows 70 characters and the entire image allows 110, after whitespace
normalization. Newlines count as one character and are preserved for
rendering. Counts use Unicode code points. Checks also report banned filler
and invalid beat counts: normally 1-3, or up to the selected template's box
count. `check` exits 1 for invalid copy; JSON distinguishes a successful
check (`ok`) from passing copy (`valid`).
For custom layouts with more than three regions, check with `--box-count`.

Rendering defaults to a square. `--aspect` accepts `16:9` (1200x675), `1:1`
(1080x1080), `4:5` (1080x1350), `9:16` (1080x1920), or `original` (1200-1920
pixels wide, retaining the source ratio). Source and output images are
limited to 40 megapixels. Animated inputs use their first frame.

- `--layout classic`: outlined Anton text at the top and bottom, in capitals.
- `--layout caption`: a white caption bar with IBM Plex Sans above the photo.
- `--layout labels`: text on normalized source-image regions. Pass
  `--regions '[[0.05,0.4,0.3,0.2],[0.65,0.4,0.3,0.2]]'` for custom placement.
  Templates default to their catalog regions; some use generic rows and
  return a placement warning.

Photos default to `--fit cover`; templates default to `contain` to retain
all panels. Labels follow the source through crop and scaling. `--plate`,
`--shadow`, and `--rotation 8` add a dark rounded plate, shadow, and rotation.
Text wraps and shrinks to fit; it is never silently dropped. `--font anton`
and `--font sans` use bundled OFL fonts with licenses in `_data/fonts/`.
Use a font path or installed name such as `--font Impact` for another font.
The bundled fonts do not cover every script or emoji; use a suitable system
font for those characters.

Output supports PNG, JPEG, and WebP. Without `--out`, a unique PNG goes into
`$ZING_HOME/memes/renders/`. An explicit output path replaces that file;
the source image cannot be the output. `--workspace <dir>` overrides the
storage root. Every subcommand accepts `--json`.

MCP offers `meme_templates`, `meme_ideas`, `meme_check`, and `meme_render`.
Use `texts` for the ordered text array and `image`/`out` for input/output
paths. Render returns paths and box metadata, never inline image bytes.
Its `viral_lens` measures brevity, beats, contrast, and aspect; it does not
predict reach. Review the resulting image before sharing it.

The prompt rules, eight offline formulas, catalog, aspect sizes, and viral
lens arithmetic are ported from MemeForge's `app/api/generate/route.ts`,
`lib/meme-engine.ts`, `components/TemplateDock.tsx`, and `lib/render.ts`.
Zing adds complete multi-box ideas, region metadata, and bounded text fitting.
Font source URLs and SHA-256 digests are recorded in `_data/fonts/sources.json`.
