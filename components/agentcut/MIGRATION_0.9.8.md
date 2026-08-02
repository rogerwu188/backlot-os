# AgentCut 0.9.8 migration

0.9.8 adds explicit pre-assembly source admission and a post-render, SHA-bound visual release gate. It does not perform platform mutations.

1. Set `sourceAdmissionPolicy.enabled=true` (or `releaseGate.required=true`) on projects that use the new contract.
2. Every admitted video clip must declare `metadata.action_required`, `metadata.source_reference_mode`, and `metadata.cadence_report_path`.
3. For `action_required=true`, add all four non-empty `action_trajectory` fields: `windup`, `contact`, `force`, and `result`.
4. Generate cadence evidence from that exact clip source. The report's `video` path must resolve to the same file as `clip.source`.
5. Treat `BLOCK_AGENTCUT_ASSEMBLY` as fatal. Do not substitute a full-cut cadence report for missing per-shot evidence.
6. Render produces a candidate, not a clean release. Run `agentcut release-validate FINAL REVIEW --project PROJECT` after the final review exists.
7. A clean release requires a `qingshan.review.report.v2` video report, full-cut/final scope, exact current-final SHA binding, and `hard_gate_passed=true`. A later file change invalidates the review.
8. `CONDITIONAL_MACHINE_ADMISSION` never authorizes automatic platform replacement. Platform deletion/replacement remains outside AgentCut and requires separate explicit authority.

Legacy projects without `sourceAdmissionPolicy`, new clip admission metadata, or `releaseGate.required` retain their previous assembly behavior. `releaseProject` still requires the existing master-audio policy, and its release coverage remains pending until a SHA-bound visual review is validated.
