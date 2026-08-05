# Actor Motion Coverage Migration

BacklotOS 0.2.25 makes multi-character Seedance 2 long takes fail closed when
only the foreground action is authored.

Add one top-level `actor_roster` containing every character that may appear in
the long take. Every keyframe must provide an `actor_motion` object with exactly
the same keys. A visible actor requires `continuous_micro_action`,
`event_reaction`, and at least two positive `motion_cues`. An actor who has left
the frame requires `visible: false` plus an `offscreen_reason`.

Position locks such as "remain in the safe zone" are still valid blocking, but
they are not motion. Do not place them in motion fields. Describe breathing,
eye-line changes, weight transfer, balance recovery, protective reactions, or
other event-caused movement while preserving the assigned screen zone.

The compiler injects the complete per-actor coverage into every timestamped
keyframe instruction and records `FULL_VISIBLE_ACTOR_MOTION_COVERAGE` in the
compiled gate manifest. Missing actors, unexplained exits, and static-pose
language stop compilation before any paid provider request.

Post-generation adjudication must pass `visible_actor_count` and
`visible_actor_motion_score`. Multi-character long takes require the motion
score and apply the same 60-point threshold independently from the overall
score. This catches a globally dynamic clip whose foreground moves while its
supporting cast remains frozen.
