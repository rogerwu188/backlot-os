# AgentCut 0.9.9 migration

0.9.9 adds an opt-in, post-render full-cut visual stagnation gate. Existing projects remain unchanged because `finalVisualPolicy.enabled` and `required` both default to `false`.

Release projects should copy `examples/final-visual-gate-policy.json` into the top-level `finalVisualPolicy` field and set an immutable `reportPath`. When enabled, render/renderMany analyze the staged candidate before atomic publication. A failed near-freeze or repeated-composition gate returns nonzero, removes staging, preserves any existing output, and writes a machine-readable failure report.

Standalone QA:

```sh
tools/run_agentcut.sh final-visual-validate FINAL.mp4 \
  --project PROJECT.json \
  --policy POLICY.json \
  --report FINAL_VISUAL_GATE.json
```

NDJSON uses `validateFinalVisual` with `final`, optional `project`, optional inline `policy`, and optional `report` parameters. It never authorizes platform mutation.

`action_required` does not exempt a frozen result: it is only an input promise. A freeze exemption requires actual dialogue metadata, `narrative_action_present=true`, or an auditable `allowedIntervals` entry with a reason. This prevents intended action metadata from concealing a motionless render.
