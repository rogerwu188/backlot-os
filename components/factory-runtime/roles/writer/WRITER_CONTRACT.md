# Writer contract
The official six phases remain exactly: `READ_EVIDENCE -> MERGE_EVIDENCE -> DRAFT_FULL_FACT -> VALIDATE -> APPEND_ATOMIC -> NEXT_CHAPTER`.
Only `DRAFT_FULL_FACT` uses internal `READ_CHUNK -> SYNTHESIZE -> COMMIT` substates. These are not official phases.

Each isolated Writer LLM turn follows `dispatcher.py -> current Writer model synthesis -> commit_step.py`. Dispatcher claims/resumes the same task and emits at most two evidence segments with source indices/hashes, expected checkpoint SHA, and partial-facts summary; it never advances the cursor. The model emits the 11-key increment plus work-item-bound `evidence_links`. Commit rejects empty/PENDING/placeholders, stale SHA, or absent/foreign evidence, and atomically appends `partial_facts` and advances cursor only after CAS. `payload.draft` is forbidden.
