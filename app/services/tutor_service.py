from __future__ import annotations

from app.core.exceptions import ConversationAccessError
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.schemas.tutor import Citation, TutorRequest, TutorResponse


class TutorService:
    def __init__(self, pipeline: MultiTurnRAG | None = None):
        self.pipeline = pipeline or MultiTurnRAG()

    async def answer(self, request: TutorRequest, authenticated_user_id: str | None = None) -> TutorResponse:
        if authenticated_user_id is not None and request.user_id != authenticated_user_id:
            raise ConversationAccessError("request user_id does not match authenticated user")
        result = await self.pipeline.run(
            user_id=authenticated_user_id or request.user_id,
            message=request.message,
            conversation_id=request.conversation_id,
            learning_concept=request.learning_concept,
            incorrect_answer=request.incorrect_answer,
        )
        return TutorResponse(
            answer=result.answer,
            conversation_id=result.conversation_id,
            citations=[
                Citation(
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    title=item.title,
                    source=item.source,
                    version=item.version,
                    score=item.score,
                )
                for item in result.citations
            ],
        )
