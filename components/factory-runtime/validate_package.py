#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
r=Path(__file__).resolve().parent;m=json.loads((r/'PUBLIC_INSTALL_MANIFEST.json').read_text());bad=[]
for rel,h in m['files'].items():
 p=r/rel
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h: bad.append(rel)
if bad: raise SystemExit('manifest mismatch: '+','.join(bad))
print(json.dumps({'status':'PASS','files':len(m['files']),'version':m['version']}))
