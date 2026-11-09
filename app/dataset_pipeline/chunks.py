# 파일 역할: 경제·금융 데이터의 정규화, 청크, 키워드, 분류 전처리를 담당합니다.
"""Paragraph-first token-aware chunking with source lineage metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any

from app.dataset_pipeline.io import NormalizedDocument
from app.dataset_pipeline.tokenizer import ExactTokenizer


@dataclass(frozen=True, slots=True)
class Chunk:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    document_id: str
    chunk_id: str
    source: str
    title: str
    content: str
    source_url: str | None
    source_locator: str | None
    chunk_index: int
    token_count: int
    text_hash: str
    dataset_version: str
    source_review_status: str
    license_status: str

    def as_dict(self) -> dict[str, Any]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return asdict(self)


def clean_text(text: str) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def paragraphs(text: str) -> list[str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    normalized = clean_text(text)
    units = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    return units or [normalized]


def _split_long_unit(
    unit: str, tokenizer: ExactTokenizer, max_tokens: int
) -> list[str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    tokens = tokenizer.encode(unit)
    result: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        text = tokenizer.decode(tokens[start:end]).strip()
        while text and tokenizer.count(text) > max_tokens and end > start + 1:
            end -= 1
            text = tokenizer.decode(tokens[start:end]).strip()
        if text:
            result.append(text)
        start = end
    return result


def _units_for_document(
    document: NormalizedDocument, tokenizer: ExactTokenizer, max_tokens: int
) -> list[str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    result: list[str] = []
    for unit in paragraphs(document.content):
        if tokenizer.count(unit) <= max_tokens:
            result.append(unit)
        else:
            result.extend(_split_long_unit(unit, tokenizer, max_tokens))
    return result


def chunk_document(
    document: NormalizedDocument,
    tokenizer: ExactTokenizer,
    dataset_version: str,
    max_tokens: int = 700,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("chunk size must be positive and overlap smaller than size")
    units = _units_for_document(document, tokenizer, max_tokens)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = tokenizer.count(unit)
        if current and current_tokens + unit_tokens + 1 > max_tokens:
            chunks.append("\n\n".join(current).strip())
            overlap: list[str] = []
            overlap_count = 0
            for previous in reversed(current):
                previous_tokens = tokenizer.count(previous)
                if overlap_count + previous_tokens > overlap_tokens:
                    break
                overlap.insert(0, previous)
                overlap_count += previous_tokens
            current = overlap
            current_tokens = overlap_count
        current.append(unit)
        current_tokens += unit_tokens + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n\n".join(current).strip())

    result: list[Chunk] = []
    for index, content in enumerate(chunks):
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result.append(
            Chunk(
                document_id=document.document_id,
                chunk_id=f"{document.source}:{document.document_id}:chunk-{index:04d}",
                source=document.source,
                title=document.title,
                content=content,
                source_url=document.source_url,
                source_locator=document.source_locator,
                chunk_index=index,
                token_count=tokenizer.count(content),
                text_hash=content_hash,
                dataset_version=dataset_version,
                source_review_status=document.source_review_status,
                license_status=document.license_status,
            )
        )
    return result


def make_chunks(
    documents: list[NormalizedDocument],
    tokenizer: ExactTokenizer,
    dataset_version: str,
    max_tokens: int = 700,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(
            chunk_document(
                document,
                tokenizer,
                dataset_version,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
        )
    return chunks
