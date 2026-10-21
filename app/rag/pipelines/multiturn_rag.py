from __future__ import annotations

from dataclasses import dataclass

from app.rag.grounding.citation_validator import CitationValidator
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import HistoryManager
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import Retriever
from app.rag.retrieval.types import RetrievedDocument


@dataclass(slots=True)
class RAGResult:
    conversation_id: str
    answer: str
    citations: list[RetrievedDocument]
    rewritten_query: str
    retrieved_documents: list[RetrievedDocument]


class MultiTurnRAG:
    def __init__(
        self,
        history_manager: HistoryManager | None = None,
        query_rewriter: QueryRewriter | None = None,
        retriever: Retriever | None = None,
        context_builder: ContextBuilder | None = None,
        answer_generator: AnswerGenerator | None = None,
        citation_validator: CitationValidator | None = None,
    ):
        self.history_manager = history_manager or HistoryManager()
        self.query_rewriter = query_rewriter or QueryRewriter()
        self.retriever = retriever or Retriever()
        self.context_builder = context_builder or ContextBuilder()
        self.answer_generator = answer_generator or AnswerGenerator()
        self.citation_validator = citation_validator or CitationValidator()

    async def run(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
        learning_concept: str | None = None,
        incorrect_answer: str | None = None,
    ) -> RAGResult:
        if conversation_id:
            history = await self.history_manager.load(conversation_id, user_id)
        else:
            history = await self.history_manager.create(user_id)

        rewritten_query = await self.query_rewriter.rewrite(message, history)
        documents = await self.retriever.retrieve(rewritten_query)
        context = self.context_builder.build(
            history=history,
            retrieved_context=documents,
            current_question=message,
            rewritten_query=rewritten_query,
            learning_concept=learning_concept,
            incorrect_answer=incorrect_answer,
        )
        if documents:
            answer = await self.answer_generator.generate(rewritten_query, context)
        else:
            # A model must not improvise when retrieval found no approved evidence.
            answer = "현재 확인된 학습자료가 없어 정확하게 설명하기 어려워요. 질문과 관련된 학습자료를 먼저 확인해 주세요."
        validation = self.citation_validator.validate_and_build(answer, documents)
        if not validation.valid:
            # Remove unsupported reference markers. Identity validation cannot
            # prove facts, but an unknown citation must not reach the client.
            for reference in validation.unsupported_references:
                document_id, chunk_id = reference.split("/", maxsplit=1)
                answer = answer.replace(f"[출처: {document_id}/{chunk_id}]", "")
                answer = answer.replace(f"[source: {document_id}/{chunk_id}]", "")
            citations = []
        else:
            citations = validation.citations

        # Persist only after generation and validation completed. append_turn is
        # atomic, so a failed write cannot leave only one side of the exchange.
        await self.history_manager.append_turn(history.conversation_id, user_id, message, answer)
        return RAGResult(
            conversation_id=history.conversation_id,
            answer=answer,
            citations=citations,
            rewritten_query=rewritten_query,
            retrieved_documents=documents,
        )
