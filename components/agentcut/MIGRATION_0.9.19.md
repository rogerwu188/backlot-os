# AgentCut 0.9.19 Migration

AgentCut 0.9.19 adds a fail-closed replacement-binding contract. Existing
projects are unchanged until `metadata.replacementBindingPolicy.enabled` is set.

For every repair batch:

1. Record every timeline clip that must receive a repaired asset.
2. Bind the admitted replacement file SHA to that exact clip ID.
3. Record superseded file SHAs and recognizable legacy path tokens.
4. Run validation before compile and again before release.
5. Treat any residual clip as an assembly failure, not a QA exception.

The gate recalculates source hashes from disk. Renaming a stale file or editing
`metadata.source_sha256` cannot bypass it. Coverage is reported at
`coverage.replacementBindings`; `residualClips` identifies every unresolved
timeline binding.
