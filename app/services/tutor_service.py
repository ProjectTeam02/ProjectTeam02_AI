from app.schemas.tutor import TutorRequest, TutorResponse


class TutorService:
    async def answer(self, request: TutorRequest) -> TutorResponse:
        # TODO: call the multi-turn RAG pipeline.
        return TutorResponse(
            answer=f"Received: {request.message}",
            conversation_id=request.conversation_id,
        )
