#!/usr/bin/env python3
"""Create one SHA-bound Writer work item without advancing its cursor."""
import argparse, hashlib, json, os, tempfile, time
from pathlib import Path
MAX_EVIDENCE = 2

def canon(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha_file(p): return sha_bytes(Path(p).read_bytes())
def atomic_write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);b=data if isinstance(data,bytes) else data.encode()
 fd,tmp=tempfile.mkstemp(prefix='.tmp-',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p);d=os.open(p.parent,os.O_DIRECTORY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def load_json(p): return json.loads(Path(p).read_text())
def validate_task(t):
 req={'schema','task_id','role','phase','payload'}
 if not req<=set(t):raise ValueError('task missing required keys')
 if t['role']!='writer':raise ValueError('role mismatch')
 if t['phase']!='DRAFT_FULL_FACT':raise ValueError('semantic dispatcher only supports DRAFT_FULL_FACT')
 if 'draft' in t['payload']:raise ValueError('payload.draft is forbidden')
 expected=t.get('task_sha');base={k:v for k,v in t.items() if k!='task_sha'}
 if expected and expected!=sha_bytes(canon(base).encode()):raise ValueError('task_sha mismatch')
def claim_or_resume(rr):
 running=sorted((rr/'running').glob('*.json'))
 if running:return running[0],False
 for src in sorted((rr/'inbox').glob('*.json')):
  dst=rr/'running'/src.name
  try:os.replace(src,dst);return dst,True
  except FileNotFoundError:continue
 return None,False
def evidence_rows(payload):
 rows=payload.get('evidence',payload.get('chunks',[]))
 if not isinstance(rows,list):raise ValueError('payload evidence/chunks must be a list')
 out=[]
 for i,row in enumerate(rows):
  if isinstance(row,dict):
   content=row.get('content',row.get('text'))
   source_index=row.get('source_index',i)
  else:content=row;source_index=i
  if not isinstance(content,str) or not content.strip():raise ValueError('evidence content must be non-empty text')
  out.append({'source_index':source_index,'source_hash':sha_bytes(content.encode()),'content':content})
 return out
def checkpoint_sha(cp_path):
 return sha_file(cp_path) if cp_path.exists() else sha_bytes(b'')
def dispatch(root):
 rr=Path(root)/'queue_v2.0.17'/'writer'
 for d in ('inbox','running','checkpoints','artifacts','outbox'): (rr/d).mkdir(parents=True,exist_ok=True)
 task_path,claimed=claim_or_resume(rr)
 if not task_path:return {'status':'NOOP'}
 t=load_json(task_path);validate_task(t);tid=t['task_id'];cp_path=rr/'checkpoints'/f'{tid}.json'
 if claimed and not cp_path.exists():
  cp={'schema':'qingshan.semantic_writer.checkpoint.v1','task_id':tid,'official_phase':'DRAFT_FULL_FACT','internal_phase':'READ_CHUNK','resume_cursor':0,'claim_count':1,'partial_facts':[],'updated_at':time.time()}
  atomic_write(cp_path,canon(cp)+'\n')
 cp=load_json(cp_path);cursor=int(cp.get('resume_cursor',0));rows=evidence_rows(t['payload'])
 selected=rows[cursor:cursor+MAX_EVIDENCE]
 if not selected:return {'status':'NO_EVIDENCE','task_id':tid,'cursor':cursor}
 expected=checkpoint_sha(cp_path)
 facts=cp.get('partial_facts',[])
 summary=[]
 for fact in facts[-4:]:
  if isinstance(fact,dict):summary.append({k:fact.get(k) for k in ('n','title','summary','key_events','cliffhanger')})
 item={'schema':'qingshan.semantic_writer.work_item.v1','task_id':tid,'task_sha':t.get('task_sha'),'official_phase':'DRAFT_FULL_FACT','internal_substate':'SYNTHESIZE','cursor':cursor,'next_cursor':cursor+len(selected),'expected_checkpoint_sha':expected,'evidence':selected,'partial_facts_summary':summary,'required_output_keys':['n','title','summary','characters','locations','key_events','new_setups','payoffs','powers_items','time_weather','cliffhanger']}
 item['work_item_sha']=sha_bytes(canon(item).encode())
 out=rr/'outbox'/f'{tid}.work_item.json';atomic_write(out,canon(item)+'\n')
 # Deliberately no checkpoint write here: generation never advances cursor.
 return {'status':'WORK_ITEM_READY','task_id':tid,'path':str(out),'sha256':sha_file(out),'cursor':cursor}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);a=ap.parse_args();print(canon(dispatch(a.root)))
if __name__=='__main__':main()
