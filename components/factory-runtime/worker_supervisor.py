#!/usr/bin/env python3
"""Persistent fallback supervisor: five separate role processes; restart is per-role."""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from file_worker import ROLES,init,atomic,canon
HERE=Path(__file__).resolve().parent
def start(root,once=False):
 base=init(root);children={}
 for r in ROLES:
  p=subprocess.Popen([sys.executable,str(HERE/'file_worker.py'),'--root',str(root),'--role',r,'--once' if once else '--daemon'],start_new_session=True)
  children[r]=p;atomic(base/r/'pids'/'supervisor-child.pid',str(p.pid)+'\n')
 if once:
  codes={r:p.wait(timeout=20) for r,p in children.items()};return codes
 atomic(Path(root)/'queue_v2.0.17'/'supervisor.pid',str(os.getpid())+'\n')
 while True:
  time.sleep(2)
  for r,p in list(children.items()):
   if p.poll() is not None:
    n=subprocess.Popen([sys.executable,str(HERE/'file_worker.py'),'--root',str(root),'--role',r,'--daemon'],start_new_session=True);children[r]=n;atomic(base/r/'pids'/'supervisor-child.pid',str(n.pid)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--once',action='store_true');a=p.parse_args();x=start(a.root,a.once);print(json.dumps(x,sort_keys=True)) if x is not None else None
if __name__=='__main__':main()
