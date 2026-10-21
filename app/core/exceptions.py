class AppError(Exception):
    """Base application exception."""


class RetrievalError(AppError):
    """Raised when retrieval fails."""
class ConversationNotFoundError(Exception):
    """The requested conversation does not exist."""


class ConversationAccessError(Exception):
    """The authenticated user does not own the conversation."""


class GenerationError(Exception):
    """The answer model could not produce a response."""


class CitationValidationError(Exception):
    """A generated citation did not match retrieved evidence."""
