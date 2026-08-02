import json,os,subprocess,sys,tempfile
from pathlib import Path

def run(*args,input_text=None):
    return subprocess.run(args,input=input_text,text=True,capture_output=True,check=False)

health=run(sys.executable,"-m","qingshan_review.cli","health")
assert health.returncode==0,health.stderr
payload=json.loads(health.stdout)
assert payload["status"]=="ready" and payload["workers"]>=4,payload
assert payload["ffmpeg"] and payload["ffprobe"],payload

ndjson=run(sys.executable,"-m","qingshan_review.cli","serve",input_text='{"id":"h","method":"health"}\n')
rows=[json.loads(x) for x in ndjson.stdout.splitlines() if x.strip()]
assert rows and rows[-1]["ok"] and rows[-1]["result"]["status"]=="ready",rows
print(json.dumps({"status":"PASS","version":payload["version"],"workers":payload["workers"],"interfaces":["CLI","NDJSON_AGENT"]},ensure_ascii=False))
