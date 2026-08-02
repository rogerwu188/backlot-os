#!/usr/bin/env python3
"""Minimal atomic activation bridge; dry-run by default and audit-forbidden until --activate."""
import argparse,hashlib,json,os,tempfile,time
from pathlib import Path
from owner_auth import validate,BASE_SHA
ROLES=('producer','writer','pipeline','editor','audit')
def canon(o):return json.dumps(o,sort_keys=True,separators=(',',':'))
def atomic(p,s):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(prefix='.partial-',dir=p.parent)
 try:
  with os.fdopen(fd,'w') as f:f.write(s);f.flush();os.fsync(f.fileno())
  os.replace(t,p);d=os.open(p.parent,os.O_DIRECTORY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:
  try:os.unlink(t)
  except FileNotFoundError:pass
def writer_snapshot(runtime):
 candidates=[]
 for ver in ('queue_v2.0.16','queue_v2.0.17'):
  rr=Path(runtime)/ver/'writer'
  for sub in ('running','inbox'):
   candidates+=list((rr/sub).glob('*ch482*.json')) if (rr/sub).exists() else []
 for p in candidates:
  t=json.loads(p.read_text());cp=Path(runtime)/p.parts[-4]/'writer'/'checkpoints'/(t['task_id']+'.json');c=json.loads(cp.read_text()) if cp.exists() else {}
  return {'task_id':t.get('task_id'),'dispatch_id':t.get('dispatch_id'),'accepted_run_id':t.get('accepted_run_id'),'recovery_fence':t.get('recovery_fence'),'cursor':c.get('cursor',c.get('resume_cursor',t.get('cursor'))),'checkpoint':c.get('checkpoint'),'task_path':str(p),'checkpoint_path':str(cp) if cp.exists() else None}
 return None
def health(runtime):
 base=Path(runtime)/'queue_v2.0.17';out={}
 for r in ROLES:
  rr=base/r;out[r]={'dirs':all((rr/x).is_dir() for x in ('inbox','outbox','receipts','deadletter','heartbeat','locks','pids')),'probe':(rr/'receipts/local_tool_probe.json').is_file()}
 return out
def activate(auth_path,install_root,runtime,target,activate=False,allow_test=False):
 root=Path(install_root);consumed=root/'activation-receipts';aid=Path(auth_path).name;receipt=consumed/(aid+'.consumed.json')
 if receipt.exists():raise ValueError('authorization already consumed')
 v=validate(auth_path,BASE_SHA,allow_test=allow_test);snap=writer_snapshot(runtime);h=health(runtime)
 if snap is None:raise ValueError('Writer ch482 state missing')
 if not all(x['dirs'] for x in h.values()):raise ValueError('five worker layouts unhealthy')
 current=root/'live-current';old=os.readlink(current) if current.is_symlink() else None
 plan={'schema':'qingshan.live_activation.plan.v1','authorization_id':aid,'authorization_sha256':v['authorization_sha256'],'base_package_sha256':BASE_SHA,'target':str(Path(target).resolve()),'previous':old,'five_worker_health':h,'writer_before':snap,'activation_requested':activate,'test_only':v['authorization']['test_only']}
 if not activate:return plan
 if allow_test or v['authorization']['test_only']:raise ValueError('test_only/dry-run authorization cannot activate live')
 rollback=root/'rollback-points'/aid;atomic(rollback,canon({'previous':old,'writer_snapshot':snap,'created_at':time.time()})+'\n')
 tmp=root/'.live-current.partial';tmp.unlink(missing_ok=True);tmp.symlink_to(Path(target).resolve());os.replace(tmp,current)
 after=writer_snapshot(runtime)
 if after!=snap:raise RuntimeError('Writer ch482 changed during activation')
 atomic(receipt,canon({**plan,'consumed':True,'activated_at':time.time(),'writer_after':after})+'\n')
 return {**plan,'activated':True,'receipt':str(receipt),'rollback_point':str(rollback)}
def rollback(install_root,authorization_id,runtime):
 root=Path(install_root);p=root/'rollback-points'/authorization_id;o=json.loads(p.read_text());before=writer_snapshot(runtime);cur=root/'live-current'
 if o['previous']:
  t=root/'.live-current.rollback';t.unlink(missing_ok=True);t.symlink_to(o['previous']);os.replace(t,cur)
 else:cur.unlink(missing_ok=True)
 after=writer_snapshot(runtime)
 if after!=before or after!=o['writer_snapshot']:raise RuntimeError('Writer ch482 not preserved across rollback')
 r=root/'activation-receipts'/(authorization_id+'.rollback.json');atomic(r,canon({'rolled_back':True,'writer_preserved':True,'previous':o['previous']})+'\n');return {'rolled_back':True}
def main():
 p=argparse.ArgumentParser();p.add_argument('--auth',required=True);p.add_argument('--install-root',required=True);p.add_argument('--runtime',required=True);p.add_argument('--target',required=True);p.add_argument('--dry-run',action='store_true');p.add_argument('--activate',action='store_true');a=p.parse_args()
 if a.activate==a.dry_run:raise SystemExit('choose exactly one of --dry-run/--activate')
 print(canon(activate(a.auth,a.install_root,a.runtime,a.target,activate=a.activate,allow_test=False)))
if __name__=='__main__':main()
