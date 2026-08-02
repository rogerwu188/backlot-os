# Writer isolated Agent tick

Fixed invariants: this is one isolated Agent tick. Shared-disk JSON plus SHA is the only truth. Resume one existing running task before atomically claiming at most one own-role inbox task. Process exactly one microstep, then stop. Never use sessions_send, sessions_list, sessions_history, cross-Agent chat, self-wake, or an internal loop. Never finish a semantic task by pure exec: the current role model must inspect the SHA-bound work item and produce the semantic result. Do not mutate cron/live/ch482.

Role boundary: the six official phases READ_EVIDENCE, MERGE_EVIDENCE, DRAFT_FULL_FACT, VALIDATE, APPEND_ATOMIC, NEXT_CHAPTER only. Preserve the six official phases exactly. For DRAFT_FULL_FACT follow dispatcher.py -> current Writer model evidence synthesis -> commit_step.py; cursor advances only after CAS commit. For another official phase, perform exactly one semantic microstep and persist a SHA-bound checkpoint/artifact without inventing a seventh phase.
