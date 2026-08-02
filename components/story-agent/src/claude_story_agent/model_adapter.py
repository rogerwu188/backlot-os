"""Replaceable model layer: anthropic | command | mock.

Hard rules:
  * NEVER write, log, or return a real API key.
  * If no usable model backend -> raise CapabilityError (caller returns
    CAPABILITY_FAIL). Never fabricate a PASS or invent output.
  * If ANTHROPIC_API_KEY is absent, the anthropic backend is UNAVAILABLE;
    we do not guess, prompt for, or emit any key.
"""
from __future__ import annotations
import importlib.util, os, json, re, shlex, subprocess, shutil

DEFAULT_MIN_MODEL_VERSION = "4.8"


def _version_tuple(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", value or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _declared_model_version(model: str) -> tuple[int, int] | None:
    explicit = os.environ.get("CLAUDE_STORY_MODEL_VERSION", "").strip()
    if explicit:
        return _version_tuple(explicit)
    # Anthropic IDs commonly encode the family release, e.g. claude-sonnet-4-5-*.
    match = re.search(r"^claude(?:-[a-z]+)*-(\d+)[.-](\d+)(?:-|$)", model.lower())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _model_policy(model: str) -> dict:
    minimum_text = os.environ.get("CLAUDE_STORY_MIN_MODEL_VERSION", DEFAULT_MIN_MODEL_VERSION).strip()
    minimum = _version_tuple(minimum_text)
    actual = _declared_model_version(model)
    valid_minimum = minimum is not None
    passes = bool(model and valid_minimum and actual is not None and actual >= minimum)
    return {
        "policy": f"claude>={minimum_text}", "minimum_model_version": minimum_text,
        "configured_model": model or None,
        "declared_model_version": f"{actual[0]}.{actual[1]}" if actual else None,
        "version_verified": actual is not None, "passes": passes,
    }

class CapabilityError(RuntimeError):
    """Raised when the requested capability cannot execute (no model)."""

def _has_anthropic_key() -> bool:
    v = os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(v) and v.strip() not in ("", "your-key-here", "changeme")

class ModelAdapter:
    def __init__(self, mode: str | None = None, command: str | None = None):
        self.mode = mode or os.environ.get("CLAUDE_STORY_MODE", "auto")
        self.command = command or os.environ.get("CLAUDE_STORY_COMMAND", "")
        self._mock = None
        if self.mode == "auto":
            if self.command:
                self.mode = "command"
            elif _has_anthropic_key():
                self.mode = "anthropic"
            else:
                self.mode = "unavailable"

    # ---- health: does a real backend exist? (never reveals key value) ----
    def health(self) -> dict:
        if self.mode == "mock":
            return {"mode": "mock", "available": True, "note": "offline test backend", "model_policy": _model_policy("test-mock")}
        if self.mode == "command":
            try:
                argv = shlex.split(self.command)
            except ValueError:
                argv = []
            ok = bool(argv) and bool(shutil.which(argv[0]))
            return {"mode": "command", "available": ok,
                    "command_present": bool(self.command)}
        if self.mode == "anthropic":
            key_present = _has_anthropic_key()
            package_present = importlib.util.find_spec("anthropic") is not None
            model = os.environ.get("CLAUDE_STORY_ANTHROPIC_MODEL", "").strip()
            model_present = bool(model)
            policy = _model_policy(model)
            return {"mode": "anthropic",
                    "available": key_present and package_present and model_present and policy["passes"],
                    "api_key_present": key_present,
                    "package_present": package_present,
                    "model_configured": model_present,
                    "model_policy": policy}
        return {"mode": "unavailable", "available": False}

    def set_mock(self, fn):
        self._mock = fn
        self.mode = "mock"

    # ---- invoke: returns model text; raises CapabilityError if no backend ----
    def complete(self, system: str, user: str) -> str:
        if self.mode == "mock":
            if self._mock is None:
                raise CapabilityError("mock backend selected but no mock fn set")
            return self._mock(system, user)
        if self.mode == "command":
            if not self.command:
                raise CapabilityError("CLAUDE_STORY_COMMAND not set")
            try:
                argv = shlex.split(self.command)
            except ValueError:
                raise CapabilityError("CLAUDE_STORY_COMMAND is not valid shell-style argv")
            if not argv or not shutil.which(argv[0]):
                raise CapabilityError("configured command is unavailable")
            payload = json.dumps({"system": system, "user": user}, ensure_ascii=False)
            try:
                proc = subprocess.run(argv, shell=False, input=payload,
                                      capture_output=True, text=True, timeout=600)
            except Exception as e:
                raise CapabilityError(f"configured command could not execute ({type(e).__name__})")
            if proc.returncode != 0:
                raise CapabilityError(f"configured command exited with code {proc.returncode}; stderr withheld")
            return proc.stdout
        if self.mode == "anthropic":
            if not _has_anthropic_key():
                raise CapabilityError("ANTHROPIC_API_KEY absent; anthropic backend unavailable")
            try:
                import anthropic  # optional dep
            except ImportError:
                raise CapabilityError("anthropic package not installed")
            client = anthropic.Anthropic()  # reads key from env itself; we never touch value
            model = os.environ.get("CLAUDE_STORY_ANTHROPIC_MODEL", "").strip()
            if not model:
                raise CapabilityError("CLAUDE_STORY_ANTHROPIC_MODEL is not configured")
            policy = _model_policy(model)
            if not policy["passes"]:
                raise CapabilityError(
                    "configured Anthropic model does not satisfy the Claude >=4.8 policy; "
                    "set a supported provider model ID and CLAUDE_STORY_MODEL_VERSION"
                )
            try:
                msg = client.messages.create(
                    model=model, max_tokens=8000,
                    system=system, messages=[{"role": "user", "content": user}])
            except Exception as exc:
                raise CapabilityError(f"anthropic request failed ({type(exc).__name__}); provider details withheld")
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        raise CapabilityError("no usable model backend (mode=unavailable)")
