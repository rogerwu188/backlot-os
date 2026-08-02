# Conflict-safe semantic canary migration

All candidate cron templates remain disabled by default. Never create a duplicate cron for a role: upgrade only the fixed `cron_id` in place. Canary roles sequentially. Writer first: only after the 2.0.16 Writer semantic canary PASS, keep legacy `01f96e1c` disabled and enable the same fixed Writer cron binding in place; do not enable a second Writer job. Then apply the identical one-role-at-a-time canary rule to producer, pipeline, editor, and audit. On failure, leave that role disabled and preserve its running task identity/checkpoint/cursor. Activation is forbidden in this build package.

## 2.0.20 authorization provenance gate

Live activation always reads authorization from `/home/storyclaw/.openclaw/shared/ai-drama-factory/factory/owner_authorizations`. No command-line argument or environment variable can move this trust root. The authorization file must resolve beneath that directory without traversal or symlinks. Files materialized from chat, temporary directories, or any unapproved local path are rejected before activation-plan creation.
