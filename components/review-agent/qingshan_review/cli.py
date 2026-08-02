from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from .agent import Agent
from .core import Reviewer,repair_task

def main(argv=None):
 p=argparse.ArgumentParser(prog="qingshan-review");p.add_argument("--workers",type=int,default=int(os.environ.get("BACKLOT_WORKERS",os.environ.get("QINGSHAN_WORKERS","4"))));p.add_argument("--ledger",default=os.environ.get("BACKLOT_ISSUE_LEDGER",os.environ.get("QINGSHAN_ISSUE_LEDGER")));p.add_argument("--registry",default=os.environ.get("BACKLOT_RULE_REGISTRY",os.environ.get("QINGSHAN_RULE_REGISTRY")));p.add_argument("--production-root",default=os.environ.get("BACKLOT_PROJECT_ROOT",os.environ.get("QINGSHAN_PRODUCTION_ROOT",os.getcwd())))
 s=p.add_subparsers(dest="cmd",required=True)
 for n in ("review","validate"):
  x=s.add_parser(n);x.add_argument("input")
 x=s.add_parser("review-many");x.add_argument("input")
 s.add_parser("serve");s.add_parser("health")
 x=s.add_parser("repair-task");x.add_argument("input")
 a=p.parse_args(argv);r=Reviewer(a.workers,a.ledger,a.registry,a.production_root)
 try:
  if a.cmd=="serve": Agent(r).serve();return 0
  if a.cmd=="health": out=Agent(r).handle({"id":"cli","method":"health"})["result"]
  else:
   raw=json.loads(Path(a.input).read_text())
   if a.cmd=="review":out=r.review(raw)
   elif a.cmd=="review-many":out=r.review_many_report(raw["items"])
   elif a.cmd=="validate":out=r.validate(raw)
   else:out=repair_task(raw)
 except (OSError,json.JSONDecodeError,ValueError,KeyError,TypeError) as exc:
  print(json.dumps({"ok":False,"error":{"type":"SchemaError" if isinstance(exc,(ValueError,KeyError,TypeError)) else type(exc).__name__,"message":str(exc)}},ensure_ascii=False,indent=2));return 2
 print(json.dumps(out,ensure_ascii=False,indent=2));return 1 if out.get("status") in {"FAIL","CONTENT_FAIL","CAPABILITY_FAIL","ERROR"} else 0

if __name__=="__main__":raise SystemExit(main())
