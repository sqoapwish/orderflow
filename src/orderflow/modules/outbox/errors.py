class InboxEventConflictError(RuntimeError):
    """The same event identifier was received with different content."""
