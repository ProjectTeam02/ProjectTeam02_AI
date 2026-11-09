# 파일 역할: 경제·금융 데이터의 정규화, 청크, 키워드, 분류 전처리를 담당합니다.
"""Exact token counting used by the dataset pipeline."""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import median
from typing import Any


class ExactTokenizer:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    def __init__(self, model_alias: str = "gpt-4o-mini") -> None:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        try:
            import tiktoken

            try:
                self.encoding = tiktoken.encoding_for_model(model_alias)
            except KeyError:
                self.encoding = tiktoken.get_encoding("o200k_base")
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken is required for exact token metrics; install requirements"
            ) from exc
        self.model_alias = model_alias
        self.encoding_name = self.encoding.name

    def encode(self, text: str) -> list[int]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return self.encoding.encode(text, disallowed_special=())

    def decode(self, tokens: Iterable[int]) -> str:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return self.encoding.decode(list(tokens))

    def count(self, text: str) -> int:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return len(self.encode(text))


def percentile(values: list[int], fraction: float) -> float | None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def summarize(values: Iterable[int]) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    numbers = list(values)
    if not numbers:
        return {
            "count": 0,
            "total": 0,
            "average": None,
            "median": None,
            "min": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "max": None,
        }
    return {
        "count": len(numbers),
        "total": sum(numbers),
        "average": sum(numbers) / len(numbers),
        "median": median(numbers),
        "min": min(numbers),
        "p25": percentile(numbers, 0.25),
        "p75": percentile(numbers, 0.75),
        "p95": percentile(numbers, 0.95),
        "max": max(numbers),
    }
