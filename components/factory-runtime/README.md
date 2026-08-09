# Queue 2.0.20 file-native workers with a fixed authorization root

Candidate-only five-role shared-disk queue package. Each 60-second isolated role tick resumes/claims one own task and performs one semantic microstep; JSON+SHA is the sole transport and truth. Offsets: producer 0, writer 12, pipeline 24, editor 36, audit 48. Installation creates `queue_v2.0.17/{role}/{inbox,running,done,failed,checkpoints,heartbeat}`.

Real owner authorization is accepted only from the installer-owned StoryClaw directory `/home/storyclaw/.openclaw/shared/ai-drama-factory/factory/owner_authorizations`. The caller and process environment cannot select or override this trust root. The validator canonicalizes the path before reading it and rejects files outside that directory, traversal aliases, and symlinks. Test authorizations remain confined to the packaged fixtures directory.

All cron templates are disabled and activation remains forbidden pending independent audit. No live/ch482/cron mutation is performed by this package.

## Portable production-line wakeup

`portable_wakeup.py` embeds the wake contract in the factory runtime instead of
depending on one chat product. It can run as a long-lived `--daemon`, or a host
may call `--once` from its own scheduler. Both modes share the same durable
time-slot run key, fencing token, intent-before-execution receipt and lock, so a
second platform trigger in the same slot is a no-op.

The configured command is an orchestration/checkpoint entrypoint only. The
config must explicitly forbid provider submission and browser/platform actions;
paid work still requires its separate durable transaction, exact task binding,
price/cap gate and authoritative reconciliation. Copy
`portable_wakeup.example.json`, use one shared state directory, and supervise
the daemon with the target platform's normal process manager. The runtime does
not modify cron, systemd or Kubernetes resources itself.
