#!/usr/bin/env python3
"""Claim/resume one role task and emit one SHA-bound microstep work item; never completes semantics."""
import argparse,hashlib,json,os,tempfile,time
from pathlib import Path
ROLES=('producer','pipeline','editor','audit')
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b):return hashlib.sha256(b).hexdigest()
def atomic(p,s):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(prefix='.tmp-',dir=p.parent)
 with os.fdopen(fd,'w') as f:f.write(s);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def dispatch(root,role):
 rr=Path(root)/'queue_v2.0.17'/role
 for d in ('inbox','running','done','failed','checkpoints','heartbeat'): (rr/d).mkdir(parents=True,exist_ok=True)
 running=sorted((rr/'running').glob('*.json')); q=running[0] if running else None
 if not q:
  for x in sorted((rr/'inbox').glob('*.json')):
   try: q=rr/'running'/x.name;os.replace(x,q);break
   except FileNotFoundError:pass
 if not q:return {'status':'NOOP'}
 t=json.loads(q.read_text());base={k:v for k,v in t.items() if k!='task_sha'}
 if t.get('role')!=role or not {'task_id','dispatch_id','accepted_run_id','phase','payload'}<=set(t):raise ValueError('invalid identity/role')
 if t.get('task_sha') and t['task_sha']!=sha(canon(base).encode()):raise ValueError('task_sha mismatch')
 cp=rr/'checkpoints'/(t['task_id']+'.json');state=json.loads(cp.read_text()) if cp.exists() else {'checkpoint':None,'cursor':0,'claim_count':0}
 if not running:state['claim_count']=int(state.get('claim_count',0))+1
 item={'schema':'qingshan.semantic_role.work_item.v1','version':'2.0.17','role':role,'task_id':t['task_id'],'dispatch_id':t['dispatch_id'],'accepted_run_id':t['accepted_run_id'],'phase':t['phase'],'cursor':state.get('cursor',0),'checkpoint':state.get('checkpoint'),'task_sha':t.get('task_sha'),'payload':t['payload'],'required':'current isolated role model must execute exactly one semantic microstep','created_at':time.time()}
 item['work_item_sha']=sha(canon(item).encode());out=rr/'running'/(t['task_id']+'.work-item.json');atomic(out,canon(item)+'\n');return {'status':'WORK_ITEM_READY','path':str(out),'sha256':sha(out.read_bytes())}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--role',required=True,choices=ROLES);a=p.parse_args();print(canon(dispatch(a.root,a.role)))
