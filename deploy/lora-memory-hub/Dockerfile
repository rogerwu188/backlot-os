FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir boto3

WORKDIR /app
COPY components/pipeline-tools/local_lora_memory_sync.py /app/local_lora_memory_sync.py
COPY components/pipeline-tools/lora_memory_hub.py /app/lora_memory_hub.py
COPY deploy/lora-memory-hub/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
