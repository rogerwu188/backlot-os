# Writer isolated semantic tick instruction

This is one **isolated LLM turn**, not a Python-only worker completion. Preserve the official six phases exactly:
`READ_EVIDENCE -> MERGE_EVIDENCE -> DRAFT_FULL_FACT -> VALIDATE -> APPEND_ATOMIC -> NEXT_CHAPTER`.
`READ_CHUNK`, `SYNTHESIZE`, and `COMMIT` are internal substates only.

For a `DRAFT_FULL_FACT` tick:
1. Run `dispatcher.py --root <runtime>` once. It atomically claims or resumes the same task and emits at most two evidence segments in a SHA-bound `work_item`; generation does **not** advance the cursor.
2. The current Writer model must read that `work_item` and semantically produce one JSON increment with exactly the 11 ordered keys `n,title,summary,characters,locations,key_events,new_setups,payoffs,powers_items,time_weather,cliffhanger`, plus `model_output_provenance="current_writer_agent"` and an `evidence_links` object with one non-empty citation list for each of the 11 keys. Every citation must contain source_index, source_hash, and an exact non-empty evidence_excerpt from the current work item. No empty, `PENDING`, TODO, placeholder, or guessed evidence values.
3. Save the model output JSON, then run `commit_step.py --root <runtime> --work-item <path> --model-output <path>` once. It validates semantics/evidence and advances `partial_facts`/cursor only if checkpoint CAS still matches.

Do not end the isolated turn after merely execing Python or after dispatch. The Writer model synthesis in step 2 is mandatory. Do not use `payload.draft`, sessions/chat, self-wake, cron mutation, or alter official phases.
