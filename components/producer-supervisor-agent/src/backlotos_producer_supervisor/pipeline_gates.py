"""Wraps GENERIC (payload-dict, no hardcoded episode/character names)
pipeline-tools gate modules as verb-dispatched semantic checks for the
BACKLOT_PIPELINE_COMMAND adapter.

Episode-specific one-off scripts (build_e*.py, audit_e*.py, finalize_e*.py,
and anything else with hardcoded episode numbers or source-drama character names)
are intentionally NOT imported here -- see AUDIT.md for the full list and
the reasoning per module.

Loading strategy: the pipeline-tools directory is NOT a Python package (no
__init__.py, filenames like `common_sense_causality_gate.py` are plain
scripts). We locate it via BACKLOT_PIPELINE_TOOLS_DIR if set, else by
walking up from this file's location to find a sibling `pipeline-tools`
directory (true in this repo's layout: components/producer-supervisor-agent
and components/pipeline-tools are siblings). If neither resolves, every
verb below reports ADAPTER_REQUIRED -- it never fabricates a PASS.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable

GENERIC_GATE_MODULES = {
    "dramatic-quality": "dramatic_quality_gate",
    "common-sense-causality": "common_sense_causality_gate",
    "anti-padding": "anti_padding_gate",
    "action-visualization-readability": "action_visualization_readability_gate",
    "cut-motivation": "cut_motivation_gate",
    "defect-tolerance": "defect_tolerance_gate",
}

# edit_plan_integrity_gate exposes evaluate_plan_rows(rows, target_fps, tolerance)
# rather than evaluate(payload) -- handled specially below.

# continuity_auditor.py, density_gate_watch.py, evidence_gate_watch.py operate on
# real media files / directory scans via a CLI __main__, not a pure
# evaluate(payload)->dict function; they are NOT wrapped here (see AUDIT.md).
# Media/image/video/audio generation itself has no provider integration in
# this sandbox and is never faked.

NOT_WRAPPED_REQUIRES_MEDIA_OR_CLI = {
    "continuity-auditor": "operates on real video files via ffmpeg CLI, not a payload dict",
    "density-gate-watch": "is a watch-loop CLI utility, not a payload evaluator",
    "evidence-gate-watch": "is a filesystem token scanner CLI, not a payload evaluator",
    "storyboard-generation": "requires a live media-generation provider (image/video/audio) -- no provider configured in this package",
    "media-generation": "requires a live media-generation provider -- no provider configured in this package",
}


def _tools_dir() -> Path | None:
    env_dir = os.environ.get("BACKLOT_PIPELINE_TOOLS_DIR", "")
    if env_dir and Path(env_dir).is_dir():
        return Path(env_dir)
    install_root = Path(os.environ.get("BACKLOT_INSTALL_DIR", Path.home() / ".local" / "share" / "backlotos"))
    installed_tools = install_root / "share" / "pipeline-tools"
    if installed_tools.is_dir():
        return installed_tools
    cwd_tools = Path.cwd() / "components" / "pipeline-tools"
    if cwd_tools.is_dir():
        return cwd_tools
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "pipeline-tools"
        if candidate.is_dir():
            return candidate
    return None


def _load_module(module_file_stem: str):
    tools_dir = _tools_dir()
    if tools_dir is None:
        return None
    path = tools_dir / f"{module_file_stem}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"backlotos_pipeline_tools_{module_file_stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    tools_dir_str = str(tools_dir)
    inserted = tools_dir_str not in sys.path
    if inserted:
        sys.path.insert(0, tools_dir_str)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # A gate module with unmet sibling imports (e.g. ffmpeg-dependent
        # helpers) is not usable; report unavailable rather than raising.
        sys.modules.pop(spec.name, None)
        return None
    finally:
        if inserted and tools_dir_str in sys.path:
            sys.path.remove(tools_dir_str)
    return module


def run_gate(gate_name: str, payload: dict) -> dict:
    if gate_name in NOT_WRAPPED_REQUIRES_MEDIA_OR_CLI:
        return {"ok": False, "status": "ADAPTER_REQUIRED", "gate": gate_name, "reason": NOT_WRAPPED_REQUIRES_MEDIA_OR_CLI[gate_name]}
    module_stem = GENERIC_GATE_MODULES.get(gate_name)
    if module_stem is None:
        return {"ok": False, "status": "ERROR", "gate": gate_name, "error": f"unknown gate: {gate_name}", "known_gates": sorted(GENERIC_GATE_MODULES)}
    module = _load_module(module_stem)
    if module is None:
        return {"ok": False, "status": "ADAPTER_REQUIRED", "gate": gate_name, "error": f"pipeline-tools module '{module_stem}.py' not found; set BACKLOT_PIPELINE_TOOLS_DIR"}
    evaluate: Callable[[dict], dict] | None = getattr(module, "evaluate", None)
    if evaluate is None:
        return {"ok": False, "status": "ERROR", "gate": gate_name, "error": f"module '{module_stem}' has no evaluate(payload) function"}
    try:
        result = evaluate(payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "ERROR", "gate": gate_name, "error": f"gate evaluation failed ({type(exc).__name__})"}
    failure_statuses = {"FAIL", "FAILED", "ERROR", "CAPABILITY_FAIL", "ADAPTER_REQUIRED", "NOT_RUN", "BLOCKED"}
    ok = str(result.get("status", "")).upper() not in failure_statuses if isinstance(result, dict) and "status" in result else bool(result.get("ok", False))
    return {"ok": ok, "status": result.get("status", "PASS" if ok else "FAIL"), "gate": gate_name, "result": result}


def run_edit_plan_integrity(rows: list, target_fps: float, tolerance: float = 0.05) -> dict:
    module = _load_module("edit_plan_integrity_gate")
    if module is None:
        return {"ok": False, "status": "ADAPTER_REQUIRED", "gate": "edit-plan-integrity", "error": "pipeline-tools module 'edit_plan_integrity_gate.py' not found"}
    fn = getattr(module, "evaluate_plan_rows", None)
    if fn is None:
        return {"ok": False, "status": "ERROR", "gate": "edit-plan-integrity", "error": "evaluate_plan_rows not found"}
    try:
        failures = fn(rows, target_fps, tolerance)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "ERROR", "gate": "edit-plan-integrity", "error": f"gate evaluation failed ({type(exc).__name__})"}
    return {"ok": not failures, "status": "FAIL" if failures else "PASS", "gate": "edit-plan-integrity", "failures": failures}


def health() -> dict:
    tools_dir = _tools_dir()
    available = {}
    for name, stem in GENERIC_GATE_MODULES.items():
        available[name] = _load_module(stem) is not None
    available["edit-plan-integrity"] = _load_module("edit_plan_integrity_gate") is not None
    for name in NOT_WRAPPED_REQUIRES_MEDIA_OR_CLI:
        available[name] = False
    any_available = any(available.values())
    return {
        "ok": any_available, "status": "ready" if any_available else "dependency_unavailable", "tools_dir": str(tools_dir) if tools_dir else None,
        "gates": available,
        "any_available": any_available,
    }
