"""JSONL input and resumable result persistence."""

from __future__ import annotations

import json
from pathlib import Path

from app.model_comparison.contracts import ComparisonCase, ComparisonResult


def load_cases(path: str | Path) -> list[ComparisonCase]:
    input_path = Path(path)
    cases: list[ComparisonCase] = []
    seen: set[str] = set()
    with input_path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {input_path}:{line_number}: {exc.msg}"
                ) from exc
            case = ComparisonCase.from_dict(payload, line_number)
            if case.case_id in seen:
                raise ValueError(f"duplicate case_id: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    return cases


class JsonlResultStore:
    """Append-only result store that supports safe process restarts."""

    COMPLETED_STATUSES = {"ok", "mock", "smoke_ok", "no_evidence"}

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records: dict[tuple[str, str, str], dict] = {}
        if self.path.exists():
            self._load_existing()

    def is_completed(self, case_id: str, model_id: str, mode: str) -> bool:
        record = self._records.get((case_id, model_id, mode))
        return bool(record and record.get("status") in self.COMPLETED_STATUSES)

    def append(self, result: ComparisonResult | dict) -> None:
        record = result.as_dict() if isinstance(result, ComparisonResult) else result
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()
        key = (record["case_id"], record["model_id"], record["mode"])
        self._records[key] = record

    def _load_existing(self) -> None:
        with self.path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid result JSONL at {self.path}:{line_number}"
                    ) from exc
                required = ("case_id", "model_id", "mode", "status")
                if not all(key in record for key in required):
                    raise ValueError(
                        f"result JSONL at {self.path}:{line_number} has an invalid row"
                    )
                key = (record["case_id"], record["model_id"], record["mode"])
                self._records[key] = record


def write_template(path: str | Path, count: int = 100) -> None:
    """Write a fillable 100-case template without overwriting an existing file."""

    if count <= 0:
        raise ValueError("template count must be greater than zero")
    template_path = Path(path)
    if template_path.exists():
        raise FileExistsError(template_path)
    template_path.parent.mkdir(parents=True, exist_ok=True)
    with template_path.open("w", encoding="utf-8") as handle:
        for index in range(1, count + 1):
            row = {
                "case_id": f"TUTOR-{index:03d}",
                "question": "검수된 경제·금융 튜터 질문을 입력하세요.",
                "history": [],
                "corpus": [],
                "gold": {
                    "answer": None,
                    "required_concepts": [],
                    "forbidden_claims": [],
                    "review_status": "NOT_REVIEWED",
                },
            }
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
