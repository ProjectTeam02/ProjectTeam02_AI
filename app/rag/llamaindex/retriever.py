class LlamaIndexRetriever:
    async def retrieve(self, query: str, top_k: int = 5):
        raise NotImplementedError
