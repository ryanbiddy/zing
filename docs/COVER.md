# Make a cover from a video frame

`zing cover` puts type over a frame you choose from your footage. It renders a finished JPEG or PNG for each style and size you select. Open `out/sheet.jpg` to see them together.

If you have already studied the video, run `zing thumbs VIDEO --json`. Pick a candidate and pass its `frame_path` to `zing cover new`. You can copy a PNG, JPEG or WebP still, or take a frame directly from a local video.

## Pick a style

| Style | When to use it | What to write |
|---|---|---|
| `clipping` | The source's name and the person in the news are both part of the story. A tear in the newspaper reveals the face. | Set the masthead in type. Add a kicker, dateline and a passage from the transcript. The optional headline appears on square and vertical covers. You can set an accent such as `#8c1d2c` and a short credit. |
| `plate` | One short phrase reads well in two beats. | Split it between `top` and `bottom`. The first line sits on black, the second on yellow. Add a `tag` if the viewer needs a credit. |
| `number` | The speaker gives a figure that explains the moment. | Put the figure and unit in `figure`. Explain what it measures in `label`. The optional `tag` appears on wide and tall covers. |
| `quote` | Hearing the speaker's own words makes you want to hear what comes next. | Copy the line into `text`. Copy the phrase to mark in yellow into `highlight`. Put one or two credit lines in the `by` list. The page adds quotation marks. |

## Pick a size

| Size | Shape | Base pixels | Use |
|---|---|---|---|
| `wide` | 16:9 | 1920 × 1080 | YouTube video thumbnail |
| `tall` | 9:16 | 1080 × 1920 | Shorts, Reels and TikTok covers |
| `square` | 1:1 | 1080 × 1080 | Podcast art, X and LinkedIn |
| `portrait` | 4:5 | 1080 × 1350 | Instagram feed |

Use `--scale 2` to double both dimensions. A wide cover becomes 3840 × 2160, YouTube's recommended video thumbnail size. Zing lowers JPEG quality as needed to keep wide JPEGs under 2 MB. [YouTube thumbnail guidance](https://support.google.com/youtube/answer/72431)

## Make the first cover

Rendering uses Node.js 20 or newer, the factory sidecar and a local Chrome or Edge installation. Run `zing factory setup` once to install the sidecar. FFmpeg is needed when extracting from a video.

```console
zing cover styles
zing cover new ./cover --frame ./chosen-frame.jpg --style number
```

To take a frame at 32 seconds instead, start a new folder with `zing cover new ./cover-from-video --video ./episode.mp4 --at 32`. The frame keeps its source resolution. If the layout extra and verified YuNet model are available, Zing uses the largest detected face. Otherwise it reports a centred default box. Adjust the box before rendering.

For example, in NASA's interview with Kayla Barron, she says she had a missed call four minutes before she got back to her phone. Here is a number cover for the 1280 × 720 example frame. For your own frame, keep the dimensions and path written by `new`. [Source interview](https://www.youtube.com/watch?v=8A-6NoJbsFg)

```json
{
  "version": 1,
  "seed": 11,
  "frame": {
    "src": "frame.jpg", "w": 1280, "h": 720,
    "face": {"cx": 0.477, "cy": 0.33, "fh": 0.31}
  },
  "source": {
    "name": "Houston We Have a Podcast, Episode 136",
    "url": "https://www.youtube.com/watch?v=8A-6NoJbsFg",
    "date": "2020-03-06",
    "rights": "public-domain"
  },
  "said": "And sure enough, I got back to my phone right after the parade, and four minutes before that, I had a missed call.",
  "number": {"figure": "4 MIN", "label": "I had a missed call", "tag": "Kayla Barron"}
}
```

`cx` and `cy` locate the centre of the face as fractions of the frame width and height. `fh` is the fraction of the frame height covered by the face. The square face box must fit inside the picture. The seed controls the tear and defaults to 11.

```console
zing cover check ./cover --json
zing cover render ./cover --style number --size wide,portrait --scale 2
```

Open `out/number-wide.jpg` and `out/number-portrait.jpg`. The sheet and receipt describe the latest render. The receipt includes the frame hash, rights, drawn text, fonts, checks, dimensions, byte counts and JPEG quality. Use `--format png` for PNG covers. The sheet is always a JPEG.

The defaults render all sizes for every style block in the file. Omit unused blocks. Naming a missing style gives an error. `check` lists every field to fix and exits with status 1 for an invalid file. A warning means the crop enlarges the face more than 2.5 times. A higher-resolution source adds detail. Rendering measures the final type and names any field that needs shorter text.

## Keep the promise

The masthead tells viewers who the story comes from. Use the real source or a name the speaker actually says. The check looks for whole words in `source.name` or `said`. Mentioning a name does not establish that it published the story. Check the attribution yourself. Keep the masthead in type. Do not add a logo image.

Supply `said` to check the article and quote against the clip. The article can repeat a passage to fill its columns. The quote must occur in the transcript. Case, spacing, dash styles and straight or curly quotes can differ. A pull quote can end with a period where the speaker paused at a comma. Use the whole figure, including its sign and scale. For example, `24` matches “twenty-four” and `1.1M` matches “1.1 million”. `15K` matches “15,000”. The check reads plain spoken numbers such as “two thousand and four”. It refuses what it cannot read for sure, such as “half a million”. In that case use the figure as the transcript writes it. The check is a guard and can miss things, so confirm the number yourself. Without a transcript, the receipt records which comparisons were skipped.

Record who owns the frame or what license permits the use in `source.rights`. For your own footage, `own` is enough. You can omit the URL. Add a timestamp in seconds if you know where the frame came from. All drawn fields take plain text.

For a YouTube Test and Compare run, choose up to three visibly different styles for the same idea. Watch the first 30 seconds with each cover in hand. If someone clicked for the figure or quote, those seconds should deliver it. YouTube judges eligible tests on watch time. [YouTube A/B testing](https://support.google.com/youtube/answer/16391400)

Run `zing cover prompt` for the writing instructions you can give your agent. All five commands accept `--json`.
