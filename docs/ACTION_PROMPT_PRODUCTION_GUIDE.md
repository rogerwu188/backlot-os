# Action Prompt and BGM Production Guide

BacklotOS treats prompt construction as a production gate. QA verifies results;
it is not the first place where action logic, camera intent, or music presence
should be discovered.

## Expressive native dialogue

On-camera or voice-over dialogue is compiled before paid generation. Every line
must declare `psychological_state`, `emotion`, `emotion_intensity` (1-5), `pace`,
`pause_map`, `emphasis_words`, `volume_arc`, `breath_pattern`,
`delivery_transition`, and `body_sync`. The compiler verifies that emphasis words
occur in the exact canonical line, preserves the character's frozen voice
reference, and rejects repeated identical delivery signatures across all lines
unless the script explicitly requires a deliberately monotone performance.

These fields are sent with the exact dialogue into native lip-sync video prompts;
they are not deferred to editing. Human listening remains required after
generation for emotional credibility, pronunciation, timing, and lip sync.

### Audio-driven dialogue transport

Each exact Seedance dialogue reference must be between 2 and 15 seconds. A
verified shorter line is padded with trailing digital silence and re-registered;
its voice performance is not regenerated. The default visual prompt refers to
ordered audio slots without repeating the spoken line as visible prompt text.
This is the recommended clean-source mode, not a universal ban on words in the
generated picture.

Choose one typed visual-text policy per dialogue shot:

- `AUDIO_ONLY_ISOLATION`: keep dialogue glyphs out of the provider prompt and
  add release subtitles in AgentCut.
- `EXACT_DIEGETIC_TEXT_ALLOWED`: permit story-motivated account entries,
  letters, labels, or brush writing when the exact text and source SHA are
  bound before generation.
- `EXACT_PROVIDER_CAPTION_ALLOWED`: permit provider-rendered dialogue captions
  when every line is exact, the visual style is approved, OCR and human review
  are mandatory, and AgentCut is forbidden from adding a duplicate subtitle.

Only invented pseudo-writing, misspellings, unbound text, and duplicate subtitle
layers are rejected. Provider-rendered text remains a higher-risk choice, not
an automatic failure.

## Replacement binding is an assembly hard gate

Generating a repaired asset does not complete a repair. The final timeline must
bind every declared target clip to the exact admitted replacement file SHA.
Every repair builder writes `metadata.replacementBindingPolicy` with the target
clip IDs, replacement SHAs, superseded SHAs, and recognizable legacy path
tokens. AgentCut recalculates file hashes and blocks compile, render,
final-visual approval, release validation, and upload authorization when even
one target is missing, duplicated, still points at an old file, or carries
metadata for a different source. The operator repairs the exact entries listed
in `coverage.replacementBindings.residualClips`; a later QA pass cannot waive
this failure.

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

### Task2-1 cinematic shot-language contract

Task2-1 writer output is converted into a typed
`cinematic_shot_language_contract` before provider compilation. The contract
keeps prompt responsibilities in this fixed order:

1. `LOCKED_DESCRIPTORS`: the complete character/state, location/state, and prop
   descriptor text. Each descriptor is stress-tested, SHA-256 bound, and pasted
   verbatim; an ID or a style paraphrase is not a substitute for the text.
2. `PURPOSE_GEOMETRY_TIME_CUTS`: one contiguous segment per compiled shot. Each
   segment names its narrative purpose, entry and exit state, subject anchor,
   camera side, axis relation, scale anchor, and the reason the camera moves.
3. `KEY_RULES`: scene-specific invariants such as protected props, thresholds,
   wind direction, crowd formation, or one-variable iteration discipline.
4. `AUDIO`: diegetic sound and a typed dialogue policy. Spoken words belong
   here, never inside action or camera prose.
5. `ATMOSPHERE`, `STYLE`, then `NEGATIVES`: continuity state precedes the visual
   treatment; negative constraints cannot stand in for a positive physical
   event.

The segments must start at zero, remain contiguous, follow storyboard order,
and cover the declared duration exactly. The compiler rejects unknown asset
references, descriptor text whose SHA does not match, untested assets,
decorative camera movement without motivation, timeline gaps, and unsupported
dialogue policies before a paid generation call.

Map writer fields deliberately: `shot_treatment.purpose` becomes
`narrative_purpose`; blocking and scene-map data become `geometry`; the current
continuity ledger becomes `entry_state`; the visible causal result becomes
`exit_state`; and the cut reason becomes `camera_motivation`. Complex action
starts after its initiation is already visible, then records contact, feedback,
and result rather than spending the clip on a slow setup. Change one structured
variable per retry and log that delta so an accepted improvement can be reused.

### Corpus completion is a ledger gate

Large source projects are never declared trained from a sample count alone.
`corpus_absorption_gate.py` compares the authoritative source-asset count with
unique ledger records. Every source item must finish as either `ADAPTED`, with
source URL, content SHA, license basis, dataset version, adapter version,
relations, and an evaluation receipt; or `EXCLUDED`, with a durable reason such
as duplicate SHA, corruption, privacy risk, missing source, or low quality.
Pending and missing records keep the run blocked. This makes “all assets
trained” mean complete auditable coverage, while preventing duplicate or unsafe
media from being forced into a dataset merely to raise a training count.

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

Every keyframe also declares `camera_side`, `camera_position`, and
`camera_facing`. Every adjacent transition declares its continuous camera path,
travel distance, axis change, and whether the camera crosses the same aperture
with the subjects. The compiler rejects axis changes above 90 degrees, paths
faster than 2.5 metres per second, mismatched camera endpoints, and room-to-
street crossings that cannot follow through the named aperture. This makes
physical camera reachability part of prompt generation instead of a late QA
repair.

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
The public dataset contains only redacted evidence identifiers and SHA-256
bindings, so it can be deployed on another workstation without private episode
media while retaining the exact failed-to-accepted learning relation.

Image-prompt failures are harvested as first-class training records too. For
plot-critical glyphs, deterministic AgentCut text remains the preferred path.
Provider-native text is also allowed under `EXACT_DIEGETIC_TEXT_ALLOWED` or
`EXACT_PROVIDER_CAPTION_ALLOWED`; it must bind the exact source text before
generation and pass OCR plus human review afterward. Blank surfaces are a
fallback, not a mandatory replacement for readable story information.
Records without a passing repair remain `ACTIVE_REWRITE_PENDING_POSITIVE`.
They may inject a defensive compiler clause immediately, but must not carry an
accepted asset SHA or be reported as `ADMITTED` until the replacement passes
its declared OCR, identity, physical-scale, or continuity gate.

Every installed workstation automatically synchronizes admitted LoRA-ready
memory through the repository with `local_lora_memory_sync.py`. The
synchronizer allowlists the
portable schema, rejects credentials and local/private evidence paths, merges
by immutable `sample_id`, rewrites a deterministic manifest, and pushes only
the memory dataset and manifest. Conflicting content under an existing sample
ID fails closed instead of silently choosing one machine's version. Set
`BACKLOTOS_LORA_AUTO_SYNC=0` only to disable it deliberately. A deployment
creates an isolated sync checkout unless an explicit checkout is configured.
Without GitHub write credentials, compilation continues from bundled and local
memory, persists admitted rows in a local pending queue, writes a
`QUEUED_FOR_RETRY` receipt, and retries before the next prompt compilation.
Concurrent prompt compilers share an exclusive sync lock so parallel production
cannot race Git commits. `BACKLOTOS_LORA_SYNC_CHECKOUT` and
`BACKLOTOS_LORA_SYNC_REMOTE` remain available for controlled deployments.

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

## Combat identity and outcome

Before any video prompt is compiled, the writer must complete a canonical character brief for every visible or speaking role, including one-scene opponents and background performers. The brief names the source location, era, age, social role, clothing materials and colors, face, hair, and voice. Missing details go back to writing; image generation must not invent a generic temporary character.

Freeze one SHA-verified visual and voice reference per character after historical-library and same-episode pairwise similarity audits pass. Unless the script explicitly requires look-alikes, excessive face, wardrobe, or voice similarity blocks production. The frozen identity remains constant through every keyframe and video frame; wardrobe-color drift such as black clothing becoming grey is a hard failure.

For combat, prose such as "they exchange blows" is never a sufficient action
plan. Add `combat_choreography_contract` with 3-6 contiguous beats, each no
longer than three seconds. Every beat binds initiator, target, named technique,
contact point, force direction, footwork, target reaction, and end state. Every
participant requires a different SHA-bound identity reference, a visibly
different wardrobe silhouette and face geometry, plus a measurable first-second
displacement.

An action-reference video is mandatory and may contribute only choreography
timing and body mechanics; it cannot contribute identity, wardrobe, scene,
camera, or outcome. The contract separately names the winner and restrained
actor. Identity inversion, a frozen visible actor, or the wrong actor being
restrained is a hard failure regardless of the aggregate 60-point score.

Release repair must preserve audience readability. Blur, defocus, or depth-of-
field degradation is not an OCR repair for evidence, documents, faces, hands,
or people. Regenerate a clean textless source or use an opaque authored prop
surface and add intentional glyphs in AgentCut. Release subtitles retain the
approved font-and-outline style; an opaque subtitle box requires an explicit
episode creative brief and cannot cover model-generated text.

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

Writing `real-time 1x` or `no slow motion` is not sufficient: the timestamps
must also describe physically credible performance speed. Every action-like
prompt is classified from both structured fields and prompt text, so omitting
`action_unit=true` cannot bypass the tempo gate. Add
`performance_tempo_contract.atomic_action_windows` with the start, end, and
named physical action for every landing, approach, lunge, strike, interception,
recoil, or restraint.

Combat is authored faster than ordinary movement for screen impact without
speeding up playback. A fight or chase must show measurable body displacement
or attack intent within 0.5 seconds, each atomic attack/defence beat must
complete within 1.2 seconds, and idle gaps between beats may not exceed 0.25
seconds. Prefer 3-6 contiguous causal beats with readable contact and reaction.
Do not allocate two seconds to a simple landing or four seconds to walking a
few steps: those timestamps instruct the provider to synthesize slow
performance even when the negative prompt says `no slow motion`.

Every action unit also declares `assembly_window_contract`. Its trim end may not
exceed `primary_action_complete_by_seconds + result_hold_seconds + 0.25`, the
window may not exceed 2.5 seconds, `preserve_native_speed` must be true, and an
unused provider tail must be marked `DISCARD_UNAUTHORED_TAIL`. The same gate runs
in the prompt compiler and the concurrent episode supervisor, so a malformed
task cannot reach a paid provider submission or later assembly.

### Motivated combat-camera vocabulary

Combat prompts select camera language by dramatic function. They do not copy a
menu of moves into every prompt. The compiler accepts these technique IDs:

| Technique ID | Use |
| --- | --- |
| `tracking_follow` | Follow displacement, pursuit, or obstacle crossing. |
| `arc_orientation` | Read the fighters' positions with one bounded arc. |
| `crash_push` | Emphasize one decisive approach or contact. |
| `crash_pull` | Reveal the physical result after contact. |
| `low_angle_dolly` | Read footwork, takeoff, or grounded pressure. |
| `overhead_crane` | Read a group, route, enclosure, or terrain. |
| `micro_slow_follow` | Inspect one decisive contact for at most 0.6 seconds. |
| `impact_shake` | Add at most 0.35 seconds of shake at real contact. |
| `whip_pan_cut` | Match action direction across a storyboard cut. |
| `detail_triple_cut` | Show setup, contact, and result as three details. |
| `crane_rise` | Move from a result detail to the changed whole space. |
| `obstacle_pass` | Preserve continuity through a real door, post, crowd, or obstacle. |
| `shot_reverse_exchange` | Make an attack/counter exchange and eyeline axis explicit. |
| `bounded_rotation` | Read one exchange around a fixed contact anchor. |
| `locked_impact` | Let choreography and force play inside a stable composition. |

Every `combat_choreography_contract` must include a
`camera_language_plan`. Each segment binds exact time, action-beat index,
narrative motivation, subject anchor, and axis relation. Unplanned time is a
locked camera. Storyboards may use up to five motivated segments to assemble
short shots. A 15-second long take permits at most two dynamic camera segments,
with at least one second of stable observation between them. The declared
camera-plan mode must match the actual provider generation mode.
Edit-only techniques (`whip_pan_cut`, `detail_triple_cut`, and
`shot_reverse_exchange`) require storyboard generation. Slow motion without a
decisive contact, sustained shake, adjacent dynamic motion, decorative orbit,
and continuous push/pull/roam fail before paid submission.

### Causal combat-continuity ladders

Camera grammar alone does not guarantee that an exchange remains physically
legible. Every combat contract therefore includes one to three
`continuity_ladders`. A ladder binds ordered action-beat indexes, an entry and
exit state, persistent visible evidence, any required real-world measurement,
one final relational composition, and a camera resolution that must match an
already declared camera segment. Contact must leave a visible consequence;
damage, formation, props, distance, and recovery cannot reset between beats.

The licensed Scene 69, Scene 69B.20, Scene 69B.19, Scene 69B.18, Scene 69B.17,
Scene 69B.16, and Scene 69B.15 prompt/rule adapter exposes fifteen typed
methods:

- `causal_impact_aftermath_ladder`
- `occlusion_breach_threat_reveal`
- `timed_emotional_reaction_microsequence`
- `damage_accumulation_state_promotion`
- `reversible_crowd_geometry_ceremonial_entrance`
- `prop_geometric_anchor_momentum_recovery`
- `reciprocal_charge_convergence_ladder`
- `asymmetric_locked_clash_sustained_force`
- `defense_rhythm_failure_combo_ladder`
- `embodied_topology_traversal_damage_combo`
- `committed_miss_entrapment_counter_window`
- `force_conversion_controlled_recovery_ladder`
- `follow_through_exposure_penetration_extraction_ladder`
- `near_miss_armor_interception_recovery_ladder`
- `low_profile_evasion_limb_failure_counterlaunch_recovery_ladder`

Each method has its own required evidence vocabulary. Spatial methods require a
positive measurement in metres, centimetres, seconds, degrees, or body lengths;
damage promotion additionally requires a durable state ID. The final frame must
show the relevant identities, force direction, path, and environmental result
together. Missing evidence, unordered beat bindings, duplicate methods, invalid
measurements, and camera resolutions outside the motivated plan fail before a
paid submission. This is a licensed prompt/rule adapter, not trained Seedance
model weights.

`embodied_topology_traversal_damage_combo` handles a large opponent, creature,
vehicle, or structure as traversable terrain. It requires a load-bearing anchor,
ordered footholds or grip transitions, a continuous route, distinct contact
results, measured landing relation, and a shared closing frame containing the
topology and cumulative damage. Source prompts that demand perpetual handheld
motion, decorative whip moves, or slow motion are filtered out; camera movement
may reveal the route but cannot replace physical evidence.

`committed_miss_entrapment_counter_window` turns a missed committed strike into
a readable initiative transfer. It requires an irreversible attack line, a
measured evasion clearance, visible weapon contact and entrapment, a persistent
extraction delay, and a counterlaunch that starts only after the opening is
proved. The trapped state receives a durable state ID and must remain visible in
the final shared composition. Continuous shake, decorative whip moves, and
unmotivated slow motion are filtered from the source methodology.

`force_conversion_controlled_recovery_ladder` handles a defender who blocks a
heavier impact and converts its force into controlled displacement rather than
resetting between contact and landing. It requires defensive contact, readable
force transfer, measured displacement, deliberate body rotation, carried-prop
continuity, landing absorption, residual stance cost, and a final shared frame
showing the new distance. Decorative whip-pans, repeated lens-stomps, perpetual
handheld drift, and unmotivated slow motion are filtered out.

`follow_through_exposure_penetration_extraction_ladder` turns a committed
follow-through into a physically legible counteroffensive opening. It requires
the opponent's recovery state, a named exposed target zone, measured gap
closure, targeted penetration, an embedded interval that proves ownership and
reaction, a distinct extraction consequence, durable cumulative damage, and a
shared closing frame. Decorative whip-pans, repeated lens-stomps, perpetual
handheld drift, and unmotivated slow motion are filtered out.

`near_miss_armor_interception_recovery_ladder` preserves the difference between
a body evasion, a complete miss, and a glancing hit on a named protective layer.
It requires a measured last-moment clearance, visible armor contact, separate
protected-body and damaged-protection states, a persistent fragment or
deformation consequence, opposing attacker/defender recovery costs, and a
shared closing frame. The damaged protection receives a durable state ID.
Decorative whip-pans, impact zooms, perpetual handheld drift, unmotivated slow
motion, and invented glow cannot replace physical contact evidence.

`low_profile_evasion_limb_failure_counterlaunch_recovery_ladder` organizes a
low-profile evasion, targeted support-limb hit, visible load-bearing failure,
opponent counterlaunch, measured airborne displacement, and prop-preserving
landing as one causal exchange. The support-limb failure receives a durable
state ID; the closing frame must retain the wound, both recovery costs, the
carried prop, landing absorption, and any motivated witness-field reaction.
Ground tracking may establish clearance and a stable impact frame may resolve
the result, but repeated whip-pans, perpetual shake, decorative slow motion,
and impact zooms cannot replace readable body mechanics.

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
