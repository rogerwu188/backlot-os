# 0.5.0 migration

- Final-video reviews now require a full decoded-frame black-frame scan (`qingshan.black_frame.v1`). Every unapproved pure/near-pure black frame emits frame, time and pblack evidence and blocks release. Scanner errors also block.
- AgentCut mixed audio tracks recover dialogue IDs from legacy clip IDs such as `E20-DIA-022-AUDIO`, align them to materialized script/video order, and expose expected/audio order plus mapping counts. Explicit zero-sentence PASS evidence is rejected.
- Brightness jumps of 20 luma or more require per-boundary `evidence_file`, `reason`, `confidence>=0.9` and `raw_jump_preserved=true`. Only then is `PASS_WITH_ADJUDICATION` permitted; otherwise the raw jump remains a blocking finding.
- Existing periodic duplicate, freeze, OCR, audio, ASR and story-duration thresholds remain unchanged.
- Agent version is 0.5.0; rules are `qingshan.review.rules.v16`. Final report/request schema identifiers remain compatible.
