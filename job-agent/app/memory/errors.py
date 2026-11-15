"""Failures that callers must handle without changing memory backends."""


class SessionBusyError(RuntimeError):
    """Another request already owns this session."""


class SessionLeaseLostError(RuntimeError):
    """The session lock expired, changed owner, or could not be renewed."""
