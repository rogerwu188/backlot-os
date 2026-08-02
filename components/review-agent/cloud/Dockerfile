FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QINGSHAN_WORKERS=4 \
    QINGSHAN_PRODUCTION_ROOT=/srv/qingshan \
    QINGSHAN_ISSUE_LEDGER=/state/issues.ndjson \
    QINGSHAN_RULE_REGISTRY=/state/anti_recurrence_rules.ndjson \
    QINGSHAN_OCR_PYTHON=/usr/local/bin/python

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/qingshan-review
COPY cloud/requirements-cloud.txt /tmp/requirements-cloud.txt
RUN pip install --no-cache-dir -r /tmp/requirements-cloud.txt
COPY . /opt/qingshan-review
RUN pip install --no-cache-dir --no-deps . && mkdir -p /srv/qingshan/tools /state /data /evidence
COPY cloud/runtime_tools/ /srv/qingshan/tools/

ENTRYPOINT ["qingshan-review"]
CMD ["serve"]
