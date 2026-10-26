from __future__ import annotations

from app.core.config import get_settings
from app.core.exceptions import ConversationAccessError
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.schemas.tutor import (
    Citation,
    InternalCitation,
    InternalTutorRequest,
    InternalTutorResponse,
    TutorRequest,
    TutorResponse,
)


class TutorService:
    def __init__(self, pipeline: MultiTurnRAG | None = None):
        self.pipeline = pipeline or MultiTurnRAG()

    async def answer(
        self, request: TutorRequest, authenticated_user_id: str | None = None
    ) -> TutorResponse:
        if (
            authenticated_user_id is not None
            and request.user_id != authenticated_user_id
        ):
            raise ConversationAccessError(
                "request user_id does not match authenticated user"
            )
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
                    source_id=item.source_id or item.document_id,
                    url=item.source_url or item.source,
                    version=item.version,
                    score=item.score,
                )
                for item in result.citations
            ],
            grounded=result.grounded,
        )

    async def answer_internal(
        self, request: InternalTutorRequest
    ) -> InternalTutorResponse:
        result = await self.pipeline.run(
            user_id=request.user_id,
            message=request.question,
            conversation_id=request.conversation_id,
            stage_id=request.stage_id,
            concept_id=request.concept_id,
            learning_concept=request.concept_id,
            incorrect_answer=(
                request.wrong_answer_context.as_prompt_text()
                if request.wrong_answer_context
                else None
            ),
            request_id=request.request_id,
        )
        settings = get_settings()
        generator = self.pipeline.answer_generator
        return InternalTutorResponse(
            conversationId=result.conversation_id,
            answer=result.answer,
            citations=[
                InternalCitation(
                    sourceId=item.source_id or item.document_id,
                    documentId=item.document_id,
                    documentVersion=item.version,
                    title=item.title,
                    url=item.source_url or item.source,
                )
                for item in result.citations
            ],
            grounded=result.grounded,
            requestId=request.request_id,
            modelName=(
                settings.llm_model
                if getattr(generator, "llm", None) is not None
                else "offline-extractive"
            ),
            usage=getattr(generator, "last_usage", None),
        )
