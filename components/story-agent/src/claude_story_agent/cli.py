"""Single-shot CLI + NDJSON server entrypoint."""
from __future__ import annotations
import argparse, json, os, sys
from .runtime import Runtime
from .model_adapter import ModelAdapter

def main(argv=None):
    ap = argparse.ArgumentParser(prog="claude-story-agent")
    ap.add_argument("verb", choices=["health","validate","review","generate","revise",
                                     "status","progress","generateMany","reviewMany","serve"])
    ap.add_argument("--in", dest="infile", help="request JSON file (default stdin)")
    ap.add_argument("--mode", help="model mode: anthropic|command|mock|auto")
    ap.add_argument("--command", help="external CLAUDE_STORY_COMMAND")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("CLAUDE_STORY_WORKERS","4")))
    a = ap.parse_args(argv)
    rt = Runtime(ModelAdapter(mode=a.mode, command=a.command), workers=a.workers)
    if a.verb == "serve":
        rt.serve_ndjson(); return 0
    try:
        if a.infile:
            with open(a.infile,encoding="utf-8") as stream: req=json.load(stream)
        elif a.verb in {"health","status","progress"}:
            req={}
        elif not sys.stdin.isatty():
            req=json.load(sys.stdin)
        else:
            req={}
    except (OSError,json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"status":"ERROR","error":f"invalid input ({type(exc).__name__})"}))
        return 2
    req["verb"] = a.verb
    try:
        result=rt.dispatch(req)
    except Exception as exc:
        result={"ok":False,"status":"ERROR","error":f"request failed ({type(exc).__name__}): {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok",False) else 1

if __name__ == "__main__":
    raise SystemExit(main())
