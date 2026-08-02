#!/usr/bin/env python3
"""Five independent worker process lifecycle and health; no cron mutation."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
ROLES=('producer','writer','pipeline','editor','audit')
def start(package,runtime,state):
 state=Path(state);state.mkdir(parents=True,exist_ok=True);out={}
 for r in ROLES:
  pf=state/(r+'.pid')
  if pf.exists():
   try:os.kill(int(pf.read_text()),0);out[r]=int(pf.read_text());continue
   except (OSError,ValueError):pass
  p=subprocess.Popen([sys.executable,str(Path(package)/'file_worker.py'),'--root',str(runtime),'--role',r,'--daemon'],start_new_session=True);pf.write_text(str(p.pid)+'\n');out[r]=p.pid
 return out
def stop(state):
 out={}
 for r in ROLES:
  p=Path(state)/(r+'.pid')
  if p.exists():
   try:os.killpg(int(p.read_text()),signal.SIGTERM);out[r]='stopped'
   except (OSError,ValueError):out[r]='absent'
   p.unlink(missing_ok=True)
 return out
def health(runtime,state):
 out={}
 for r in ROLES:
  p=Path(state)/(r+'.pid');alive=False
  if p.exists():
   try:os.kill(int(p.read_text()),0);alive=True
   except OSError:pass
  hb=Path(runtime)/'queue_v2.0.17'/r/'heartbeat/worker.json';out[r]={'alive':alive,'heartbeat':hb.exists(),'independent_pid':p.exists()}
 return out
