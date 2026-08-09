import unittest
from datetime import datetime, timezone

from tools.task_lane_global_wait_gate import audit_scheduler_state


def state(tasks, *, global_wait=False, heartbeat=None):
    payload = {
        "schema": "backlotos.task_lane_scheduler_state.v1",
        "scheduler_decision": {"global_wait": global_wait},
        "tasks": tasks,
    }
    if heartbeat is not None:
        payload["heartbeat_integration"] = heartbeat
    return payload


CHECKED_AT = datetime(2026, 8, 9, 21, 40, tzinfo=timezone.utc)


def live_running(task_id="NEXT", *, role="PRODUCING", deliverable="SHOT_PACKAGE"):
    return {
        "task_id": task_id,
        "lane_id": "ACTION",
        "state": "RUNNING",
        "zero_cost": True,
        "deliverable_type": deliverable,
        "liveness_role": role,
        "lease_owner": "worker:test",
        "lease_expires_at": "2026-08-09T21:45:00Z",
        "last_progress_at": "2026-08-09T21:39:30Z",
        "next_due_at": "2026-08-09T21:41:00Z",
    }


class TaskLaneGlobalWaitGateTests(unittest.TestCase):
    def test_ready_zero_cost_task_makes_global_wait_fail(self):
        result = audit_scheduler_state(
            state([{"task_id": "PRECOMPILE", "lane_id": "PROMPTS", "state": "READY", "zero_cost": True}], global_wait=True)
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GLOBAL_WAIT_MASKS_READY_ZERO_COST_TASKS", {row["code"] for row in result["failures"]})

    def test_waiting_dependency_requires_exact_predecessor_id(self):
        result = audit_scheduler_state(
            state([{"task_id": "U19", "lane_id": "ACTION", "state": "WAITING_DEPENDENCY", "zero_cost": False}])
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("WAITING_DEPENDENCY_EXACT_PREDECESSOR_MISSING", {row["code"] for row in result["failures"]})

    def test_remote_wait_does_not_mask_ready_other_lane(self):
        result = audit_scheduler_state(
            state([
                {"task_id": "REMOTE", "lane_id": "ACTION", "state": "REMOTE_WAIT", "zero_cost": False, "wait_scope": "TASK_LOCAL"},
                {"task_id": "QA-PREP", "lane_id": "QA", "state": "READY", "zero_cost": True},
            ])
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["remote_wait_isolated_from_ready_lanes"])
        self.assertEqual(result["dispatchable_ready_task_ids"], ["QA-PREP"])

    def test_qingshan_production_schema_uses_same_gate(self):
        payload = state([{"task_id": "QA", "lane_id": "QA", "state": "READY", "zero_cost": True}])
        payload["schema"] = "qingshan.task_lane_scheduler_state.v1"
        payload["episode"] = "E40"
        result = audit_scheduler_state(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["episode"], "E40")

    def test_remote_wait_global_wait_fails(self):
        result = audit_scheduler_state(
            state([
                {"task_id": "REMOTE", "lane_id": "ACTION", "state": "REMOTE_WAIT", "zero_cost": False, "wait_scope": "TASK_LOCAL"},
                {"task_id": "QA-PREP", "lane_id": "QA", "state": "READY", "zero_cost": True},
            ], global_wait=True)
        )
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("REMOTE_WAIT_MASKS_READY_OTHER_LANES", codes)
        self.assertIn("GLOBAL_WAIT_MASKS_READY_ZERO_COST_TASKS", codes)

    def test_idle_unfinished_work_requires_legal_blocker_evidence(self):
        payload = state([
            {
                "task_id": "U19",
                "lane_id": "ACTION",
                "state": "WAITING_DEPENDENCY",
                "zero_cost": False,
                "exact_predecessor_task_id": "U18",
            },
            {
                "task_id": "U18",
                "lane_id": "ACTION",
                "state": "TERMINAL",
                "zero_cost": False,
            },
        ])
        result = audit_scheduler_state(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["liveness_state"], "FALSE_IDLE")
        self.assertIn(
            "IDLE_WITH_UNFINISHED_WORK_AND_NO_LEGAL_BLOCKER",
            {row["code"] for row in result["failures"]},
        )

    def test_evidenced_legal_blocker_is_not_false_idle(self):
        payload = state([
            {
                "task_id": "U18",
                "lane_id": "ACTION",
                "state": "TERMINAL",
                "zero_cost": False,
            },
            {
                "task_id": "U19",
                "lane_id": "ACTION",
                "state": "WAITING_DEPENDENCY",
                "zero_cost": False,
                "exact_predecessor_task_id": "U18",
            },
        ])
        payload["scheduler_decision"]["legal_blocker"] = {
            "code": "PREDECESSOR_QA_FAILED",
            "evidence_ref": "qa/u18.json",
            "next_recheck_at": "2026-08-09T00:00:00Z",
        }
        result = audit_scheduler_state(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["liveness_state"], "LEGALLY_BLOCKED")

    def test_heartbeat_return_fails_without_active_successor(self):
        result = audit_scheduler_state(
            state(
                [{"task_id": "DONE", "lane_id": "ACTION", "state": "TERMINAL", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": False,
                },
            )
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["heartbeat_return_allowed"])
        self.assertIn(
            "HEARTBEAT_RETURN_WITHOUT_ACTIVE_SUCCESSOR",
            {row["code"] for row in result["failures"]},
        )

    def test_heartbeat_return_passes_with_running_successor(self):
        result = audit_scheduler_state(
            state(
                [live_running()],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": False,
                },
            ),
            now=CHECKED_AT,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertEqual(result["active_successor_task_ids"], ["NEXT"])

    def test_running_without_scoped_lease_fails_closed(self):
        result = audit_scheduler_state(
            state(
                [{"task_id": "ORPHAN", "lane_id": "ACTION", "state": "RUNNING"}],
                heartbeat={"require_active_successor_before_return": True, "episode_terminal": False},
            ),
            now=CHECKED_AT,
        )
        codes = {row["code"] for row in result["failures"]}
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("RUNNING_LEASE_FIELDS_MISSING", codes)
        self.assertIn("HEARTBEAT_RETURN_WITHOUT_ACTIVE_SUCCESSOR", codes)
        self.assertEqual(result["stale_running_task_ids"], ["ORPHAN"])

    def test_expired_running_watchdog_is_not_active_successor(self):
        watchdog = live_running("WATCHDOG", role="OBSERVATION", deliverable="PIPELINE_GATE")
        watchdog["lease_expires_at"] = "2026-08-09T21:39:59Z"
        result = audit_scheduler_state(
            state(
                [watchdog],
                heartbeat={"require_active_successor_before_return": True, "episode_terminal": False},
            ),
            now=CHECKED_AT,
        )
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("RUNNING_LEASE_EXPIRED", codes)
        self.assertIn("HEARTBEAT_RETURN_WITHOUT_ACTIVE_SUCCESSOR", codes)
        self.assertEqual(result["active_successor_task_ids"], [])

    def test_overdue_running_progress_is_not_active_successor(self):
        producing = live_running()
        producing["next_due_at"] = "2026-08-09T21:39:59Z"
        result = audit_scheduler_state(
            state(
                [producing],
                heartbeat={"require_active_successor_before_return": True, "episode_terminal": False},
            ),
            now=CHECKED_AT,
        )
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("RUNNING_PROGRESS_OVERDUE", codes)
        self.assertIn("HEARTBEAT_RETURN_WITHOUT_ACTIVE_SUCCESSOR", codes)
        self.assertEqual(result["active_successor_task_ids"], [])

    def test_live_observation_only_cannot_satisfy_continuity(self):
        result = audit_scheduler_state(
            state(
                [live_running("WATCH", role="OBSERVATION", deliverable="QA_RECEIPT")],
                heartbeat={"require_active_successor_before_return": True, "episode_terminal": False},
            ),
            now=CHECKED_AT,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["observation_task_ids"], ["WATCH"])
        self.assertEqual(result["active_successor_task_ids"], [])
        self.assertIn(
            "HEARTBEAT_RETURN_WITHOUT_ACTIVE_SUCCESSOR",
            {row["code"] for row in result["failures"]},
        )

    def test_task_local_remote_wait_satisfies_continuity(self):
        result = audit_scheduler_state(
            state(
                [{
                    "task_id": "REMOTE",
                    "lane_id": "ACTION",
                    "state": "REMOTE_WAIT",
                    "wait_scope": "TASK_LOCAL",
                }],
                heartbeat={"require_active_successor_before_return": True, "episode_terminal": False},
            ),
            now=CHECKED_AT,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["active_successor_task_ids"], ["REMOTE"])

    def test_terminal_episode_may_return_without_successor(self):
        result = audit_scheduler_state(
            state(
                [{"task_id": "DONE", "lane_id": "ACTION", "state": "TERMINAL", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": True,
                },
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])


if __name__ == "__main__":
    unittest.main()
