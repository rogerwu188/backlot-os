# qingshan-review-agent 0.9.0 migration

- Rule version is `qingshan.review.rules.v22`.
- Set `action_required: true` or an action-valued `action_intensity` on each action/fight/supernatural source shot.
- The action-shot near-duplicate hard gate is `near_duplicate_ratio <= 0.15`; it is evaluated per exact-SHA shot and is not averaged across a final.
- Supply `evidence_inputs.action_physics` using `qingshan.action_physics_audit.v1`, exact `candidate_sha256`, and all eight checks: `wind_up`, `contact`, `force_transfer`, `result`, `real_hand_prop_contact`, `no_floating_hands`, `no_object_drift`, `complete_action_head_tail`.
- Missing or stale action-physics evidence is a capability failure. A failed physics check or motion threshold is a content failure.
- Static dialogue shots do not inherit the action threshold unless explicitly marked.
- Review IDs change because the rule/config digest changes. No media or platform state is modified.
