# Architecture

BacklotOS separates creative agents from deterministic production gates.

```text
Story / canon
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

