# AgentCut 0.9.4 migration

No project JSON changes are required.

- Video boundaries are now rasterized to the output CFR grid with nearest-frame, half-up rounding. A visual boundary may move by at most half a frame; at 24 fps this is 20.833 ms.
- Each visual range is half-open and contains at least one frame. Adjacent clips that share a continuous boundary share the same quantized boundary, so no background frame can appear between them.
- Source EOF is materialized by repeating the last valid decoded video frame only through that clip's allocated visual range. It does not create timeline padding.
- Audio start, source in-point, duration, mastering, subtitle timing, and project duration remain expressed in exact seconds and are not frame-quantized.
- `compile` summaries now include `visualFrameRange`. NDJSON `health` reports `videoBoundaryMaterialization.mode=cfr-half-open`.

Existing 0.9.3 projects can be rendered unchanged. Review any workflow that expected a non-frame-aligned video boundary to be represented between output frames; the encoded video can only change on an output frame boundary.
