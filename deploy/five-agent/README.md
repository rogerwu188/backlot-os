# Five-agent deployment

BacklotOS deploys five isolated agent services plus a non-agent workbench:

| Agent | Port | Responsibility | Current implementation |
|---|---:|---|---|
| producer-agent | 8801 | Supervising, orchestration, exception and budget decisions | Producer/Supervisor Agent 0.2.0; installed and selected by the official image |
| story-agent | 8802 | Source adaptation, script generation/review and failed-only revision | Story Agent 0.2.0 |
| pipeline-agent | 8803 | Storyboard and media generation, asset admission and credit receipts | Giggle image/video provider plus generic quality gates. Defaults: image `gpt2img`, video `seedance-2.0-pro`; live submission requires `GIGGLE_API_KEY`. |
| post-agent | 8804 | AgentCut timeline, subtitles, sound and render | AgentCut 0.9.17 |
| review-release-agent | 8805 | Multimodal review, regression and release preflight | Review Agent 1.1.0; platform publish remains human-only |

The workbench is a control plane on port 8787 and is not counted as an Agent.
All five services share only the project volume and communicate through
versioned JSON contracts. A missing adapter reports `ADAPTER_REQUIRED` or
`CAPABILITY_FAIL`; it never fabricates successful work.

```bash
cp .env.example .env
docker compose up --build -d
open http://127.0.0.1:8787
```

Two command adapters that satisfy this exact protocol -- one JSON request on
stdin, one JSON object on stdout, no shell -- now ship as an installable
package: `components/producer-supervisor-agent` (`pip install -e
components/producer-supervisor-agent`). The official Dockerfile installs them,
and Compose selects them by default:

- `BACKLOT_PRODUCER_COMMAND=backlotos-producer-command`
- `BACKLOT_PIPELINE_COMMAND=backlotos-pipeline-command`

The Producer command is locally accepted. The Pipeline command executes seven
deterministic semantic gates, while storyboard and media-generation provider
calls remain explicitly `ADAPTER_REQUIRED`; their absence cannot produce a
content PASS. Full Compose acceptance remains pending on a host with Docker.

The command is executed without a shell. Standard error is never returned to
the caller. Set `BACKLOT_AGENT_TOKEN` when the internal Agent ports are exposed
beyond a private container network.
