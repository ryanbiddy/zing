These three CC0 JPEGs test real recognition with explicitly provisioned
OpenCV Zoo models. Synthetic shapes cannot establish recognition accuracy.

`manifest.json` records each source, author where available, license,
original or V1 excerpt hash, derivative hash, and expected class. The photos
were oriented and resized without cropping to a maximum side of 480 pixels,
then saved at JPEG quality 85. The dog source is an MPO; only its first image
is used. The Korky frame is at 1.0 seconds in the verified V1 excerpt described
in `tools/eval/real/manifest.json`.

Together the fixtures occupy 82,296 bytes. The real-model test is opt-in via
`ZING_REQUIRE_VISION=1`; it never downloads a model or image. Unit and
integration tests use mocked detections when OpenCV and models are absent.
