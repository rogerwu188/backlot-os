# qingshan-review-agent 1.1.0 migration

Version 1.1.0 makes episode runtime and materialized visual pacing auditable final-review gates.

- New projects set `metadata.production_contract_version=2` and provide `runtime_policy`.
- Default episode target is 180 seconds, with ±10 seconds soft tolerance and ±20 seconds hard tolerance.
- Missing runtime policy on a v2 project is blocking. Legacy projects remain OPTIONAL/NOT_RUN.
- AgentCut should put `visual_signature`, `natural_unit_id`, `relationship`, and visual-information-delta metadata on materialized video clips.
- Three consecutive clips with the same visual signature are blocking.
- More than two selected sources, or more than 20 seconds, for one natural unit is blocking.
- Repair candidates replace old sources; they are not appended automatically.
- Technical safety scores never override a blocking episode-runtime or visual-pacing issue.
- E36 V28 remains immutable and is retained as a regression shape: 180 seconds planned versus 316.374349 seconds actual must fail the new runtime gate.
