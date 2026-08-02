#!/usr/bin/env python3
import argparse, hashlib, json, os, tempfile, time
from pathlib import Path
ROLES=("producer","writer","pipeline","editor","audit")
DIRS=("inbox","running","done","failed","checkpoints","heartbeat")
OFFICIAL_WRITER_PHASES=("READ_EVIDENCE","MERGE_EVIDENCE","DRAFT_FULL_FACT","VALIDATE","APPEND_ATOMIC","NEXT_CHAPTER")
DRAFT_INTERNAL=("READ_CHUNK","SYNTHESIZE","COMMIT")
DRAFT_KEYS=("n","title","summary","characters","locations","key_events","new_setups","payoffs","powers_items","time_weather","cliffhanger")
def canon(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p): return sha_bytes(Path(p).read_bytes())
def atomic_write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True); b=data if isinstance(data,bytes) else data.encode()
 fd,tmp=tempfile.mkstemp(prefix='.tmp-',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as f: f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp): os.unlink(tmp)
def init_runtime(root):
 root=Path(root)
 for r in ROLES:
  for d in DIRS: (root/'queue_v2.0.17'/r/d).mkdir(parents=True,exist_ok=True)
 return root
def heartbeat(role,rr,status,task_id=None):
 atomic_write(rr/'heartbeat'/'worker.json',canon({'schema':'qingshan.minimal_worker.heartbeat.v1','role':role,'status':status,'task_id':task_id,'updated_at':time.time()})+'\n')
def checkpoint(rr,tid,obj):
 obj=dict(obj);obj.update(schema='qingshan.minimal_worker.checkpoint.v1',task_id=tid,updated_at=time.time())
 atomic_write(rr/'checkpoints'/f'{tid}.json',canon(obj)+'\n');return obj
def artifact(rr,tid,obj):
 p=rr/'artifacts'/f'{tid}.json';atomic_write(p,canon(obj)+'\n')
 return {'path':str(p),'sha256':sha_file(p),'bytes':p.stat().st_size}
def load_task(p,role):
 o=json.loads(p.read_text()); req={'schema','task_id','role','phase','payload'}
 if not req<=set(o): raise ValueError('task missing required keys')
 if o['role']!=role: raise ValueError('role mismatch')
 expected=o.get('task_sha'); base={k:v for k,v in o.items() if k!='task_sha'}
 if expected and expected!=sha_bytes(canon(base).encode()): raise ValueError('task_sha mismatch')
 return o
def claim_one(rr):
 for p in sorted((rr/'inbox').glob('*.json')):
  q=rr/'running'/p.name
  try: os.replace(p,q);return q
  except FileNotFoundError: continue
 return None
def valid_draft(row,n):
 return set(row.keys())==set(DRAFT_KEYS) and len(row)==len(DRAFT_KEYS) and row['n']==n and all(isinstance(row[k],list) for k in DRAFT_KEYS[3:9]) and all(isinstance(row[k],str) and row[k] for k in ('title','summary','time_weather','cliffhanger'))
def writer_step(rr,t,cp):
 tid=t['task_id']; phase=t['phase']; p=t['payload']; n=int(p.get('n',1))
 if phase not in OFFICIAL_WRITER_PHASES: raise ValueError('writer official phase changed')
 if phase!='DRAFT_FULL_FACT':
  a=artifact(rr,tid,{'role':'writer','official_phase':phase,'result':p.get('result',{}),'status':'phase_complete'})
  checkpoint(rr,tid,{'official_phase':phase,'state':'artifact_ready','artifact':a});return True,a
 internal=cp.get('internal_phase','READ_CHUNK'); cursor=int(cp.get('resume_cursor',0)); claimed=int(cp.get('claim_count',1))
 chunks=p.get('chunks',[]); batch=max(1,min(int(p.get('batch_size',2)),4))
 if internal=='READ_CHUNK':
  nxt=min(cursor+batch,len(chunks)); checkpoint(rr,tid,{'official_phase':phase,'internal_phase':'SYNTHESIZE' if nxt==len(chunks) else 'READ_CHUNK','resume_cursor':nxt,'claim_count':claimed,'chunk_count':len(chunks)});return False,None
 if internal=='SYNTHESIZE':
  raise ValueError('isolated Writer LLM turn required: run dispatcher.py, generate the 11-key increment from its work_item, then run commit_step.py')
 if internal=='COMMIT':
  raise ValueError('COMMIT is handled only by commit_step.py with work_item-bound evidence and checkpoint CAS')
 raise ValueError('invalid internal phase')
def generic_step(role,rr,t,cp):
 a=artifact(rr,t['task_id'],{'schema':f'qingshan.{role}.output.v1','role':role,'phase':t['phase'],'input_sha':t.get('task_sha'),'output':t['payload'].get('output',{})})
 checkpoint(rr,t['task_id'],{'phase':t['phase'],'step':int(cp.get('step',0))+1,'state':'artifact_ready','artifact':a});return True,a
def tick(root,role):
 if role not in ROLES: raise ValueError('unknown role')
 rr=init_runtime(root)/'queue_v2.0.17'/role; running=sorted((rr/'running').glob('*.json')); claimed=False
 q=running[0] if running else claim_one(rr)
 if not q: heartbeat(role,rr,'idle');return {'status':'HEARTBEAT_ONLY'}
 claimed=not bool(running); tid=q.stem; cp={}
 try:
  t=load_task(q,role);tid=t['task_id'];cp_path=rr/'checkpoints'/f'{tid}.json';cp=json.loads(cp_path.read_text()) if cp_path.exists() else {}
  if claimed: cp=checkpoint(rr,tid,{'state':'running','claim_count':int(cp.get('claim_count',0))+1,'resume_cursor':int(cp.get('resume_cursor',0))})
  done,a=(writer_step(rr,t,cp) if role=='writer' else generic_step(role,rr,t,cp))
  if done:
   if not a or not Path(a['path']).exists() or sha_file(a['path'])!=a['sha256']: raise ValueError('artifact missing before done')
   receipt={'schema':'qingshan.minimal_worker.done.v1','task_id':tid,'role':role,'artifact':a,'completed_at':time.time()}
   atomic_write(rr/'done'/q.name,canon(receipt)+'\n');q.unlink();heartbeat(role,rr,'done',tid);return {'status':'DONE','task_id':tid}
  heartbeat(role,rr,'checkpointed',tid);return {'status':'CHECKPOINTED','task_id':tid}
 except Exception as e:
  error=str(e); failed_cp=checkpoint(rr,tid,{**cp,'state':'failed','error':error})
  receipt={'schema':'qingshan.minimal_worker.failed.v1','task_id':tid,'role':role,'error':error,'checkpoint_sha':sha_file(rr/'checkpoints'/f'{tid}.json'),'failed_at':time.time()}
  failed_path=rr/'failed'/q.name;atomic_write(failed_path,canon(receipt)+'\n');q.unlink(missing_ok=True)
  if not failed_path.exists() or json.loads(failed_path.read_text()).get('error')!=error: raise RuntimeError('failed quarantine receipt not durable')
  heartbeat(role,rr,'failed',tid);return {'status':'FAILED','task_id':tid,'error':error}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--role',required=True,choices=ROLES);ap.add_argument('--once',action='store_true',required=True);a=ap.parse_args();tick(a.root,a.role)
if __name__=='__main__': main()
