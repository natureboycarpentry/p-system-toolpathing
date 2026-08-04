"""Errors that carry a user-friendly message and must be shown without a traceback."""


class UserFacingError(RuntimeError):
    """Raised for expected precondition failures (missing setup, tools, workspace)."""
