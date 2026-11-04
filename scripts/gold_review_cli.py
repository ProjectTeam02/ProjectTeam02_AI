"""Run the local, human-first Gold Set review tool.

기본 사용 예:

    .venv/bin/python scripts/gold_review_cli.py --reviewer-id jihoon

검수자는 제목과 원문만 보고 0·1·2·NEEDS_REVIEW를 입력합니다. 기존 AI
예측과 기존 Excel 라벨은 화면에 표시하지 않습니다. 결과는 원본 템플릿이
아닌 로컬 append-only JSONL에 저장됩니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 모듈 상수는 실행 경로와 무관하게 프로젝트 기준으로 고정합니다.
from app.dataset_pipeline import gold_review  # noqa: E402

DEFAULT_QUEUE = ROOT / "data/labeled/precision/independent_gold_review_queue.csv"
# Legacy template paths remain available only when explicitly supplied. They are
# not the current 320-document review population.
DEFAULT_KDI = ROOT / "reports/step3/kdi_independent_gold_review_template.csv"
DEFAULT_BOK = ROOT / "reports/step3/bok_independent_gold_review_template.csv"
DEFAULT_HISTORY = ROOT / "data/labeled/precision/gold_review_history.jsonl"
DEFAULT_EXPORT_CSV = ROOT / "data/labeled/precision/gold_review_current.csv"
DEFAULT_EXPORT_JSONL = ROOT / "data/labeled/precision/gold_review_current.jsonl"
DEFAULT_STATUS = ROOT / "reports/gold_review_validation.json"
DEFAULT_DISAGREEMENTS = ROOT / "reports/gold_review_disagreements.json"
DEFAULT_RUBRIC = "inflation-rubric-draft-v1"
CHAPTER_GUIDE = (
    "챕터: 인플레이션(C0704)\n"
    "2점: 인플레이션의 정의·측정·원인·영향·대응 정책 또는 디플레이션 비교를 "
    "본문이 직접 설명하는 경우\n"
    "1점: 금리·통화량·환율처럼 인플레이션 이해에 도움이 되는 배경 개념이지만 "
    "핵심 설명은 아닌 경우\n"
    "0점: 챕터 학습 내용과 직접적인 관련이 없는 경우\n"
    "판단 보류: 원문 부족·오류·의미 불명확으로 점수를 확정하기 어려운 경우"
)


def _print_progress(progress: dict[str, Any]) -> None:
    print(
        "진행률: "
        f"{progress['reviewed_document_count']}/{progress['template_count']}건 검수, "
        f"최종 합의 {progress['adjudicated_document_count']}건"
    )
    print(f"기관별 전체: {progress['source_counts']}")
    print(f"기관별 검수: {progress['reviewed_source_counts']}")
    print(f"현재 라벨 분포: {progress['label_counts']}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_review_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    """Load the canonical 320-row queue unless legacy inputs are explicit."""
    queue_path = getattr(args, "queue", None)
    if queue_path is not None:
        rows = gold_review.load_template_rows([queue_path])
        for row in rows:
            # Older locally generated queues did not contain all reviewer
            # lineage fields. Fill only structural defaults; never copy labels.
            row["source"] = row.get("source") or row.get("source_group", "")
            row["source_group"] = row.get("source_group") or row["source"]
            row["chunk_id"] = row.get("chunk_id") or (
                f"LABELING_XLSX:{row.get('document_id', '')}:chunk-0000"
            )
            row["chapter_id"] = row.get("chapter_id") or "inflation"
            row["dataset_version"] = (
                row.get("dataset_version") or "labeling-xlsx-current"
            )
            row["rubric_version"] = (
                row.get("rubric_version") or DEFAULT_RUBRIC
            )
            row["sampling_bucket"] = row.get("sampling_bucket") or row.get(
                "sampling_stratum", ""
            )
        return rows
    return gold_review.load_template_rows([args.kdi, args.bok])


def _display_document(row: dict[str, str], index: int, total: int) -> None:
    """Display only source content and stable lineage needed for human review."""
    print("\n" + "=" * 80)
    print(
        f"문서 {index + 1}/{total} | {row.get('source', '')} | "
        f"{row.get('document_id', '')}"
    )
    print(f"제목: {row.get('title', '')}")
    print(f"청크 ID: {row.get('chunk_id', '')}")
    print(f"분할: {row.get('split', '')}")
    print("\n[원문]")
    print(row.get("content", ""))
    print("\n[판정 기준]")
    print(CHAPTER_GUIDE)
    print("입력: 0 / 1 / 2 / r(NEEDS_REVIEW)")
    print("기존 AI 예측·기존 라벨·키워드 매칭 결과는 표시하지 않습니다.")


def _prompt_review(row: dict[str, str]) -> tuple[str, str, str, str, str, str] | str:
    answer = input(
        "\n라벨 입력 [0/1/2/r=NEEDS_REVIEW, n=다음, p=이전, q=종료]: "
    ).strip()
    command = answer.casefold()
    if command in {"n", "p", "q"}:
        return command
    label = "NEEDS_REVIEW" if command in {"r", "needs_review"} else answer
    if label not in {"0", "1", "2", "NEEDS_REVIEW"}:
        print("잘못된 라벨입니다. 0, 1, 2, r 중 하나를 입력하세요.")
        return "invalid"
    reason = input("판정 이유(필수): ").strip()
    evidence = input("원문 근거 문장(NEEDS_REVIEW는 선택): ").strip()
    print("별도 승인 상태: PENDING / APPROVED / REJECTED / NEEDS_REVIEW")
    source_status = input("출처 검토 상태(빈칸=PENDING): ").strip() or "PENDING"
    license_status = input("라이선스 검토 상태(빈칸=PENDING): ").strip() or "PENDING"
    quiz_status = input("문제 생성 적합성(빈칸=PENDING): ").strip() or "PENDING"
    return label, evidence, reason, source_status, license_status, quiz_status


def _save_review(
    row: dict[str, str],
    reviewer_id: str,
    label: str,
    evidence: str,
    reason: str,
    history_path: Path,
    rubric_version: str,
    events: list[dict[str, Any]],
    source_status: str = "PENDING",
    license_status: str = "PENDING",
    quiz_status: str = "PENDING",
) -> None:
    event = gold_review.create_review_event(
        row,
        reviewer_id,
        label,
        evidence,
        reason,
        rubric_version,
        source_status,
        license_status,
        quiz_status,
    )
    gold_review.append_event(history_path, event)
    events.append(event)
    print("저장했습니다. 검수 이력은 기존 값을 덮어쓰지 않고 새 이벤트로 추가했습니다.")


def _review_loop(
    rows: list[dict[str, str]],
    reviewer_id: str,
    history_path: Path,
    rubric_version: str,
    events: list[dict[str, Any]],
    include_reviewed: bool,
) -> None:
    latest = gold_review.latest_reviewer_events(events)
    reviewed_by_user = {
        document_id for document_id, reviewer in latest if reviewer == reviewer_id
    }
    queue = (
        rows
        if include_reviewed
        else [row for row in rows if row.get("document_id") not in reviewed_by_user]
    )
    if not queue:
        print(
            "현재 평가자에게 남은 미검수 문서가 없습니다. "
            "--include-reviewed를 사용하면 수정할 수 있습니다."
        )
        return
    index = 0
    while queue:
        index = max(0, min(index, len(queue) - 1))
        _display_document(queue[index], index, len(queue))
        result = _prompt_review(queue[index])
        if result == "q":
            break
        if result == "n":
            index = min(index + 1, len(queue) - 1)
            continue
        if result == "p":
            index = max(index - 1, 0)
            continue
        if result == "invalid":
            continue
        label, evidence, reason, source_status, license_status, quiz_status = result
        try:
            _save_review(
                queue[index],
                reviewer_id,
                label,
                evidence,
                reason,
                history_path,
                rubric_version,
                events,
                source_status,
                license_status,
                quiz_status,
            )
        except ValueError as error:
            print(f"저장 실패: {error}")
            continue
        index = min(index + 1, len(queue) - 1)


def _adjudication_loop(
    rows: list[dict[str, str]],
    reviewer_id: str,
    history_path: Path,
    events: list[dict[str, Any]],
) -> None:
    latest = gold_review.latest_reviewer_events(events)
    adjudicated = gold_review.latest_adjudications(events)
    by_document: dict[str, list[dict[str, Any]]] = {}
    for (document_id, _), event in latest.items():
        if event.get("review_status") == "SINGLE_REVIEWED":
            by_document.setdefault(document_id, []).append(event)
    candidates = [
        row
        for row in rows
        if len(
            {
                event.get("reviewer_id")
                for event in by_document.get(row.get("document_id"), [])
            }
        )
        >= 2
        and row.get("document_id") not in adjudicated
    ]
    if not candidates:
        print("2인 이상 독립 검수가 끝났고 아직 합의되지 않은 문서가 없습니다.")
        return
    print(f"합의 대기 문서: {len(candidates)}건")
    for index, row in enumerate(candidates):
        print(
            f"[{index}] {row.get('source')} {row.get('document_id')} {row.get('title')}"
        )
    selected = input("합의할 번호 또는 document_id (q=종료): ").strip()
    if selected.casefold() == "q":
        return
    if selected.isdigit() and int(selected) < len(candidates):
        row = candidates[int(selected)]
    else:
        row = next(
            (item for item in candidates if item.get("document_id") == selected), None
        )
    if row is None:
        print("문서를 찾지 못했습니다.")
        return
    _display_document(row, 0, 1)
    label = input("최종 합의 점수 [0/1/2]: ").strip()
    evidence = input("최종 근거 문장(원문에 있는 문장, 필수): ").strip()
    reason = input("합의 근거(필수): ").strip()
    mode = input("검수 방식 [1=ADJUDICATED_CONSENSUS, 2=THIRD_PARTY_REVIEW]: ").strip()
    review_mode = "ADJUDICATED_CONSENSUS" if mode == "1" else "THIRD_PARTY_REVIEW"
    reviewers = {
        event.get("reviewer_id")
        for event in by_document.get(row.get("document_id"), [])
    }
    try:
        event = gold_review.create_adjudication_event(
            row,
            reviewer_id,
            label,
            evidence,
            reason,
            len(reviewers),
            review_mode,
            events,
        )
        gold_review.append_event(history_path, event)
        events.append(event)
        print("최종 합의 결과를 저장했습니다.")
    except ValueError as error:
        print(f"합의 결과 저장 실패: {error}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    all_rows = _load_review_rows(args)
    rows = list(all_rows)
    if args.source != "ALL":
        rows = [row for row in rows if row.get("source") == args.source]
    if args.split != "ALL":
        rows = [row for row in rows if row.get("split") == args.split]
    if args.document_id:
        rows = [row for row in rows if row.get("document_id") == args.document_id]
    events = gold_review.load_history(args.history)
    progress = gold_review.progress_summary(rows, events)
    _print_progress(progress)
    if args.validate_only:
        # 기관·split 필터는 화면 범위에만 적용하고 전체 큐를 검증합니다.
        validation = gold_review.validate_history(all_rows, events)
        disagreements = gold_review.disagreement_report(all_rows, events)
        _write_json(args.disagreements, disagreements)
        result = {
            **validation,
            "progress": progress,
            "disagreements": disagreements,
        }
        _write_json(args.status, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    if args.adjudicate:
        _adjudication_loop(rows, args.reviewer_id, args.history, events)
    else:
        _review_loop(
            rows,
            args.reviewer_id,
            args.history,
            args.rubric_version,
            events,
            args.include_reviewed,
        )
    export = gold_review.export_current_reviews(
        rows,
        events,
        args.export_csv,
        args.export_jsonl,
    )
    validation = gold_review.validate_history(all_rows, events)
    disagreements = gold_review.disagreement_report(all_rows, events)
    _write_json(args.disagreements, disagreements)
    _write_json(
        args.status,
        {
            "progress": gold_review.progress_summary(all_rows, events),
            "validation": validation,
            "disagreements": disagreements,
            "export": export,
        },
    )
    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--source", choices=["KDI", "BOK", "ALL"], default="ALL")
    parser.add_argument(
        "--split", choices=["development", "test", "ALL"], default="ALL"
    )
    parser.add_argument("--document-id")
    parser.add_argument("--adjudicate", action="store_true")
    parser.add_argument("--include-reviewed", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--rubric-version", default=DEFAULT_RUBRIC)
    parser.add_argument(
        "--queue",
        type=Path,
        default=DEFAULT_QUEUE,
        help="현재 KDI 160+BOK 160 독립 Gold 검수 큐(기본값).",
    )
    parser.add_argument(
        "--kdi",
        type=Path,
        default=None,
        help="레거시 템플릿을 명시적으로 검증할 때만 사용합니다.",
    )
    parser.add_argument(
        "--bok",
        type=Path,
        default=None,
        help="레거시 템플릿을 명시적으로 검증할 때만 사용합니다.",
    )
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--export-csv", type=Path, default=DEFAULT_EXPORT_CSV)
    parser.add_argument("--export-jsonl", type=Path, default=DEFAULT_EXPORT_JSONL)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--disagreements", type=Path, default=DEFAULT_DISAGREEMENTS)
    args = parser.parse_args()
    if args.kdi is not None or args.bok is not None:
        if args.kdi is None or args.bok is None:
            parser.error("--kdi와 --bok는 레거시 템플릿 검증 시 함께 지정해야 합니다.")
        args.queue = None
    run(args)


if __name__ == "__main__":
    main()
