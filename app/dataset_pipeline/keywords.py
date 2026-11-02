# 파일 역할: 경제·금융 데이터의 정규화, 청크, 키워드, 분류 전처리를 담당합니다.
"""Config-driven broad keyword candidate extraction."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.dataset_pipeline.chunks import Chunk


@dataclass(frozen=True, slots=True)
class Chapter:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    chapter_id: str
    chapter_name: str
    chapter_definition: str
    include_criteria: str
    exclude_criteria: str
    keywords: tuple[str, ...]
    related_keywords: tuple[str, ...]
    opposite_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    rubric_version: str
    aliases: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Chapter":
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        expansions = value.get("keyword_expansions") or {}
        return cls(
            chapter_id=str(value["chapter_id"]),
            chapter_name=str(value["chapter_name"]),
            chapter_definition=str(value.get("chapter_definition", "")),
            include_criteria=str(value.get("include_criteria", "")),
            exclude_criteria=str(value.get("exclude_criteria", "")),
            keywords=tuple(
                str(item) for item in value.get("keywords", expansions.get("core", []))
            ),
            related_keywords=tuple(
                str(item)
                for item in value.get("related_keywords", expansions.get("related", []))
            ),
            opposite_keywords=tuple(
                str(item)
                for item in value.get(
                    "opposite_keywords", expansions.get("opposite", [])
                )
            ),
            exclude_keywords=tuple(
                str(item) for item in value.get("exclude_keywords", [])
            ),
            rubric_version=str(value.get("rubric_version", "draft-v1")),
            aliases=tuple(
                str(item)
                for item in value.get("aliases", expansions.get("aliases", []))
            ),
        )

    @property
    def all_keywords(self) -> tuple[str, ...]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return tuple(
            dict.fromkeys(
                [*self.keywords, *self.related_keywords, *self.opposite_keywords]
            )
        )

    @property
    def keyword_groups(self) -> dict[str, tuple[str, ...]]:
        """Return groups used for candidate recall without treating them as labels."""
        return {
            "core": self.keywords,
            "alias": self.aliases,
            "related": self.related_keywords,
            "opposite": self.opposite_keywords,
        }


def normalize_keyword(value: str) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return re.sub(r"\s+", "", value.casefold())


def _evidence(content: str, keyword: str) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    for sentence in re.split(r"(?<=[.!?다요])\s+|\n+", content):
        if normalize_keyword(keyword) in normalize_keyword(sentence):
            return sentence.strip()[:300]
    return content.strip()[:300]


def classify_chunk_by_keywords(chunk: Chunk, chapter: Chapter) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    normalized_content = normalize_keyword(f"{chunk.title} {chunk.content}")
    weights = {"core": 1.0, "alias": 0.85, "related": 0.55, "opposite": 0.35}
    matched_details: list[dict[str, Any]] = []
    for keyword_type, keywords in chapter.keyword_groups.items():
        for keyword in keywords:
            if normalize_keyword(keyword) in normalized_content:
                matched_details.append(
                    {
                        "keyword": keyword,
                        "keyword_type": keyword_type,
                        "weight": weights[keyword_type],
                    }
                )
    unique_details: list[dict[str, Any]] = []
    seen_keywords: set[str] = set()
    for detail in matched_details:
        normalized = normalize_keyword(detail["keyword"])
        if normalized not in seen_keywords:
            seen_keywords.add(normalized)
            unique_details.append(detail)
    matched = [detail["keyword"] for detail in unique_details]
    exclusions = [
        keyword
        for keyword in chapter.exclude_keywords
        if normalize_keyword(keyword) in normalized_content
    ]
    signal = sum(float(detail["weight"]) for detail in unique_details)
    score = min(1.0, 0.2 + 0.1 * signal) if matched else 0.0
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "chapter_id": chapter.chapter_id,
        "chapter_name": chapter.chapter_name,
        "keyword_matched": bool(matched),
        "candidate": bool(matched),
        "keyword_match_score": round(score, 4),
        "keyword_score_is_not_relevance": True,
        "keyword_strategy": "weighted_broad_candidate_filter",
        "matched_keywords": matched,
        "matched_keyword_details": unique_details,
        "matched_keyword_types": sorted(
            {detail["keyword_type"] for detail in unique_details}
        ),
        "exclude_keyword_matches": exclusions,
        "evidence_span": _evidence(chunk.content, matched[0]) if matched else None,
        "review_status": "PENDING",
        "source": chunk.source,
        "source_url": chunk.source_url,
        "source_locator": chunk.source_locator,
        "text_hash": chunk.text_hash,
        "rubric_version": chapter.rubric_version,
    }


def keyword_candidates(
    chunks: list[Chunk], chapters: list[Chapter]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    rows: list[dict[str, Any]] = []
    per_chapter: dict[str, int] = Counter()
    matching_chunk_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for chapter in chapters:
        for chunk in chunks:
            pair = (chapter.chapter_id, chunk.chunk_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            row = classify_chunk_by_keywords(chunk, chapter)
            if row["candidate"]:
                rows.append(row)
                per_chapter[chapter.chapter_id] += 1
                matching_chunk_ids.add(chunk.chunk_id)
    return rows, {
        "total_chunks": len(chunks),
        "candidate_rows": len(rows),
        "candidate_chunk_count": len(matching_chunk_ids),
        "candidate_chunk_rate": len(matching_chunk_ids) / len(chunks) if chunks else 0,
        "candidate_count_by_chapter": dict(per_chapter),
        "chapter_count": len(chapters),
        "keyword_is_candidate_generator": True,
        "unmatched_chunks_are_not_deleted": True,
    }


def sample_unmatched(
    chunks: list[Chunk], candidates: list[dict[str, Any]], sample_size: int = 100
) -> list[dict[str, Any]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    matched_ids = {row["chunk_id"] for row in candidates}
    unmatched = [chunk for chunk in chunks if chunk.chunk_id not in matched_ids]
    ordered = sorted(
        unmatched,
        key=lambda chunk: hashlib.sha256(chunk.chunk_id.encode("utf-8")).hexdigest(),
    )
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source": chunk.source,
            "title": chunk.title,
            "content": chunk.content,
            "review_status": "PENDING",
            "sampling_method": "stable_hash_unmatched_sample",
        }
        for chunk in ordered[:sample_size]
    ]
