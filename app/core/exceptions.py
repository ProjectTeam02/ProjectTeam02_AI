class AppError(Exception):
    """Base application exception."""


class RetrievalError(AppError):
    """Raised when retrieval fails."""


class ConfigurationError(AppError):
    """Raised when a required provider or index setting is invalid."""


class IndexConfigurationError(ConfigurationError):
    """Raised when an existing vector index is incompatible with settings."""


class ConversationNotFoundError(Exception):
    """The requested conversation does not exist."""


class ConversationAccessError(Exception):
    """The authenticated user does not own the conversation."""


class GenerationError(Exception):
    """The answer model could not produce a response."""


class GenerationTimeoutError(GenerationError):
    """The configured generation deadline was exceeded."""


class CitationValidationError(Exception):
    """A generated citation did not match retrieved evidence."""
