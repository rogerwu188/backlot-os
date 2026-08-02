# AgentCut 0.9.10 migration

0.9.10 adds an auditable, strictly non-release assembly contract. It does not relax the normal source-admission or release gates.

## Conditional source contract

A cadence-failing source can enter only `NON_RELEASE_ROUGH_ASSEMBLY`, and only when all of the following are true:

- `source_admission` remains `CONDITIONAL_MACHINE_ADMISSION`;
- the original cadence report remains `FAIL`;
- `conditionalAdmissionEvidencePath` points to `qingshan.conditional_machine_admission.v1` evidence;
- the evidence candidate path and SHA-256 match the clip and the current source bytes;
- the raw review path and SHA-256 match the preserved review bytes;
- the raw review's per-media SHA, FAIL status, and blocking failure multiset match the conditional evidence;
- raw failure codes are explicitly allowed for rough review;
- confidence, selection reason, rollback point, and replacement condition are present;
- project metadata does not claim release or platform authorization.

Missing evidence, changed bytes, severe identity/story/media failures, `STANDARD` mode, or release-designated projects still return `BLOCK_AGENTCUT_ASSEMBLY`.

If `allowedConditionalFailureCodes` is omitted, the compatibility defaults are `video.periodic_duplicate` and `audio.long_silence`. If it is explicitly `[]`, no conditional failure is eligible.

## Hold slots

Use `timeline.holdSlots` to reserve a known missing interval:

```json
{
  "assemblyMode": "NON_RELEASE_ROUGH_ASSEMBLY",
  "timeline": {
    "holdSlots": [{
      "id": "E28-CW-U09",
      "start": 107,
      "duration": 13,
      "mode": "black",
      "reason": "source intentionally held",
      "replacementCondition": "replace U09 and rerun full QA",
      "releaseBlocking": true
    }]
  }
}
```

The interval counts toward project duration and suppresses only the corresponding technical `VIDEO_GAP`. It is never considered content coverage. Any unresolved hold forces `release-validate` and `final-visual-validate` to fail.

## Compatibility

Old projects remain `STANDARD`. The first CL2X-517 builder's `sourceAdmissionPolicy.roughAssemblyException` and `qingshanAudit.placeholder` fields are read as a compatibility bridge, but new builders should emit `assemblyMode`, an explicit evidence path, and `timeline.holdSlots`.

`validate`, `validate-media`, `compile`, `render`, `renderMany`, and all equivalent NDJSON methods share the same preflight. No successful result authorizes platform mutation.
