#!/usr/bin/env python3
"""Validate one real Writer model increment and atomically CAS-commit it."""
import argparse,hashlib,json,os,tempfile,time
from pathlib import Path
KEYS=('n','title','summary','characters','locations','key_events','new_setups','payoffs','powers_items','time_weather','cliffhanger')
PLACEHOLDERS={'pending','todo','tbd','n/a','na','none','null','placeholder','待定','占位','稍后补充','未完成'}
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def sha_file(p):return sha_bytes(Path(p).read_bytes())
def atomic_write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);b=data if isinstance(data,bytes) else data.encode();fd,tmp=tempfile.mkstemp(prefix='.tmp-',dir=p.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p);d=os.open(p.parent,os.O_DIRECTORY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def load(p):
 p=Path(p)
 if not p.is_file() or not p.read_bytes().strip():raise ValueError('non-empty model output required')
 try:return json.loads(p.read_text())
 except json.JSONDecodeError as e:raise ValueError('valid JSON model output required') from e
def placeholder(v):return isinstance(v,str) and v.strip().lower() in PLACEHOLDERS
def nonempty(v):
 if v is None:return False
 if isinstance(v,str):return bool(v.strip()) and not placeholder(v)
 if isinstance(v,list):return bool(v) and all(nonempty(x) for x in v)
 if isinstance(v,dict):return bool(v) and all(nonempty(x) for x in v.values())
 return True
def validate_output(o,item):
 if not isinstance(o,dict):raise ValueError('model output must be an object')
 if set(o)!=(set(KEYS)|{'evidence_links','model_output_provenance'}):raise ValueError('model output must contain exactly 11 keys plus evidence_links and model_output_provenance')
 if o['model_output_provenance']!='current_writer_agent':raise ValueError('current Writer Agent model output required')
 if not all(nonempty(o[k]) for k in KEYS):raise ValueError('empty, PENDING, or placeholder output rejected')
 if not isinstance(o['n'],int):raise ValueError('n must be integer')
 for k in KEYS[3:9]:
  if not isinstance(o[k],list) or not o[k]:raise ValueError(f'{k} must be a non-empty list')
 links=o['evidence_links']
 if not isinstance(links,dict) or set(links)!=set(KEYS):raise ValueError('each of 11 keys must have evidence_links')
 allowed={(str(e['source_index']),e['source_hash']):e['content'] for e in item['evidence']}
 for key in KEYS:
  if not isinstance(links[key],list) or not links[key]:raise ValueError(f'evidence_links missing for {key}')
  for link in links[key]:
   if not isinstance(link,dict) or set(link)!={'source_index','source_hash','evidence_excerpt'}:raise ValueError('invalid evidence link shape')
   pair=(str(link['source_index']),link['source_hash']);excerpt=link['evidence_excerpt']
   if pair not in allowed:raise ValueError('evidence link outside current work_item')
   if not isinstance(excerpt,str) or not excerpt.strip() or excerpt not in allowed[pair]:raise ValueError('evidence excerpt not present in cited source')
def commit(root,work_item_path,model_output_path):
 rr=Path(root)/'queue_v2.0.17'/'writer';item=load(work_item_path)
 if item.get('schema')!='qingshan.semantic_writer.work_item.v1':raise ValueError('invalid work_item schema')
 base={k:v for k,v in item.items() if k!='work_item_sha'}
 if item.get('work_item_sha')!=sha_bytes(canon(base).encode()):raise ValueError('work_item SHA mismatch')
 tid=item['task_id'];cp_path=rr/'checkpoints'/f'{tid}.json'
 if not cp_path.exists() or sha_file(cp_path)!=item['expected_checkpoint_sha']:raise ValueError('stale checkpoint SHA; CAS rejected')
 cp=load(cp_path)
 if int(cp.get('resume_cursor',-1))!=int(item['cursor']):raise ValueError('cursor mismatch; CAS rejected')
 output=load(model_output_path);validate_output(output,item)
 fact={k:output[k] for k in KEYS};fact['evidence_links']=output['evidence_links'];fact['model_output_provenance']=output['model_output_provenance'];fact['work_item_sha']=item['work_item_sha']
 facts=cp.get('partial_facts',[])
 if not isinstance(facts,list):raise ValueError('partial_facts must be a list')
 new_cp=dict(cp);new_cp.update(internal_phase='READ_CHUNK',resume_cursor=int(item['next_cursor']),partial_facts=facts+[fact],updated_at=time.time())
 if sha_file(cp_path)!=item['expected_checkpoint_sha']:raise ValueError('checkpoint changed before commit; CAS rejected')
 atomic_write(cp_path,canon(new_cp)+'\n');committed=rr/'artifacts'/f'{tid}.partial_facts.json';atomic_write(committed,canon(new_cp['partial_facts'])+'\n')
 return {'status':'COMMITTED','task_id':tid,'resume_cursor':new_cp['resume_cursor'],'checkpoint_sha':sha_file(cp_path),'partial_facts_sha':sha_file(committed)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--work-item',required=True);ap.add_argument('--model-output',required=True);a=ap.parse_args();print(canon(commit(a.root,a.work_item,a.model_output)))
if __name__=='__main__':main()
