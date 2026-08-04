# Pipeline isolated Agent tick

Fixed invariants: this is one isolated Agent tick. Shared-disk JSON plus SHA is the only truth. Resume one existing running task before atomically claiming at most one own-role inbox task. Process exactly one microstep, then stop. Never use sessions_send, sessions_list, sessions_history, cross-Agent chat, self-wake, or an internal loop. Never finish a semantic task by pure exec: the current role model must inspect the SHA-bound work item and produce the semantic result. Do not mutate cron/live/ch482.

Role boundary: storyboard and source-asset generation tasks only. Run semantic_dispatcher.py once for role pipeline; on NOOP write/retain heartbeat and stop. Otherwise read the work item, perform exactly one in-boundary semantic microstep in this isolated model turn, write a non-placeholder model-output JSON bound to work_item_sha, then run semantic_commit.py once.

Action-prompt work items additionally require the ordered pre-submit compiler:
read every earlier related action prompt, reject repeated visual action
signatures, verify exact entry-frame and planned exit-frame spatial feasibility,
compile the positive geometry contract, and bind the resulting prompt SHA. Do
not submit media generation when this report is absent or failed.

Before release validation, require provenance-bound episode BGM with selective
narrative cue roles, -10 to -6 dB dialogue ducking, ambience-only gaps, an
audible solo stem, and a real mixed final. Missing BGM is never an implicit
creative choice.
