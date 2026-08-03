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
seconds for native ambience alone. A rendered solo stem must measure at least
-35 dB mean and -18 dB peak, and the final mixed file must exist. Missing music
is a hard failure unless an explicit, evidence-backed creative exemption is
added by a future versioned policy.

## Release checklist

Run the BGM authenticity gate against the final project, solo stem, and mixed
master. Then run normal AgentCut full-cut review, cadence, subtitle, branded
outro, audio safety, and release validation. Platform publication remains a
separate irreversible action and is never implied by a passing media gate.
