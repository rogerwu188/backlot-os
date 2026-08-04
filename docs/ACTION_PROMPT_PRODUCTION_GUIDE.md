# Action Prompt and BGM Production Guide

BacklotOS treats prompt construction as a production gate. QA verifies results;
it is not the first place where action logic, camera intent, or music presence
should be discovered.

## Action prompt flow

1. Write one primary physical event per short action shot.
2. Give the shot explicit entry, contact, feedback, result, and exit states.
3. Name the actor who owns each ability, prop, force, and reaction.
4. Fix the screen axis, movement direction, contact point, effect footprint,
   protected props, and final handoff pose.
5. Read all earlier related action prompts before compiling the current one.
6. Reject a repeated action picture even when wording, lens, or camera motion is
   different.
7. Generate dependent action shots in order so the earlier tail frame can bind
   the next start frame. Generate unrelated shots concurrently.
8. Submit only the SHA-bound optimized provider prompt after every pre-submit
   gate passes.
9. Declare the exact real-time assembly window. Provider minimum-duration tails
   are not authored footage: discard them after the result hold, preserve native
   speed, and remove only duplicate tail frames. Never hide excess duration with
   slow motion or time stretching.

## Fifteen-second multi-keyframe action takes

Use a multi-keyframe long take when the story event is spatially indivisible,
such as moving from a burning room through one wall breach into the street.
Fragmenting that event into independent clips makes the edit guess the missing
body path. Instead, submit one 15-second Seedance 2 Pro Omni task with 3-9
chronological keyframes and let the model synthesize the in-between motion.

Each keyframe must bind an existing image path and SHA, timestamp, unique action
state, location zone, actor blocking, action event, reference role, inherited
state, and a list of elements that must not be inherited. Timestamps start at
0, end at 15, and strictly increase. Adjacent frames explicitly forbid
teleporting and action reset. A location-zone change additionally names the
same physical aperture and crossing direction. The compiler rejects Fast,
non-1080p output, slow motion, camera roam/orbit/sway, repeated action states,
missing reference duties, or a broken crossing contract before any paid call.

Generate related keyframes serially from the accepted predecessor frame.
Independent dialogue, QA, and unrelated action chains remain parallel. If an
inline image payload is too large, create visually equivalent 1080p transport
copies and rebind their SHA values; never resend the same timed-out payload.

Before each paid long-take compilation, the compiler loads the bundled local
LoRA-ready failure-memory dataset. Admitted failure/rewrite/pass pairs inject a
deterministic guard clause and are recorded by sample ID and dataset SHA in the
compiled manifest. Multiple image references may have only one
`STATE_AUTHORITY` for geometry, camera, actor blocking, and scale. Remove any
secondary reference with conflicting geometry; prose-only negative isolation
is not reliable. The bundled dataset is deployable immediately as a rule
adapter and can later train model weights without changing its evidence schema.

Long-take review uses a 60-point admission threshold. Scores at or above 60 are
retained unless identity, safety, era, OCR, or media-integrity hard failures are
present. Minor taste or polish issues above the threshold do not authorize a
paid regeneration.

Before assigning percentages, preserve the story function of every action prop.
An environmental barrier must remain grounded architecture; a footprint repair
cannot silently turn it into a handheld shield, floating rectangle, or other
easier object. Declare `action_prop_function_contract` with a required function
class, forbidden classes, and positive/negative prompt terms. Declare human and
architectural relationships in `action_scale_contract`; frame ratios are only a
secondary check after those real-world relationships pass.

Use `action_causality_contract` to allow exactly one visible physical phase per
generated action shot. Formation, contact, recoil, and terminal consequence are
separate phases when any one of them would become unreadable in the provider's
minimum clip duration. Compile the phase plan with
`action_causal_chain_compiler.py`; every dependent phase uses the accepted tail
of its predecessor, while unrelated generation, polling, and QA stay parallel.

For multi-actor movement, declare `action_movement_lane_contract` before prompt
optimization. Give every actor a named floor corridor, require a real-world
minimum lateral clearance, and bind positive separation terms plus forbidden
overlap language. The pre-submit gate rejects missing lanes, intersecting body
paths, authored torso overlap, and prompts that leave clearance implicit.

Any shot with a readable result hold must also declare
`action_terminal_support_contract`. Bind the terminal body to explicit support
points such as both feet on the floor, a hand on a beam, or a verified airborne
exception with no hold. Transitional raised-foot or airborne poses cannot be
stretched across the provider minimum duration as artificial slow motion.

For a task using `generation_schedule_mode=TAIL_CHAINED_SERIAL`, declare an
`action_sequence_contract.chain_id`, numeric `sequence_index`,
`depends_on_task`, and `predecessor_tail_frame_ref`. At submission time there
may be only one ready task for that chain. For every index after the first, the
predecessor tail file must already exist and must be the first
`reference_image_sequence` entry with role
`EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME`. A path that merely predicts a
future tail, a generic action still, or a simultaneously submitted successor
fails before provider spend.

When the predecessor passes, the supervisor extracts its final frame and
replaces the dependent task's generic temporal entry in both
`reference_images` and `reference_image_sequence`. Identity and other
non-temporal entries are retained in their existing order. Merely inserting the
tail into one field is invalid because provider transport and the submission
gate would otherwise disagree about the authoritative first frame.

Dynamic anchor counts describe temporal states, not every provider reference.
Identity, character, style, scene, and composition-only references remain
available to the model but do not inflate temporal interpolation counts. A
start plus a non-interpolable terminal target is two temporal anchors even when
additional identity and ownership-composition references are supplied. Mark a
provider-visible ownership or composition guide with a role containing
`REFERENCE_ONLY`; it is still forwarded to the model but is excluded from the
temporal-state count and adjacent-keyframe pair calculation.

Use `components/pipeline-tools/action_prompt_pipeline_cli.py` with the bundled
example manifest. It writes optimized prompt files, a compiled manifest, and a
single pre-submit report covering optimization, spatial feasibility, sequence
continuity, direction, and actor ownership.

## Dependency-lane concurrency

The episode supervisor does not wait for a whole batch. Every scheduling wave
contains all ready independent shots plus the earliest ready member of every
`TAIL_CHAINED_SERIAL` chain. A later member of the same chain remains deferred
until its predecessor passes and its accepted tail has been rebound as the
successor's first provider image. Different chains still advance concurrently.

Submission, remote polling, and completed-output QA use separate bounded worker
pools. Set `max_submit_workers` and `max_poll_workers` (default `8`) and
`max_qa_workers` (default `4`) in the batch config. Receipts store the selected
and deferred task keys for every submission wave, making restarts deterministic
and preventing a dependency in one lane from freezing unrelated work.

## Camera discipline

Camera movement must reveal information or preserve an action relationship. Do
not stack `smooth_roam`, `slow_push`, overhead reveals, or equivalent movement
families across adjacent clips. Dialogue and evidence shots default to a stable
camera. A dialogue, evidence, or exposition unit longer than three seconds must
declare a motivated fixed-composition hard cut, reaction cut, or evidence insert;
continuous camera movement cannot substitute for shot design. Action shots
default to normal real-time speed and one readable contact.

Every action unit also declares `assembly_window_contract`. Its trim end may not
exceed `primary_action_complete_by_seconds + result_hold_seconds + 0.25`, the
window may not exceed 2.5 seconds, `preserve_native_speed` must be true, and an
unused provider tail must be marked `DISCARD_UNAUTHORED_TAIL`. The same gate runs
in the prompt compiler and the concurrent episode supervisor, so a malformed
task cannot reach a paid provider submission or later assembly.

## Selective BGM flow

Every release episode must choose one source policy:

- `GENERATED_EPISODE_BGM`: record task ID, generation receipt, source SHA, and
  exact Pay/Refund/Net evidence.
- `LIBRARY_FALLBACK`: record the music ID, fallback reason, rights evidence, and
  a passing cross-episode similarity report.

The project must contain `metadata.bgm_contract`,
`metadata.bgm_cue_policy.mode=SELECTIVE_NARRATIVE_CUES`, and a real
`Audio.BGM` track. Each clip declares a cue role and whether dialogue is present.
Dialogue cues use volume `<=0.16`; non-dialogue cues use `<=0.32`; the contract
declares ducking between -10 and -6 dB.

BGM may cover at most 85% of the story runtime and must leave at least eight
seconds for native ambience alone. A rendered selective-cue solo stem must
measure at least -40 dB global mean and -18 dB peak, while the per-cue spectral
gate carries the stricter dialogue-masking decision. The final mixed file must exist. Missing music
is a hard failure unless an explicit, evidence-backed creative exemption is
added by a future versioned policy.

## Release checklist

Run the BGM authenticity gate against the final project, solo stem, and mixed
master. For release projects, set
`metadata.bgm_cue_policy.spectral_masking_gate_required=true` and pass
`--baseline` with the equivalent no-BGM master. The gate decodes every dialogue
cue at normal speed, checks the 300-3400 Hz speech band, requires music to remain
at least 12 dB below the dialogue-band mean, limits mixed mean/peak increases to
1.0/1.5 dB, and rejects touching cue-role handoffs above a 6 dB stem step. This
pre-release gate does not replace the final subjective full-cut listen.

Then run normal AgentCut full-cut review, cadence, subtitle, branded
outro, audio safety, and release validation. Platform publication remains a
separate irreversible action and is never implied by a passing media gate.
