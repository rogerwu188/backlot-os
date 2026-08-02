"""Minimal example: Task2 launches AgentCut and submits concurrent jobs."""

import json
import subprocess
import sys


requests = [
    {"id": "health", "method": "health", "params": {}},
    {"id": "qa-a", "method": "validate", "params": {"project": "/data/a.json", "strictMedia": True}},
    {"id": "job-a", "method": "render", "params": {"project": "/data/a.json", "overwrite": True, "progress": True}},
]

process = subprocess.Popen(
    [sys.executable, "-m", "agentcut", "agent", "--workers", "3"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    bufsize=1,
)
assert process.stdin is not None and process.stdout is not None

for request in requests:
    process.stdin.write(json.dumps(request) + "\n")
process.stdin.flush()

# Responses and progress events can arrive in any order; correlate them by id.
responses = {}
while len(responses) < len(requests):
    response = json.loads(process.stdout.readline())
    if response.get("event") == "progress":
        print("progress", response, file=sys.stderr)
        continue
    responses[response["id"]] = response

process.terminate()
print(json.dumps(responses, ensure_ascii=False, indent=2))
