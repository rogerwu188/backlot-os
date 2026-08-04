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

For a task using `generation_schedule_mode=TAIL_CHAINED_SERIAL`, declare an
`action_sequence_contract.chain_id`, numeric `sequence_index`,
`depends_on_task`, and `predecessor_tail_frame_ref`. At submission time there
may be only one ready task for that chain. For every index after the first, the
predecessor tail file must already exist and must be the first
`reference_image_sequence` entry with role
`EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME`. A path that merely predicts a
future tail, a generic action still, or a simultaneously submitted successor
fails before provider spend.

Dynamic anchor counts describe temporal states, not every provider reference.
Identity, character, style, scene, and composition-only references remain
available to the model but do not inflate temporal interpolation counts. A
start plus a non-interpolable terminal target is two temporal anchors even when
additional identity and ownership-composition references are supplied.

Use `components/pipeline-tools/action_prompt_pipeline_cli.py` with the bundled
example manifest. It writes optimized prompt files, a compiled manifest, and a
single pre-submit report covering optimization, spatial feasibility, sequence
continuity, direction, and actor ownership.

## Camera discipline

Camera movement must reveal information or preserve an action relationship. Do
not stack `smooth_roam`, `slow_push`, overhead reveals, or equivalent movement
families across adjacent clips. Dialogue and evidence shots default to a stable
camera. Action shots default to normal real-time speed and one readable contact.

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
