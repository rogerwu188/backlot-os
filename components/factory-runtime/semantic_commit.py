#!/usr/bin/env python3
"""Commit one model-produced microstep with identity/SHA binding; no semantic generation here."""
import argparse,hashlib,json,os,tempfile,time
from pathlib import Path
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(b):return hashlib.sha256(b).hexdigest()
def atomic(p,s):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(prefix='.tmp-',dir=p.parent)
 with os.fdopen(fd,'w') as f:f.write(s);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def main(root,item_path,output_path):
 i=json.loads(Path(item_path).read_text());o=json.loads(Path(output_path).read_text());base={k:v for k,v in i.items() if k!='work_item_sha'}
 if i.get('work_item_sha')!=sha(canon(base).encode()):raise ValueError('work item SHA mismatch')
 if not isinstance(o,dict) or not isinstance(o.get('semantic_result'),dict) or not o['semantic_result'] or o.get('work_item_sha')!=i['work_item_sha']:raise ValueError('non-empty model semantic_result and binding required')
 if o.get('model_output_provenance')!='current_role_agent':raise ValueError('current role Agent model output required')
 if not isinstance(o.get('evidence_links'),list) or not o['evidence_links']:raise ValueError('evidence_links required')
 if o.get('cursor')!=int(i['cursor'])+1:raise ValueError('cursor must advance exactly once after valid model output')
 if any(isinstance(v,str) and v.strip().lower() in {'pending','todo','tbd','placeholder','待定','占位'} for v in o['semantic_result'].values()):raise ValueError('placeholder rejected')
 rr=Path(root)/'queue_v2.0.17'/i['role'];tid=i['task_id'];cp={'schema':'qingshan.semantic_role.checkpoint.v1','task_id':tid,'dispatch_id':i['dispatch_id'],'accepted_run_id':i['accepted_run_id'],'checkpoint':o.get('checkpoint'),'cursor':o.get('cursor',i['cursor']),'status':'microstep_complete','updated_at':time.time()};atomic(rr/'checkpoints'/(tid+'.json'),canon(cp)+'\n')
 art={'schema':'qingshan.semantic_role.artifact.v1','identity':{k:i[k] for k in ('task_id','dispatch_id','accepted_run_id')},'role':i['role'],'phase':i['phase'],'semantic_result':o['semantic_result'],'evidence_links':o['evidence_links'],'model_output_provenance':o['model_output_provenance'],'work_item_sha':i['work_item_sha']};ap=rr/'done'/(tid+'.artifact.json');atomic(ap,canon(art)+'\n');tp=rr/'running'/(tid+'.json');tp.unlink(missing_ok=True);Path(item_path).unlink(missing_ok=True);return {'status':'DONE','artifact':str(ap),'sha256':sha(ap.read_bytes())}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--work-item',required=True);p.add_argument('--model-output',required=True);a=p.parse_args();print(canon(main(a.root,a.work_item,a.model_output)))
