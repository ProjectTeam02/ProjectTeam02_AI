# 파일 역할: LlamaIndex 기반 RAG 검색·생성·메모리·인덱싱 기능을 제공합니다.
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.harness import ExecutionHarness, StageContract
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import HistoryManager
from app.rag.retrieval.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.schemas.tutor import PersonalizedTutorContext


@dataclass(slots=True)
class RAGResult:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    conversation_id: str
    answer: str
    citations: list[RetrievedDocument]
    rewritten_query: str
    retrieved_documents: list[RetrievedDocument]
    grounded: bool = False
    history_from_seq: int | None = None
    trace: list[dict[str, object]] | None = None


class MultiTurnRAG:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    def __init__(
        self,
        history_manager: HistoryManager | None = None,
        query_rewriter: QueryRewriter | None = None,
        retriever: Retriever | None = None,
        context_builder: ContextBuilder | None = None,
        answer_generator: AnswerGenerator | None = None,
        citation_validator: CitationValidator | None = None,
    ):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.history_manager = history_manager or HistoryManager()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.retriever = retriever or Retriever()
        self.context_builder = context_builder or ContextBuilder()
        self.answer_generator = answer_generator or AnswerGenerator()
        self.citation_validator = citation_validator or CitationValidator()
        settings = get_settings()
        self.harness = ExecutionHarness(
            settings.rag_stage_timeout_seconds, settings.rag_max_retries
        )

    async def run(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
        learning_concept: str | None = None,
        incorrect_answer: str | None = None,
        stage_id: str | None = None,
        concept_id: str | None = None,
        request_id: str | None = None,
    ) -> RAGResult:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        if request_id:
            previous = await self.history_manager.find_turn_by_request_id(
                user_id, request_id
            )
            if previous is not None:
                return RAGResult(
                    conversation_id=previous.conversation_id,
                    answer=previous.answer,
                    citations=previous.citations,
                    rewritten_query=message,
                    retrieved_documents=[],
                    grounded=previous.grounded,
                )
        if conversation_id:
            history = await self.history_manager.load(conversation_id, user_id)
        else:
            history = await self.history_manager.create(user_id, stage_id, concept_id)

        result = await self._execute(
            conversation_id=history.conversation_id,
            message=message,
            history=history,
            learning_concept=learning_concept,
            incorrect_answer=incorrect_answer,
            stage_id=stage_id,
            concept_id=concept_id,
        )
        # Persist only after generation and validation completed. append_turn is
        # atomic, so a failed write cannot leave only one side of the exchange.
        persisted = await self.history_manager.append_turn(
            history.conversation_id,
            user_id,
            message,
            result.answer,
            request_id=request_id,
            sources=result.citations,
            grounded=result.grounded,
        )
        if persisted.answer != result.answer:
            result.answer = persisted.answer
            result.citations = persisted.citations
        result.conversation_id = persisted.conversation_id
        result.grounded = persisted.grounded
        return result

    async def run_external(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        history,
        learning_concept: str | None = None,
        incorrect_answer: str | None = None,
        stage_id: str | None = None,
        concept_id: str | None = None,
        concept_codes: list[str] | None = None,
        history_from_seq: int | None = None,
        personalized_context: PersonalizedTutorContext | None = None,
    ) -> RAGResult:
        """Run with Node.js-supplied context without touching conversation tables."""
        return await self._execute(
            conversation_id=conversation_id,
            message=message,
            history=history,
            learning_concept=learning_concept,
            incorrect_answer=incorrect_answer,
            stage_id=stage_id,
            concept_id=concept_id,
            concept_codes=concept_codes,
            history_from_seq=history_from_seq,
            personalized_context=personalized_context,
        )

    async def _execute(
        self,
        *,
        conversation_id: str,
        message: str,
        history,
        learning_concept: str | None,
        incorrect_answer: str | None,
        stage_id: str | None,
        concept_id: str | None,
        concept_codes: list[str] | None = None,
        history_from_seq: int | None = None,
        personalized_context: PersonalizedTutorContext | None = None,
    ) -> RAGResult:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        trace: list[dict[str, object]] = []
        rewritten_query = await self.harness.run(
            StageContract("query_rewriting", "question + bounded history", "query"),
            lambda: self.query_rewriter.rewrite(message, history),
            trace,
        )
        documents = await self.harness.run(
            StageContract("retrieval", "rewritten query + scope", "documents"),
            lambda: self.retriever.retrieve(
                rewritten_query,
                concept_id=concept_id,
                stage_id=stage_id,
                concept_codes=concept_codes,
            ),
            trace,
        )
        documents = await self.harness.run(
            StageContract(
                "related_retrieval", "retrieved documents + scope", "documents"
            ),
            lambda: self.retriever.retrieve_related(
                documents,
                concept_id=concept_id,
                stage_id=stage_id,
                concept_codes=concept_codes,
            ),
            trace,
        )
        if concept_codes:
            allowed_codes = set(concept_codes)
            documents = [
                document
                for document in documents
                if document.concept_code in allowed_codes
                or (document.knowledge_scope or "").casefold() == "global"
            ]
        context = self.context_builder.build(
            history=history,
            retrieved_context=documents,
            current_question=message,
            rewritten_query=rewritten_query,
            learning_concept=learning_concept,
            incorrect_answer=incorrect_answer,
            stage_id=stage_id,
            concept_id=concept_id,
            personalized_context=personalized_context,
        )
        trace.append(
            {
                "stage": "context",
                "status": "ok",
                "document_count": len(documents),
            }
        )
        if documents:
            answer = await self.harness.run(
                StageContract(
                    "answer_generation", "question + evidence context", "answer"
                ),
                lambda: self.answer_generator.generate(message, context),
                trace,
            )
        else:
            # A model must not improvise when retrieval found no approved evidence.
            answer = (
                "현재 확인된 학습자료가 없어 정확하게 설명하기 어려워요. "
                "질문과 관련된 학습자료를 먼저 확인해 주세요."
            )
        validation = self.citation_validator.validate_and_build(answer, documents)
        trace.append(
            {
                "stage": "groundedness_validation",
                "status": "ok" if validation.grounded else "insufficient",
                "citation_valid": validation.valid,
                "citation_count": len(validation.citations),
            }
        )
        if not validation.valid or not validation.grounded:
            # Remove unsupported reference markers. Identity validation cannot
            # prove facts, and an ungrounded answer must not reach the client.
            for reference in validation.unsupported_references:
                document_id, chunk_id = reference.split("/", maxsplit=1)
                pattern = re.compile(
                    rf"\[(?:출처|source)\s*:\s*{re.escape(document_id)}"
                    rf"/{re.escape(chunk_id)}\]",
                    re.IGNORECASE,
                )
                answer = pattern.sub("", answer)
            citations = validation.citations if validation.valid else []
            if documents:
                answer = (
                    "확인된 학습자료만으로는 이 질문에 대한 답변을 충분히 "
                    "검증하기 어려워요. 관련 자료를 더 확인한 뒤 다시 질문해 주세요."
                )
        else:
            citations = validation.citations
        return RAGResult(
            conversation_id=conversation_id,
            answer=answer,
            citations=citations,
            rewritten_query=rewritten_query,
            retrieved_documents=documents,
            grounded=validation.grounded,
            history_from_seq=history_from_seq,
            trace=trace,
        )
