# C-Q13 real-video sources

This expansion adds three measurement cases without committing source video. Each fixture records the downloaded file's byte size and SHA-256, the exact yt-dlp format IDs, the study environment, performance timings, and hashes for every committed artifact.

No independent human annotations exist for these cases. Their provenance says so directly. They expand runtime and measurement coverage; they do not add hand-labeled accuracy claims.

## Sources

| Fixture | Coverage | Canonical source | Rights evidence | Acquisition |
| --- | --- | --- | --- | --- |
| `landscape-big-buck-bunny` | 10:34 landscape long-form | [Official Blender PeerTube upload](https://video.blender.org/w/dmhvQNzwBnrWy1iYzVv5g7) | Blender's [Big Buck Bunny project page](https://peach.blender.org/about/) identifies the film as CC BY 3.0. | yt-dlp 2026.7.4, format `480p`, MP4 |
| `x-nasa-artemis-backseat-drivers` | X-native landscape short | [NASA Artemis post](https://x.com/NASAArtemis/status/2040619776100147411) | [NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/) explain the general U.S. copyright status and the separate rules for NASA identifiers, third-party material, and implied endorsement. | yt-dlp 2026.7.4, formats `hls-936` + `hls-audio-128000-Audio`, MP4 |
| `short-daily-dweebs` | Additional landscape short | [Official Blender PeerTube upload](https://video.blender.org/w/gdfAeNysimipmpo7AbgaTp) | The official host labels the upload “Attribution.” It does not expose a version, so the manifest does not infer one. | yt-dlp 2026.7.4, format `720p`, MP4 |

The URLs and rights pages were checked on 2026-07-18. The manifest is the machine-readable source of record for titles, creators, rights caveats, format selectors, and expected media dimensions.
