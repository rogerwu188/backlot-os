import pytest

from backlotos_producer_supervisor.invoker import AgentInvoker, CapabilityError
from backlotos_producer_supervisor.runtime import Runtime


@pytest.mark.parametrize("verb", ["publish", "release", "delete", "overwrite-final", "platform-upload", "platform-delete", "human-release-authorization"])
@pytest.mark.parametrize("bypass_flags", [
    {},
    {"force": True},
    {"confirm": True},
    {"override": True},
    {"force_pass": True, "confirm": "yes", "human_approved": True, "skip_gate": True},
])
def test_irreversible_verbs_always_blocked_no_bypass(verb, bypass_flags):
    r = Runtime()
    result = r.dispatch({"verb": verb, "params": bypass_flags})
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "HUMAN_AUTHORIZATION_REQUIRED"


@pytest.mark.parametrize("action", ["publish", "release", "delete", "overwrite_final", "platform_upload", "platform_delete", "human_release_authorization"])
def test_irreversible_action_param_always_blocked(action):
    r = Runtime()
    result = r.dispatch({"verb": "dispatch", "params": {"action": action, "force": True, "confirm": True}})
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "HUMAN_AUTHORIZATION_REQUIRED"


def test_dispatch_to_human_stage_is_blocked_not_faked(tmp_project):
    r = Runtime(AgentInvoker(mock_fn=lambda a, p: {"ok": True}))
    result = r.dispatch({"verb": "dispatch", "params": {
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "human_release_authorization", "payload": {},
    }})
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "HUMAN_AUTHORIZATION_REQUIRED"


def test_capability_fail_when_no_invoker_backend_configured(tmp_project):
    # AgentInvoker with mode "command" but no env var set for the target agent
    invoker = AgentInvoker(mode="command")
    r = Runtime(invoker)
    result = r.dispatch({"verb": "dispatch", "params": {
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate", "payload": {},
    }})
    # must be BLOCKED/CAPABILITY_FAIL -- never a fabricated PASS/COMPLETED
    assert result["status"] in ("BLOCKED", "CAPABILITY_FAIL")
    assert result.get("reason") in ("CAPABILITY_FAIL", None) or result.get("status") == "CAPABILITY_FAIL"
    assert result["status"] != "COMPLETED"


def test_invoker_raises_capability_error_not_silent_pass():
    invoker = AgentInvoker(mode="command")
    with pytest.raises(CapabilityError):
        invoker.invoke("story", {"spec": {}})
