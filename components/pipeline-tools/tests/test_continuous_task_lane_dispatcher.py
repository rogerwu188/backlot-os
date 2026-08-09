import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.continuous_task_lane_dispatcher import dispatch_cycle, select_ready_tasks


def scheduler(tasks):
    return {
        "schema": "backlotos.task_lane_scheduler_state.v1",
        "episode": "E01",
        "scheduler_decision": {"global_wait": False},
        "tasks": tasks,
    }


def task(task_id, state="READY", lane="L1", **extra):
    return {
        "task_id": task_id,
        "lane_id": lane,
        "state": state,
        "zero_cost": True,
        **extra,
    }


class ContinuousTaskLaneDispatcherTests(unittest.TestCase):
    def test_prioritizes_shot_deliverable_over_precompile(self):
        payload = scheduler(
            [
                task("PRE", deliverable_type="PRECOMPILE", priority=100),
                task("SHOT", deliverable_type="SHOT_PACKAGE", priority=1),
            ]
        )
        result = select_ready_tasks(payload, capacity=1)
        self.assertEqual(result["selected"], ["SHOT"])

    def test_remote_wait_does_not_consume_local_slot(self):
        payload = scheduler(
            [
                task("REMOTE", state="REMOTE_WAIT", wait_scope="TASK_LOCAL", zero_cost=False),
                task("LOCAL", dispatch={"kind": "event", "event_path": "events/local.json", "payload": {}}),
            ]
        )
        result = select_ready_tasks(payload, capacity=1)
        self.assertEqual(result["available_local_slots"], 1)
        self.assertEqual(result["selected"], ["LOCAL"])

    def test_event_intent_is_durable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.json"
            state.write_text(
                json.dumps(
                    scheduler(
                        [
                            task(
                                "SHOT",
                                deliverable_type="SHOT_PACKAGE",
                                dispatch={
                                    "kind": "event",
                                    "event_path": "events/shot.json",
                                    "payload": {"action": "build"},
                                },
                            )
                        ]
                    )
                ),
                encoding="utf-8",
            )
            first = dispatch_cycle(state, journal, root, capacity=1, apply=True)
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["outcomes"][0]["status"], "DISPATCHED")
            self.assertTrue((root / "events/shot.json").is_file())
            updated = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(updated["tasks"][0]["state"], "RUNNING")
            dispatches = json.loads(journal.read_text(encoding="utf-8"))["dispatches"]
            self.assertEqual(len(dispatches), 1)
            self.assertEqual(next(iter(dispatches.values()))["status"], "DISPATCHED")

            updated["tasks"][0]["state"] = "READY"
            state.write_text(json.dumps(updated), encoding="utf-8")
            second = dispatch_cycle(state, journal, root, capacity=1, apply=True)
            self.assertEqual(second["outcomes"][0]["status"], "REUSED_DURABLE_DISPATCH")
            self.assertEqual(len(json.loads(journal.read_text(encoding="utf-8"))["dispatches"]), 1)

    def test_missing_dispatch_descriptor_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.json"
            state.write_text(json.dumps(scheduler([task("NO-DISPATCH")])), encoding="utf-8")
            result = dispatch_cycle(state, journal, root, capacity=1, apply=True)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("DISPATCH_DESCRIPTOR_MISSING", result["outcomes"][0]["failures"])
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["tasks"][0]["state"], "READY")

    def test_command_requires_argv_not_shell_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            journal = root / "journal.json"
            payload = scheduler([task("BAD", dispatch={"kind": "command", "argv": "echo unsafe"})])
            state.write_text(json.dumps(payload), encoding="utf-8")
            result = dispatch_cycle(state, journal, root, capacity=1, apply=True)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("COMMAND_ARGV_MUST_BE_NONEMPTY_STRING_LIST", result["outcomes"][0]["failures"])


if __name__ == "__main__":
    unittest.main()
