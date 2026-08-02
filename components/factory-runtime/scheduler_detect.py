#!/usr/bin/env python3
import json,shutil,subprocess
def detect():
 oc=shutil.which('openclaw')
 if oc:
  try:
   x=subprocess.run([oc,'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
   if x.returncode==0:return {'method':'openclaw_local_scheduler','available':True,'fallback':'package_worker_supervisor'}
  except Exception:pass
 return {'method':'package_worker_supervisor','available':True,'fallback':None}
if __name__=='__main__':print(json.dumps(detect(),sort_keys=True))
