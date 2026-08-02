# Source inventory

| BacklotOS component | Imported source | Version | Import policy |
|---|---|---:|---|
| `components/review-agent` | qingshan-ai-review-agent | 1.1.0 | Source, schemas, tests, cloud adapters, migration notes; no outputs or packages |
| `components/story-agent` | Claude Writer portable handoff + BacklotOS hardening | 0.1.1 | Generic prompts, adapters, schemas, tests; no keys, sessions, or project prose |
| `components/agentcut` | AgentCut | 0.9.17 | Source, schemas, tests, examples; no vendor binaries, media, builds, or releases |
| `components/factory-runtime` | cloud factory release candidate | 2.0.20 | Portable file-native runtime and tests only |
| `components/pipeline-tools` | production `tools` | source snapshot | Python/shell/docs only; no caches or evidence |
| `components/agent-factory` | agent factory templates | source snapshot | Persona and operating templates |
| `legacy/qingshan-agent-prompts` | original cloud prompt files | compatibility snapshot | Migration reference; not product branding |

The original production root is deliberately not mirrored. It is approximately 31 GiB and contains media, evidence, environments, and project-private state.
