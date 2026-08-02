#!/usr/bin/env python3
"""Independent file-native role worker. Shared disk is the only state/evidence source."""
import argparse,fcntl,hashlib,json,os,subprocess,tempfile,time
from pathlib import Path
ROLES=('producer','writer','pipeline','editor','audit'); OFFSETS={'producer':0,'writer':12,'pipeline':24,'editor':36,'audit':48}
DIRS=('inbox','running','outbox','receipts','deadletter','checkpoints','heartbeat','locks','pids','semantic_requests','semantic_results','artifacts')
PLACEHOLDERS={'','pending','todo','tbd','placeholder','待定','占位'}
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b):return hashlib.sha256(b).hexdigest()
def atomic(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);b=data if isinstance(data,bytes) else data.encode();fd,tmp=tempfile.mkstemp(prefix='.partial-',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p);d=os.open(p.parent,os.O_DIRECTORY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def init(root):
 root=Path(root)/'queue_v2.0.17'
 for r in ROLES:
  for d in DIRS:(root/r/d).mkdir(parents=True,exist_ok=True)
 return root
def probe(rr,role):
 p=rr/'receipts'/'local_tool_probe.json';tmp=rr/'receipts'/'.probe'
 try:
  atomic(tmp,b'probe');read_ok=tmp.read_bytes()==b'probe';tmp.unlink();x=subprocess.run(['/bin/sh','-c','printf probe'],capture_output=True,timeout=5);exec_ok=x.returncode==0 and x.stdout==b'probe'
  o={'schema':'qingshan.role.local_tool_probe.v1','role':role,'read':read_ok,'write':True,'exec':exec_ok,'status':'PASS' if read_ok and exec_ok else 'FAIL'}
 except Exception as e:o={'schema':'qingshan.role.local_tool_probe.v1','role':role,'status':'FAIL','error':str(e)}
 atomic(p,canon(o)+'\n');return o['status']=='PASS'
def heartbeat(rr,role,status,task=None,**extra):atomic(rr/'heartbeat'/'worker.json',canon({'role':role,'pid':os.getpid(),'status':status,'task_id':task,'updated_at':time.time(),**extra})+'\n')
def load(p):return json.loads(Path(p).read_text())
def checkpoint(rr,tid,o):o={**o,'schema':'qingshan.file_worker.checkpoint.v1','task_id':tid,'updated_at':time.time()};atomic(rr/'checkpoints'/(tid+'.json'),canon(o)+'\n');return o
def validate_task(t,role):
 if not {'task_id','role','phase','payload'}<=set(t) or t['role']!=role:raise ValueError('invalid task identity/role')
 if not isinstance(t['payload'],dict):raise ValueError('payload must be object')
 if 'draft' in t['payload']:raise ValueError('payload.draft is forbidden')
 for k in ('dispatch_id','accepted_run_id','recovery_fence'):
  if k in t and not isinstance(t[k],(str,int)):raise ValueError('invalid '+k)
 base={k:v for k,v in t.items() if k!='task_sha'}
 if t.get('task_sha') and t['task_sha']!=sha(canon(base).encode()):raise ValueError('task_sha mismatch')
def claim(rr):
 running=sorted((rr/'running').glob('*.json'))
 if running:return running[0],False
 for p in sorted((rr/'inbox').glob('*.json')):
  q=rr/'running'/p.name
  try:os.replace(p,q);return q,True
  except FileNotFoundError:pass
 return None,False
def blocked(rr,role,tid,reason):
 o={'schema':'qingshan.role_tool_channel_blocked.v1','role':role,'task_id':tid,'code':'ROLE_TOOL_CHANNEL_BLOCKED','reason':reason,'retry_after':time.time()+60}
 atomic(rr/'receipts'/(tid+'.ROLE_TOOL_CHANNEL_BLOCKED.json'),canon(o)+'\n');heartbeat(rr,role,'ROLE_TOOL_CHANNEL_BLOCKED',tid);return {'status':'ROLE_TOOL_CHANNEL_BLOCKED','task_id':tid}
def valid_result(o,item):
 if not isinstance(o,dict) or o.get('work_item_sha')!=item['work_item_sha']:return False
 if o.get('tool_result_status')!='complete' or not isinstance(o.get('semantic_result'),dict) or not o['semantic_result']:return False
 if not isinstance(o.get('evidence_links'),(list,dict)) or not o['evidence_links']:return False
 def bad(v):return isinstance(v,str) and v.strip().lower() in PLACEHOLDERS
 return not any(bad(v) for v in o['semantic_result'].values())
def tick(root,role,now=None,timeout=120):
 base=init(root);rr=base/role;lock=open(rr/'locks'/'worker.lock','a+')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:return {'status':'LOCKED'}
 try:
  atomic(rr/'pids'/'worker.pid',str(os.getpid())+'\n')
  if not probe(rr,role):heartbeat(rr,role,'LOCAL_TOOL_PROBE_FAILED');return {'status':'LOCAL_TOOL_PROBE_FAILED'}
  q,new=claim(rr)
  if not q:heartbeat(rr,role,'idle');return {'status':'NOOP'}
  t=load(q);validate_task(t,role);tid=t['task_id'];cp_path=rr/'checkpoints'/(tid+'.json');cp=load(cp_path) if cp_path.exists() else {}
  identity={k:t.get(k) for k in ('task_id','dispatch_id','accepted_run_id','recovery_fence')}
  if new:cp=checkpoint(rr,tid,{**identity,'state':'CLAIMED','claim_count':int(cp.get('claim_count',0))+1,'cursor':int(t.get('cursor',cp.get('cursor',0))), 'source_path':str(q)})
  req=rr/'semantic_requests'/(tid+'.json');res=rr/'semantic_results'/(tid+'.json')
  if not req.exists():
   item={'schema':'qingshan.file_native.semantic_request.v1','version':'2.0.17','role':role,'phase':t['phase'],'payload':t['payload'],'cursor':cp.get('cursor',0),'checkpoint':cp.get('checkpoint'),'identity':identity,'task_sha':t.get('task_sha'),'required':'one current role Agent semantic turn; write result atomically to semantic_results; no chat evidence'}
   item['work_item_sha']=sha(canon(item).encode());atomic(req,canon(item)+'\n');checkpoint(rr,tid,{**cp,'state':'WAITING_AGENT_RESULT','work_item_sha':item['work_item_sha'],'request_path':str(req)});heartbeat(rr,role,'WAITING_AGENT_RESULT',tid);return {'status':'WAITING_AGENT_RESULT','task_id':tid}
  item=load(req)
  if not res.exists():
   if time.time()-req.stat().st_mtime>=timeout:return blocked(rr,role,tid,'tool result missing or not durably returned')
   heartbeat(rr,role,'WAITING_AGENT_RESULT',tid);return {'status':'WAITING_AGENT_RESULT','task_id':tid}
  if not res.read_bytes().strip():return blocked(rr,role,tid,'empty tool result')
  out=load(res)
  if not valid_result(out,item):return blocked(rr,role,tid,'invalid or incomplete tool result envelope')
  current=load(cp_path)
  if current.get('work_item_sha')!=item['work_item_sha']:raise ValueError('checkpoint CAS mismatch')
  next_cursor=int(item['cursor'])+1
  art={'schema':'qingshan.file_native.artifact.v1','role':role,'identity':identity,'phase':t['phase'],'semantic_result':out['semantic_result'],'evidence_links':out['evidence_links'],'work_item_sha':item['work_item_sha'],'cursor':next_cursor}
  ap=rr/'artifacts'/(tid+'.json');atomic(ap,canon(art)+'\n');checkpoint(rr,tid,{**current,'state':'COMMITTED','cursor':next_cursor,'artifact_sha':sha(ap.read_bytes())})
  receipt={'schema':'qingshan.file_native.done.v1','role':role,'task_id':tid,'identity':identity,'artifact':str(ap),'artifact_sha':sha(ap.read_bytes()),'completed_at':time.time()};atomic(rr/'receipts'/(tid+'.done.json'),canon(receipt)+'\n');os.replace(q,rr/'outbox'/q.name);heartbeat(rr,role,'done',tid);return {'status':'DONE','task_id':tid}
 except Exception as e:
  tid=locals().get('tid',q.stem if q else 'unknown');atomic(rr/'deadletter'/(tid+'.json'),canon({'role':role,'task_id':tid,'error':str(e),'at':time.time()})+'\n');heartbeat(rr,role,'failed',tid,error=str(e));return {'status':'FAILED','task_id':tid,'error':str(e)}
 finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
def daemon(root,role):
 rr=init(root)/role;atomic(rr/'pids'/'worker.pid',str(os.getpid())+'\n');offset=OFFSETS[role]
 while True:
  now=time.time();delay=(offset-(int(now)%60))%60
  if delay:time.sleep(delay)
  tick(root,role);time.sleep(1)
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--role',choices=ROLES,required=True);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--once',action='store_true');g.add_argument('--daemon',action='store_true');a=p.parse_args();print(canon(tick(a.root,a.role))) if a.once else daemon(a.root,a.role)
if __name__=='__main__':main()
