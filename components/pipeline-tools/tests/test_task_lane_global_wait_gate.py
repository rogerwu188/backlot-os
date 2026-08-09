import unittest

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
                [{"task_id": "NEXT", "lane_id": "ACTION", "state": "RUNNING", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": False,
                },
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertEqual(result["active_successor_task_ids"], ["NEXT"])

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
