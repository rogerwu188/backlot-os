# Architecture

BacklotOS separates creative agents from deterministic production gates.

```text
Novel URL / ebook → One-click Launcher → source SHA + episode plan
      ↓
Writer Agent → Storyboard / shot planner → Media generation
      ↓                    ↓                       ↓
Shared contracts and exact-SHA provenance
      ↓
AgentCut timeline → Review Agent → repair tasks → human approval
      ↓
Release preflight (never automatic publishing)
```

The Factory Runtime transports append-only commands and receipts between agents. AgentCut materializes a timeline. The Review Agent reconciles decoded media evidence with the timeline and returns scored, stable issues. Repair tasks are recommendations with rollback metadata; they do not grant platform mutation authority.

The initial import retains legacy filenames where production compatibility depends on them. New product-level contracts should use `backlotos.*` namespaces and provide adapters for older `qingshan.*` contracts.

The Launcher owns product intake and creates a resumable project directory. It
does not synthesize a script when a model backend is missing. It also keeps
requested episode count separate from source density: low-density plans receive
a visible warning and never authorize padded scenes or empty shots.

## Deployment topology

```text
Workbench (control plane, not an Agent)
    ├── Producer / Supervisor Agent
    ├── Story Creation + Review Agent
    ├── Storyboard + Media Pipeline Agent
    ├── AgentCut Post-production Agent
    └── Review + Release-preflight Agent
```

Each Agent is independently deployable, has a dedicated HTTP `/health` and
`/v1/task` surface, and shares only versioned project artifacts. A service may
be restarted without merging its state with another Agent. Missing semantic
adapters fail closed as `ADAPTER_REQUIRED`/`CAPABILITY_FAIL`.
