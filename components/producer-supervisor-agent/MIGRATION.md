# Migration -- wiring backlotos-producer-supervisor-agent into a live deployment

## 1. Install

```bash
pip install -e components/producer-supervisor-agent
```

This registers three console scripts: `backlotos-producer-command`,
`backlotos-pipeline-command`, `backlotos-producer-agent`.

## 2. Point the launcher's external-command adapters at them

In `deploy/five-agent/.env` (or wherever `agent_host.py` reads its
environment):

```bash
BACKLOT_PRODUCER_COMMAND=backlotos-producer-command
BACKLOT_PIPELINE_COMMAND=backlotos-pipeline-command
```

`agent_host.RoleDispatcher.health()` will now report
`"semantic_adapter": "SUPPORTED"` for role `producer` and `pipeline` once the
command resolves on `PATH` inside the container/host running that role.
The official installer and Dockerfile now install version 0.1.1. Compose sets
both adapter commands by default. A custom deployment must still install the
package and set the two variables explicitly.

## 3. Configure downstream agent reachability (optional but needed for real dispatch)

`dispatch`/`dispatchMany` need to actually reach the `story`/`pipeline`/`post`/
`review` agents. Configure one backend per agent in `.env` (see
`.env.example`): either a local `BACKLOT_AGENT_<NAME>_COMMAND` (argv, no
shell, JSON stdin/stdout) or an HTTP `BACKLOT_AGENT_<NAME>_URL` pointing at
that agent's `/v1/task` endpoint in the docker-compose network. Without
either, dispatch honestly returns `BLOCKED`/`CAPABILITY_FAIL` -- it never
fabricates a completed job.

## 4. Running standalone (outside the launcher)

```bash
backlotos-producer-agent serve-http --host 0.0.0.0 --port 8801
```

exposes the same `GET /health` / `POST /v1/task` wire shape as
`agent_host.RoleServer`, so it can be dropped into the `producer` service slot
in `deploy/five-agent/docker-compose.yml` directly instead of proxying
through `agent_host.py`, if a future deployment prefers that. This is not
required for the current `BACKLOT_PRODUCER_COMMAND` integration path and has
not been run against the live docker-compose stack in this delivery.

## 5. Not migrated / not applicable

- No prior "original Claude producer/supervisor" executable existed anywhere
  in the source tree to migrate FROM (see `AUDIT.md` section A) -- this is a
  new implementation built to the documented contract in
  `docs/CLAUDE_PRODUCER_PACKAGE_REQUEST.md` and `agent_host.py`.
- Episode-specific pipeline-tools scripts (`build_e*.py`, `audit_e*.py`,
  `finalize_e*.py`, ...) were deliberately NOT touched, imported, or migrated.
