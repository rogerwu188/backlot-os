import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.continuous_task_lane_dispatcher import dispatch_cycle, select_ready_tasks
from tools.task_lane_state_store import (
    SchedulerWriteConflict,
    commit_task_updates,
    read_scheduler_snapshot,
)


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
            self.assertEqual(first["state_commit"]["status"], "COMMITTED_CAS")
            self.assertTrue((root / "events/shot.json").is_file())
            updated = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(updated["tasks"][0]["state"], "RUNNING")
            for field in ("lease_owner", "lease_expires_at", "last_progress_at", "next_due_at"):
                self.assertTrue(updated["tasks"][0].get(field), field)
            dispatches = json.loads(journal.read_text(encoding="utf-8"))["dispatches"]
            self.assertEqual(len(dispatches), 1)
            self.assertEqual(next(iter(dispatches.values()))["status"], "DISPATCHED")

            updated["tasks"][0]["state"] = "READY"
            state.write_text(json.dumps(updated), encoding="utf-8")
            second = dispatch_cycle(state, journal, root, capacity=1, apply=True)
            self.assertEqual(second["outcomes"][0]["status"], "REUSED_DURABLE_DISPATCH")
            self.assertEqual(len(json.loads(journal.read_text(encoding="utf-8"))["dispatches"]), 1)
            reused = json.loads(state.read_text(encoding="utf-8"))["tasks"][0]
            self.assertTrue(reused["lease_owner"].startswith("dispatch-recovery:"))

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

    def test_expected_sha_conflict_reloads_and_merges_by_task_id(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text(
                json.dumps(scheduler([task("A"), task("B")])), encoding="utf-8"
            )
            base = read_scheduler_snapshot(state)

            external = json.loads(state.read_text(encoding="utf-8"))
            external["tasks"][0]["state"] = "RUNNING"
            state.write_text(json.dumps(external), encoding="utf-8")

            proposed_b = dict(base.payload["tasks"][1], state="QA")
            receipt = commit_task_updates(
                state,
                base_snapshot=base,
                task_updates={"B": proposed_b},
                writer_id="test-merge",
            )
            self.assertEqual(receipt["status"], "COMMITTED_RELOAD_MERGE")
            final = {item["task_id"]: item for item in json.loads(state.read_text())["tasks"]}
            self.assertEqual(final["A"]["state"], "RUNNING")
            self.assertEqual(final["B"]["state"], "QA")

    def test_same_task_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text(json.dumps(scheduler([task("A")])), encoding="utf-8")
            base = read_scheduler_snapshot(state)

            external = json.loads(state.read_text(encoding="utf-8"))
            external["tasks"][0]["state"] = "TERMINAL"
            state.write_text(json.dumps(external), encoding="utf-8")

            with self.assertRaises(SchedulerWriteConflict) as raised:
                commit_task_updates(
                    state,
                    base_snapshot=base,
                    task_updates={"A": dict(base.payload["tasks"][0], state="RUNNING")},
                    writer_id="test-conflict",
                )
            self.assertEqual(raised.exception.task_ids, ["A"])
            self.assertEqual(json.loads(state.read_text())["tasks"][0]["state"], "TERMINAL")

    def test_three_concurrent_writers_preserve_disjoint_task_updates(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text(
                json.dumps(scheduler([task("A"), task("B"), task("C")])),
                encoding="utf-8",
            )
            barrier = threading.Barrier(3)

            def writer(task_id):
                snapshot = read_scheduler_snapshot(state)
                proposed = next(
                    dict(item, state="RUNNING", claimed_by=f"writer-{task_id}")
                    for item in snapshot.payload["tasks"]
                    if item["task_id"] == task_id
                )
                barrier.wait(timeout=5)
                return commit_task_updates(
                    state,
                    base_snapshot=snapshot,
                    task_updates={task_id: proposed},
                    writer_id=f"writer-{task_id}",
                )

            with ThreadPoolExecutor(max_workers=3) as pool:
                receipts = list(pool.map(writer, ("A", "B", "C")))

            self.assertEqual(
                sorted(receipt["status"] for receipt in receipts),
                ["COMMITTED_CAS", "COMMITTED_RELOAD_MERGE", "COMMITTED_RELOAD_MERGE"],
            )
            final = {item["task_id"]: item for item in json.loads(state.read_text())["tasks"]}
            self.assertEqual(set(final), {"A", "B", "C"})
            for task_id in ("A", "B", "C"):
                self.assertEqual(final[task_id]["state"], "RUNNING")
                self.assertEqual(final[task_id]["claimed_by"], f"writer-{task_id}")


if __name__ == "__main__":
    unittest.main()
