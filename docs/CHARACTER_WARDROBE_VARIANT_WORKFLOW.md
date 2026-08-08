# Character wardrobe variant workflow

A recurring character's immutable identity and episode wardrobe are separate assets. A costume change must never be regenerated inside a shot prompt or treated as permission to change the face, age, body, hair, or voice.

## Required lifecycle

1. Resolve the character's immutable identity parent and verify its exact SHA-256.
2. If the requested costume variant is already registered and its file, manifest, identity-QA receipt, and SHAs still pass, reuse it. Do not regenerate it.
3. Otherwise derive one versioned turnaround from the identity parent. Change only the authorized wardrobe state.
4. Human-QA the result for same face, age, body, hair, period, and complete costume. Persist the receipt and exact asset SHA.
5. Promote the accepted image out of working storage into the versioned reference library. Keep the working source for audit; do not overwrite the identity parent.
6. Add one stable `wardrobe_variant_id` to both the character registry and the episode State Bible. The registry entry must bind:
   - reference image path and SHA;
   - identity parent path and SHA;
   - asset manifest path and SHA;
   - identity-QA path and SHA;
   - allowed context, change reason, and `identity_verification=PASS`;
   - `verification_status=PASS`.
7. Bind every image/video production manifest to the same variant ID and reference path. Run `asset_binding_validator.py` before any paid submission.

## Fail-closed conditions

Production is blocked when any of the following is true:

- a wardrobe change is requested without a registered `wardrobe_variant_id`;
- the variant is missing, unverified, or does not have same-face/same-body PASS;
- any declared asset, parent, manifest, or QA SHA differs from disk;
- the episode State Bible selects a different variant than the production manifest;
- the production reference path differs from the registered wardrobe asset;
- a shot prompt tries to override the registered costume from text alone.

This makes costume generation a one-time asset-library operation. Later episodes or shots reuse the accepted variant by exact SHA whenever continuity permits.

## Scheduling invariant

An action-chain dependency is task-local. Before a scheduler records a global wait, run `task_lane_global_wait_gate.py`. A READY zero-cost task or an active QA task makes global wait invalid; `WAITING_DEPENDENCY` requires an exact predecessor task ID; remote waits must be `TASK_LOCAL` and cannot mask READY work in another lane.
