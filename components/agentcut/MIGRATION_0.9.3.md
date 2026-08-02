# AgentCut 0.9.3 migration

No project JSON change is required from 0.9.2.

- Keep `masterAudioPolicy.loudnessTargetLufs`, `truePeakCeilingDbtp`, `codecHeadroomDb`, and `maxClippedSamples` unchanged.
- `render` and `renderMany` automatically use measured two-pass loudnorm when a loudness target is present.
- Expect one lossless premaster pass plus a fast video-copy/audio-master pass. Temporary files are created beside the destination and removed on success or failure.
- Outputs are published with an atomic replace only after duration, loudness, true-peak, and clipping gates pass.
- Inspect `manifest.audioSafety.mastering` for the measured first-pass values and applied second-pass filter.
- A successful rerender removes a stale `<output>.failed-audio-qa.json`; a failed rerender writes that report atomically and preserves any previously published output.
