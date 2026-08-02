from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .intake import import_file, import_url
from .models import IntakeError, ProjectOptions
from .pipeline import create_project, credit_summary, record_credit, run_story_stage, status
from .web import serve
from .agent_host import ROLES, serve_role


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="backlotos", description="One-click AI film production")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="open the local production console")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8787)
    start.add_argument("--projects-root", type=Path)
    start.add_argument("--no-browser", action="store_true")
    create = sub.add_parser("create", help="create and start a project")
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument("--url")
    source.add_argument("--file", type=Path)
    create.add_argument("--type", choices=["short_drama", "long_drama"], default="short_drama")
    create.add_argument("--episodes", type=int)
    create.add_argument("--episode-minutes", type=float)
    create.add_argument("--aspect", choices=["9:16", "16:9"], default="9:16")
    create.add_argument("--visual", choices=["live_action", "animation"], default="live_action")
    create.add_argument("--projects-root", type=Path)
    create.add_argument("--no-run", action="store_true", help="create queues without starting Story Agent")
    run = sub.add_parser("run", help="resume queued Story Agent work")
    run.add_argument("project", type=Path)
    run.add_argument("--workers", type=int, default=4)
    show = sub.add_parser("status", help="show project status")
    show.add_argument("project", type=Path)
    cost = sub.add_parser("cost", help="show project or episode credit totals")
    cost.add_argument("project", type=Path)
    cost.add_argument("--episode")
    credit = sub.add_parser("record-credit", help="append a provider credit event")
    credit.add_argument("project", type=Path)
    credit.add_argument("--episode", required=True)
    credit.add_argument("--stage", required=True)
    credit.add_argument("--consumed", type=float, required=True)
    credit.add_argument("--refunded", type=float, default=0)
    credit.add_argument("--estimated", type=float)
    credit.add_argument("--provider", default="unknown")
    credit.add_argument("--provider-task-id")
    credit.add_argument("--evidence-ref")
    credit.add_argument("--provisional", action="store_true")
    sub.add_parser("health", help="show launcher health")
    agent = sub.add_parser("agent", help="run one isolated BacklotOS agent service")
    agent.add_argument("--role", choices=sorted(ROLES), required=True)
    agent.add_argument("--host", default="127.0.0.1")
    agent.add_argument("--port", type=int, required=True)
    agent.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            serve(args.host, args.port, args.projects_root, not args.no_browser)
            return 0
        if args.command == "health":
            _print({"ok": True, "status": "ready", "version": __version__, "entrypoint": "backlotos start", "agent_roles": sorted(ROLES)})
            return 0
        if args.command == "agent":
            serve_role(args.role, args.host, args.port, args.workers)
            return 0
        if args.command == "status":
            _print(status(args.project))
            return 0
        if args.command == "cost":
            _print(credit_summary(args.project, args.episode))
            return 0
        if args.command == "record-credit":
            event = record_credit(args.project, args.episode, args.stage, args.consumed, args.refunded, args.estimated, args.provider, args.provider_task_id, args.evidence_ref, not args.provisional)
            _print({"ok": True, "event": event, "summary": credit_summary(args.project, args.episode)})
            return 0
        if args.command == "run":
            result = run_story_stage(args.project, args.workers)
            _print(result)
            return 0 if result.get("ok") else 2
        options = ProjectOptions.from_values(args.type, args.episodes, args.episode_minutes, args.aspect, args.visual)
        imported = import_url(args.url) if args.url else import_file(args.file)
        project = create_project(imported, options, args.projects_root)
        result = {"ok": True, "status": "STARTED", "project_path": str(project), "episodes": options.episode_count}
        if not args.no_run:
            result["story"] = run_story_stage(project)
        _print(result)
        return 0
    except IntakeError as exc:
        _print({"ok": False, "status": "INPUT_ERROR", "error": str(exc)})
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
