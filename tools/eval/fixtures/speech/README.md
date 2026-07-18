# Spoken evaluation fixture

`ripe-figs-spoken.wav` is a one-second excerpt from the LibriVox recording
of Kate Chopin's “Ripe Figs,” read by Alan Davis Drake. LibriVox identifies
its recordings as public domain in the United States, and the Internet
Archive item applies the Creative Commons Public Domain Dedication and
Certification (`CC-PDDC`).

The checked-in WAV is mono, 16 kHz, and exactly 16,000 PCM samples. Golden
generation concatenates this clip with FFmpeg-generated one-second silence
instead of treating a synthetic tone as speech. See `provenance.json` for
the source hashes and the reproducible extraction command.

Public-domain status can vary outside the United States. The upstream
catalog carries the same territorial notice; this fixture does not claim
broader status.
