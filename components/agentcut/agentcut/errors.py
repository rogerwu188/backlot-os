class AgentCutError(Exception):
    """Base exception for errors safe to return to an agent."""


class ValidationError(AgentCutError):
    """The project JSON is invalid."""

