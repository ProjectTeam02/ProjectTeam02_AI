class IndexManager:
    """Create and cache LlamaIndex indexes."""

    def get_or_create(self, collection: str):
        raise NotImplementedError
