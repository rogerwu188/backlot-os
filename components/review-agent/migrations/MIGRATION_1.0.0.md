# Migration 1.0.0

## New review capabilities

Video requests may provide AgentCut materialized timeline, render plan, shot recipe registry, beat grid, and SFX cue manifest evidence. New production profiles make all six shot-plan capabilities REQUIRED. Old requests remain OPTIONAL/NOT_RUN and receive no deduction.

All evidence must bind the exact candidate SHA, project ID/version, and materialized timeline file SHA. Mismatch is `STALE_EVIDENCE/ERROR`; missing required evidence is `CAPABILITY_FAIL`.

## Black and strobe authorization

Legacy `allowed_black_frames` is ignored for exemptions. Authorization must originate in a provenance-valid recipe and include exact start/end frames, reason, and approved policy. Freeze, periodic repetition, copyright, safety, and irreversible-operation gates are unchanged.

## Repairs and compatibility

Shot recipe findings create read-only repairs by recipe phase for every intersecting AgentCut clip. No repair task can publish, delete, or perform an irreversible action.

The bundled `qingshan.agentcut.shot_recipe_contract_fixture.v1` is provisional until Task4 publishes its final schema. Re-run compatibility tests and record a new production receipt before claiming overall support.
