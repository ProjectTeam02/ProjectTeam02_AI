class AppError(Exception):
    """Base application exception."""


class RetrievalError(AppError):
    """Raised when retrieval fails."""
