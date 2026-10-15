class HistoryManager:
    async def load(self, conversation_id: str):
        raise NotImplementedError

    async def append(self, conversation_id: str, message: str):
        raise NotImplementedError
