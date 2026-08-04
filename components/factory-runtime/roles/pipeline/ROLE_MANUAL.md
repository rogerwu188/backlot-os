# Pipeline worker manual

Run exactly one bounded tick: `python3 worker.py --root <runtime> --once`. The worker communicates only through shared files, ignores stdout, atomically claims at most one task, resumes `running` before considering a new claim, writes checkpoint/artifact before terminal state, and emits heartbeat when idle. Public cron registration is outside this package and requires explicit operator action.

For every action sequence, compile prompts with `action_prompt_pipeline_cli.py`
before any provider submission. Each task must read all earlier related action
tasks, carry one distinct action signature, declare exact entry/exit states, and
pass entry/exit spatial feasibility. The optimized prompt SHA and optimizer
receipt are part of the submission authority. A failed gate triggers prompt or
predecessor-tail redesign; it never authorizes an unchanged paid retry.

For release episodes, run `bgm_authenticity_gate.py` before final review. A
missing BGM contract, missing `Audio.BGM` clips, inaudible stem, unverified
source, wall-to-wall score, absent ambience-only window, or dialogue masking is
a blocking failure.
