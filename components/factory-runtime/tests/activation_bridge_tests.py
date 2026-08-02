#!/usr/bin/env python3

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PKG = Path(__file__).resolve().parents[1]


def mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, PKG / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = mod("sem19_auth", "owner_auth.py")
L = mod("sem19_live", "live_activation.py")
T = mod("sem19_timer", "timer_control.py")


class Bridge(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runtime = self.root / "runtime"
        self.install = self.root / "install"
        self.target = self.root / "target"
        self.target.mkdir()
        self.auth = PKG / "fixtures/sem17-one-time-live-activation-TEST-ONLY.json"

        self.auth_root = self.root / "shared/owner_authorizations"
        self.auth_root.mkdir(parents=True)
        self.live_root_patch = mock.patch.object(A, "LIVE_AUTH_ROOT", self.auth_root)
        self.live_root_patch.start()
        self.addCleanup(self.live_root_patch.stop)
        self.live_activation_root_patch = mock.patch.dict(
            L.validate.__globals__,
            {"LIVE_AUTH_ROOT": self.auth_root},
        )
        self.live_activation_root_patch.start()
        self.addCleanup(self.live_activation_root_patch.stop)
        self.real_auth = self.auth_root / "sem17-one-time-live-activation-REAL.json"
        real = json.loads(self.auth.read_text())
        real["authorization_id"] = self.real_auth.name
        real["test_only"] = False
        self.real_auth.write_text(json.dumps(real))

        writer = self.runtime / "queue_v2.0.16/writer"
        (writer / "running").mkdir(parents=True)
        (writer / "checkpoints").mkdir()
        task = {
            "task_id": "ch482",
            "dispatch_id": "d",
            "accepted_run_id": "run",
            "recovery_fence": "f",
            "cursor": 22,
        }
        (writer / "running/ch482.json").write_text(json.dumps(task))
        (writer / "checkpoints/ch482.json").write_text(
            json.dumps({"cursor": 22, "checkpoint": "cp22"})
        )

        for role in L.ROLES:
            queue = self.runtime / "queue_v2.0.17" / role
            for directory in (
                "inbox",
                "outbox",
                "receipts",
                "deadletter",
                "heartbeat",
                "locks",
                "pids",
            ):
                (queue / directory).mkdir(parents=True, exist_ok=True)
            (queue / "receipts/local_tool_probe.json").write_text("{}")

    def tearDown(self):
        self.temp.cleanup()

    def test_31_fixture_schema_valid(self):
        self.assertTrue(
            A.validate(self.auth, allow_test=True)["authorization"]["test_only"]
        )

    def test_32_fixture_live_rejected(self):
        self.assertRaisesRegex(
            ValueError,
            "outside approved shared root",
            A.validate,
            self.auth,
        )

    def test_33_dry_run_no_live_change(self):
        plan = L.activate(
            self.auth,
            self.install,
            self.runtime,
            self.target,
            allow_test=True,
        )
        self.assertFalse((self.install / "live-current").exists())
        self.assertEqual(plan["writer_before"]["cursor"], 22)

    def test_34_atomic_activation_ready_real_shape(self):
        self.assertIn("os.replace(tmp,current)", (PKG / "live_activation.py").read_text())

    def test_35_one_time_receipt_guard(self):
        receipt = (
            self.install
            / "activation-receipts"
            / (self.auth.name + ".consumed.json")
        )
        receipt.parent.mkdir(parents=True)
        receipt.write_text("{}")
        self.assertRaisesRegex(
            ValueError,
            "already consumed",
            L.activate,
            self.auth,
            self.install,
            self.runtime,
            self.target,
            False,
            True,
        )

    def test_36_rollback_ready(self):
        self.assertTrue(callable(L.rollback))
        self.assertIn("rollback-points", (PKG / "live_activation.py").read_text())

    def test_37_five_worker_health(self):
        health = L.health(self.runtime)
        self.assertEqual(set(health), set(L.ROLES))
        self.assertTrue(all(item["dirs"] for item in health.values()))

    def test_38_five_independent_timer_pids(self):
        self.assertIn("state/(r+'.pid')", (PKG / "timer_control.py").read_text())

    def test_39_writer_snapshot_exact(self):
        snapshot = L.writer_snapshot(self.runtime)
        self.assertEqual(
            (
                snapshot["task_id"],
                snapshot["dispatch_id"],
                snapshot["accepted_run_id"],
                snapshot["recovery_fence"],
                snapshot["cursor"],
                snapshot["checkpoint"],
            ),
            ("ch482", "d", "run", "f", 22, "cp22"),
        )

    def test_40_no_sessions_chat_cron_media_credits(self):
        source = "".join(
            (PKG / filename).read_text()
            for filename in ("owner_auth.py", "live_activation.py", "timer_control.py")
        )
        self.assertNotIn("sessions_send", source)
        self.assertNotIn("cron update", source)
        self.assertNotIn("credits", source)
        self.assertNotIn("media", source)

    def test_41_activation_candidate_forbidden(self):
        state = json.loads((PKG / "INSTALL_ACTIVATION.json").read_text())
        self.assertTrue(state["activation_forbidden"])

    def test_42_base_sha_bound(self):
        self.assertEqual(
            A.BASE_SHA,
            "a961d8412d69f98e70b9522c406406d4ebc68e738f51360b5b53c66f3cf4c300",
        )

    def test_43_real_auth_inside_shared_root_accepted(self):
        result = A.validate(self.real_auth)
        self.assertEqual(result["authorization_path"], str(self.real_auth.resolve()))

    def test_44_real_auth_outside_shared_root_rejected(self):
        outside = self.root / "chat-materialized-owner-claim.json"
        payload = json.loads(self.real_auth.read_text())
        payload["authorization_id"] = outside.name
        outside.write_text(json.dumps(payload))
        self.assertRaisesRegex(
            ValueError,
            "outside approved shared root",
            A.validate,
            outside,
            A.BASE_SHA,
            False,
        )

    def test_45_real_auth_symlink_rejected(self):
        link = self.auth_root / "owner-link.json"
        link.symlink_to(self.real_auth)
        self.assertRaisesRegex(
            ValueError,
            "symlink rejected",
            A.validate,
            link,
            A.BASE_SHA,
            False,
        )

    def test_46_path_traversal_rejected(self):
        traversed = (
            self.auth_root
            / ".."
            / "owner_authorizations"
            / self.real_auth.name
        )
        self.assertRaisesRegex(
            ValueError,
            "traversal rejected",
            A.validate,
            traversed,
            A.BASE_SHA,
            False,
        )

    def test_47_environment_cannot_override_live_root(self):
        outside_root = self.root / "attacker-selected-root"
        outside_root.mkdir()
        outside = outside_root / "chat-materialized-owner-claim.json"
        payload = json.loads(self.real_auth.read_text())
        payload["authorization_id"] = outside.name
        outside.write_text(json.dumps(payload))
        with mock.patch.dict(
            os.environ,
            {"QINGSHAN_OWNER_AUTH_ROOT": str(outside_root)},
            clear=True,
        ):
            self.assertRaisesRegex(
                ValueError,
                "outside approved shared root",
                A.validate,
                outside,
            )

    def test_48_live_plan_binds_authorization_root(self):
        plan = L.activate(
            self.real_auth,
            self.install,
            self.runtime,
            self.target,
        )
        self.assertEqual(plan["authorization_id"], self.real_auth.name)
        self.assertFalse((self.install / "live-current").exists())

    def test_49_live_cli_has_no_caller_selected_auth_root(self):
        self.assertNotIn("--auth-root", (PKG / "live_activation.py").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
