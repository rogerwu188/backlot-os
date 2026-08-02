from __future__ import annotations
import json,sys,threading
from concurrent.futures import ThreadPoolExecutor
from . import __version__
from .core import Reviewer,repair_task,timeout_decision,human_report

class Agent:
 def __init__(self,reviewer):self.r=reviewer;self.lock=threading.Lock();self.jobs={};self.completed=0
 def write(self,x,out):
  with self.lock: out.write(json.dumps(x,ensure_ascii=False)+"\n");out.flush()
 def handle(self,q,emit=lambda x:None):
  m=q.get("method");p=q.get("params") or {}
  if m=="health":z={"status":"ready","version":__version__,"workers":self.r.workers,"ffmpeg":self.r.ffmpeg,"ffprobe":self.r.ffprobe}
  elif m=="validate":z=self.r.validate(p)
  elif m=="review":z=self.r.review(p)
  elif m=="reviewMany":z=self.r.review_many_report(p["items"],emit)
  elif m=="status":
   with self.lock: z={"status":"busy" if self.jobs else "ready","active_jobs":len(self.jobs),"jobs":list(self.jobs.values()),"completed_jobs":self.completed}
  elif m=="repairTask":z=repair_task(p["report"],p.get("include_warnings"))
  elif m=="timeoutDecision":z=timeout_decision(p["original_result"],float(p["elapsed_seconds"]),protected_reason=p.get("protected_reason"))
  elif m=="humanReport":z={"text":human_report(p["report"])}
  elif m=="promoteRule":z=self.r.promote(p["issue"],p["rule_id"])
  else:raise ValueError("unknown method: "+str(m))
  return {"id":q.get("id"),"ok":True,"result":z}
 def serve(self,inp=sys.stdin,out=sys.stdout):
  def one(q):
   job_id=str(q.get("id")); method=q.get("method")
   if method!="status":
    with self.lock:self.jobs[job_id]={"id":job_id,"method":method,"state":"running","progress":0.0}
   def emit(data):
    with self.lock:
     if job_id in self.jobs:self.jobs[job_id].update({"progress":data.get("progress",self.jobs[job_id]["progress"]),"last_event":data})
    self.write({"id":q.get("id"),"event":"progress","data":data},out)
   try:r=self.handle(q,emit)
   except Exception as e:r={"id":q.get("id"),"ok":False,"error":{"type":type(e).__name__,"message":str(e)}}
   if method!="status":
    with self.lock:self.jobs.pop(job_id,None);self.completed+=1
   self.write(r,out)
  with ThreadPoolExecutor(max_workers=self.r.workers) as pool:
   for line in inp:
    if line.strip():
     try:pool.submit(one,json.loads(line))
     except Exception as e:self.write({"id":None,"ok":False,"error":{"type":"JSONDecodeError","message":str(e)}},out)
