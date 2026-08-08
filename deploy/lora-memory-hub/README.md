# LoRA Memory Hub

This is the only BacklotOS service that needs GitHub write permission. Production
nodes send privacy-filtered JSONL samples to its authenticated HTTP endpoint. The
hub stores content-addressed objects in a shared private S3 bucket, periodically
merges and validates them, and pushes the deterministic corpus to GitHub.

## Deploy

1. Create a private S3 bucket and grant this service `ListBucket`, `GetObject`,
   `PutObject`, and `DeleteObject` only for the configured prefix.
   For an S3-compatible provider, set `BACKLOTOS_LORA_S3_ENDPOINT` to its HTTPS
   API endpoint. Keep the LoRA prefix separate from production relay prefixes.
2. Create a fine-grained GitHub token for the hub with Contents read/write on
   the BacklotOS repository. Do not distribute it to production nodes.
3. Copy `.env.example` to `.env`, replace every placeholder, and keep `.env`
   outside source control.
4. Start one convergence replica:

   ```bash
   docker compose up -d --build
   curl http://127.0.0.1:8080/health
   ```

Put TLS and normal access controls in front of port 8080 before exposing the
collector to remote nodes. The S3 bucket is shared infrastructure, not anonymous
public storage. Nodes need only the collector URL and collector upload token.

## Configure a production node

Install with the collector URL and provide the upload token at runtime:

```bash
BACKLOTOS_LORA_COLLECTOR_URL=https://memory.example.com ./scripts/install.sh
export BACKLOTOS_LORA_COLLECTOR_TOKEN='node-upload-token'
```

Accepted samples queue locally while the service is unavailable and retry before
later Seedance prompt compilation. A node never clones or pushes the GitHub
repository in the default `collector` mode. `BACKLOTOS_LORA_SYNC_MODE=direct-git`
exists only as an explicit development override.

## Credential boundary

| Credential | Production node | Memory hub |
| --- | --- | --- |
| Collector upload token | Yes | Yes |
| AWS/S3 credential or role | No | Yes |
| GitHub write credential | No | Yes |

Run exactly one convergence replica per GitHub checkout. HTTP ingestion remains
threaded, and duplicate uploads are idempotent because S3 keys use the canonical
dataset SHA-256.
