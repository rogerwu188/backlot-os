# BacklotOS Story Agent

Version 0.4.0 is a portable, installable extraction of the local Claude Writer's
**script generation + script review** capabilities. Generic drama core. Review is fully deterministic (runs with
no model). Generation requires a model via the adapter layer.

## Install (any machine)
```bash
cd claude_story_agent
python -m pip install -e .            # core = stdlib only
python -m pip install -e ".[test]"    # + pytest
python -m pip install -e ".[anthropic]"  # only if using Anthropic backend
# Use .env.example as a field reference; inject values through your shell or secret store.
```

## Run (single-shot CLI)
```bash
echo '{}' | python -m claude_story_agent.cli health
python -m claude_story_agent.cli review --in episode.json
echo '{"spec":{"episode_id":"E01","target_duration_sec":150}}' | python -m claude_story_agent.cli generate --mode mock
python -m claude_story_agent.cli revise --in revise_req.json
```

## Run (NDJSON persistent server, >=4 workers)
```bash
python -m claude_story_agent.cli serve       # one JSON request per line -> one JSON reply per line
# {"verb":"reviewMany","episodes":[...]}  {"verb":"generateMany","specs":[...]}
```

## Verbs
`generate` · `review` · `revise` · `validate` · `health` · `status`/`progress` ·
`generateMany` · `reviewMany` · `importNovel` · `planSeries` ·
`continuityCheck` · `serve` (NDJSON).

## Backends (adapter layer)
`CLAUDE_STORY_MODE = anthropic | command | mock | auto`
- **anthropic** — Anthropic API (needs `ANTHROPIC_API_KEY` and an explicit `CLAUDE_STORY_ANTHROPIC_MODEL` in the environment/secret store; the code never logs or returns the key). The default policy requires Claude 4.8 or newer. If a gateway model ID does not encode its release, set `CLAUDE_STORY_MODEL_VERSION=4.8` or newer.
- **command** — external `CLAUDE_STORY_COMMAND`: reads `{"system","user"}` JSON on stdin, writes model text on stdout.
- **mock** — offline canned backend for tests.

No model available → `generate`/`revise` return **CAPABILITY_FAIL** with a non-zero CLI exit (never a fabricated script). Model JSON is structurally validated before it enters the pipeline.

## Default pacing contract

All new scripts use `backlotos.us-premium-streaming/1.1`: immediate dramatic
entry, high event density, compressed dialogue, no recap/filler, a meaningful
mid-episode escalation, and a consequential end hook. Deterministic review
reports opening/end hooks, advancing-shot ratio, dialogue density, repeated
dialogue, non-advancing shots, estimated audible-dialogue ratio, dialogue-only
runs, action-scene dialogue load, and picture/dialogue restatement. Requested
episode count never authorizes padding. `importNovel` accepts source text only
at runtime, returns source SHA plus chapter/beat metadata, and never persists or
bundles the text. `continuityCheck` can use a caller-owned append-only ledger.

## Safety
Never writes/returns API keys; never publishes; never deletes; all runs are non-destructive
(an optional append-only NDJSON ledger records output snapshots and SHA values for rollback). Set `BACKLOT_STORY_LEDGER` to a local path outside Git. Without it, the ledger is process-local only.

## Current semantic boundary

The deterministic reviewer checks declared canon character registration and forbidden depictions. It does not independently prove fidelity to an unseen source novel or infer relationship continuity from prose. Those capabilities require explicit source-fact/relationship evidence or a separate semantic model review and remain capability gaps in 0.1.1.
