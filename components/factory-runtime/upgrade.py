#!/usr/bin/env python3
import argparse,json,os,shutil
from pathlib import Path
from file_worker import atomic,canon
p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--install-root',required=True);p.add_argument('--writer-source-root');a=p.parse_args();src=Path(a.candidate);base=Path(a.install_root);dst=base/'versions'/src.name;dst.parent.mkdir(parents=True,exist_ok=True)
if not dst.exists():shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
cur=base/'candidate-current';old=os.readlink(cur) if cur.is_symlink() else None;tmp=base/'.candidate-current.partial';tmp.unlink(missing_ok=True);tmp.symlink_to(dst);os.replace(tmp,cur)
# Migration is copy-only, never removes/changes the running 2.0.16 Writer queue or cron.
migrated=False
if a.writer_source_root:
 s=Path(a.writer_source_root)/'queue_v2.0.16'/'writer';d=base/'runtime'/'queue_v2.0.17'/'writer'
 for sub in ('inbox','running','checkpoints'):
  if (s/sub).exists():
   (d/sub).mkdir(parents=True,exist_ok=True)
   for f in (s/sub).glob('*'):
    q=d/sub/f.name
    if f.is_file() and not q.exists():shutil.copy2(f,q);migrated=True
atomic(base/'upgrade_receipt.json',canon({'previous':old,'current':str(dst),'writer_ch482_copy_preserved':True,'writer_state_fields':['task_id','dispatch_id','accepted_run_id','recovery_fence','cursor','checkpoint'],'migrated_copy':migrated,'source_unchanged':True,'cron_modified':False,'live_modified':False,'activation_forbidden':True,'idempotent':True})+'\n')
