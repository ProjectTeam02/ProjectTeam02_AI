"""Gold 검수 준비 키트 CLI (사람 검수 준비 전용, 승인 값을 만들지 않음).

하위 명령:
    assign      이중 검수 배정 시트 (KDI/BOK 320 + 튜터 100)
    draft-map   튜터 100건 conceptCode·approvedEvidence 후보 초안 (DRAFT)
    agreement   이중 검수 불일치·Cohen's kappa 리포트
    audit-gaps  개념·출처·선수관계·BOK 문서 검수자/검수일/라이선스 공백 목록
    evaluate    승인 후 Keyword/LLM/Hybrid Precision·Recall·F1 원커맨드
                (승인 0건 또는 미완료면 NOT_READY, 종료코드 2)

예:
    .venv/bin/python scripts/gold_review_kit.py assign --reviewer 김OO --reviewer 이OO
    .venv/bin/python scripts/gold_review_kit.py evaluate
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation import gold_review_kit as kit  # noqa: E402

NOT_READY_EXIT = 2

PRECISION_QUEUE = "labeled/precision/independent_gold_review_queue.csv"
PRECISION_HISTORY = "labeled/precision/gold_review_history.jsonl"
TUTOR_CASES = "evaluation/tutor_test_100.jsonl"
TUTOR_HISTORY = "evaluation/tutor_gold_review_events.jsonl"


def _read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding))))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: UTF-8/CP949로 읽을 수 없습니다.")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _assignment_items(data_dir: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    queue = data_dir / PRECISION_QUEUE
    if queue.is_file():
        for row in _read_csv(queue):
            items.append(
                {
                    "dataset": "PRECISION_320",
                    "item_id": row.get("document_id", ""),
                    "source": row.get("source", ""),
                    "split": row.get("split", ""),
                    "title": row.get("title", ""),
                    "review_tool": "scripts/gold_review_cli.py --document-id",
                }
            )
    cases = data_dir / TUTOR_CASES
    for case in _read_jsonl(cases):
        items.append(
            {
                "dataset": "TUTOR_100",
                "item_id": case.get("caseId", ""),
                "source": ",".join(case.get("sourceIds") or []),
                "split": "",
                "title": ",".join(case.get("expectedConcepts") or []),
                "review_tool": (
                    "scripts/tutor_gold_workflow.py --record-review --case-id"
                ),
            }
        )
    return items


def cmd_assign(args: argparse.Namespace) -> int:
    items = _assignment_items(args.data_dir)
    if not items:
        print(f"배정할 항목이 없습니다: {args.data_dir}", file=sys.stderr)
        return 1
    rows = kit.build_assignment_rows(items, args.reviewer or kit.DEFAULT_REVIEWERS)
    _write_csv(args.output, kit.ASSIGNMENT_FIELDS, rows)
    summary = {
        "assignment_csv": str(args.output),
        "item_count": len(rows),
        "reviewers_are_placeholders": not args.reviewer,
        "workload": kit.reviewer_workload(rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_draft_map(args: argparse.Namespace) -> int:
    cases = _read_jsonl(args.data_dir / TUTOR_CASES)
    concepts = json.loads((args.data_dir / args.concepts).read_text(encoding="utf-8"))
    concept_rows = (
        concepts.get("concepts", concepts) if isinstance(concepts, dict) else concepts
    )
    sources_path = args.data_dir / args.concept_sources
    sources = _read_csv(sources_path) if sources_path.is_file() else []
    drafts = kit.draft_concept_evidence_map(cases, concept_rows, sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in drafts),
        encoding="utf-8",
    )
    with_candidate = sum(1 for row in drafts if row["conceptCodeCandidates"])
    print(
        json.dumps(
            {
                "draft_jsonl": str(args.output),
                "case_count": len(drafts),
                "cases_with_concept_candidate": with_candidate,
                "cases_without_candidate": len(drafts) - with_candidate,
                "mapping_status": kit.DRAFT_STATUS,
                "gold_file_modified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_agreement(args: argparse.Namespace) -> int:
    reports = {}
    for kind, history, assigned in (
        (
            "precision",
            args.data_dir / PRECISION_HISTORY,
            args.data_dir / PRECISION_QUEUE,
        ),
        ("tutor", args.data_dir / TUTOR_HISTORY, args.data_dir / TUTOR_CASES),
    ):
        if kind == "precision":
            ids = (
                [r["document_id"] for r in _read_csv(assigned)]
                if assigned.is_file()
                else []
            )
        else:
            ids = [c.get("caseId", "") for c in _read_jsonl(assigned)]
        labels = kit.latest_labels(_read_jsonl(history), kind)
        report = kit.agreement_report(labels, ids)
        report["history_path"] = str(history)
        report["history_exists"] = history.is_file()
        reports[kind] = report
    _write_json(args.output, reports)
    print(
        json.dumps(
            {
                kind: {
                    key: report[key]
                    for key in (
                        "history_exists",
                        "reviewed_item_count",
                        "double_reviewed_item_count",
                        "not_started_count",
                        "disagreement_count",
                        "pairs",
                    )
                }
                for kind, report in reports.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"전체 리포트: {args.output}")
    return 0


GAP_SQL = """-- RDS에서 실제 승인 이력을 확인할 때 (읽기 전용, ai_user 또는 app_user)
SELECT source_id, review_status, license_review_status,
       (license IS NOT NULL) AS has_license, count(*)
FROM ai.rag_documents GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;
SELECT concept_code, version, status, reviewed_by, reviewed_at
FROM content.concepts WHERE reviewed_by IS NULL OR reviewed_at IS NULL;"""


def _gap_markdown(summary: dict[str, dict[str, int]], counts: dict[str, int]) -> str:
    lines = [
        "# 큐레이션 검수 공백 목록",
        "",
        "자동 생성: `scripts/gold_review_kit.py audit-gaps`. 이 문서는 공백을 *나열*만",
        "하며 어떤 항목도 승인하지 않습니다. CSV의 `approve=Y`, `decision=APPROVED`",
        "표시는 DB 승인 이력(검수자·검수일)이 아니므로 공백으로 집계합니다.",
        "행 단위 CSV는 저장소 정책(`reports/**/*.csv` 제외)에 따라",
        "로컬에만 생성됩니다.",
        "",
        "## 입력 건수",
        "",
        "| 자산 | 건수 |",
        "| --- | ---: |",
    ]
    lines += [f"| {name} | {count} |" for name, count in counts.items()]
    lines += [
        "",
        "## 공백 요약",
        "",
        "| 자산 | 공백 행 | 누락 필드별 건수 |",
        "| --- | ---: | --- |",
    ]
    for asset, fields in summary.items():
        detail = ", ".join(
            f"{field} {count}"
            for field, count in fields.items()
            if field != "rows_with_gap"
        )
        lines.append(f"| {asset} | {fields.get('rows_with_gap', 0)} | {detail} |")
    lines += [
        "",
        "## 사람이 할 일",
        "",
        "- 콘텐츠 검수 담당: 개념 29건의 `reviewed_by`·`reviewed_at` 기록,"
        " 근거 문서 없는 개념 연결 결정.",
        "- 데이터 담당: 개념–출처 후보의 검수자·검수일과"
        " `license_review_status`를 DB에 적재"
        " (`database/sql/data/load_concept_source_documents.sql`).",
        "- 데이터 담당: 선수관계 26건의 CSV 결정을 검수자·검수일과 함께"
        " DB에 반영"
        " (`database/sql/data/load_concept_prerequisite_review.sql`).",
        "- 라이선스 승인권자: 한국은행 「경제금융용어 800선」·KDI 용어사전"
        " 이용 조건 확인 후"
        " `ai.rag_documents.license_review_status` UPDATE.",
        "",
        "## RDS 확인 쿼리",
        "",
        "로컬 파일에는 RDS의 실제 승인 이력이 없으므로 최종 확인은 아래 쿼리로 합니다.",
        "",
        "```sql",
        GAP_SQL,
        "```",
        "",
    ]
    return "\n".join(lines)


def cmd_audit_gaps(args: argparse.Namespace) -> int:
    data = args.data_dir
    concepts_doc = json.loads((data / args.concepts).read_text(encoding="utf-8"))
    concepts = concepts_doc.get("concepts", concepts_doc)
    sources = _read_csv(data / args.concept_sources)
    prerequisites = _read_csv(data / args.prerequisites)
    documents = _read_csv(data / args.documents)
    status = {
        row.get("document_id", ""): row
        for row in _read_jsonl(data / args.normalized)
        if row.get("source") == "BOK"
    }
    gaps = kit.curation_gaps(concepts, sources, prerequisites, documents, status)
    summary = kit.summarize_gaps(gaps)
    counts = {
        "개념 (CONCEPT)": len(concepts),
        "개념–출처 후보 행 (CONCEPT_SOURCE)": len(sources),
        "  └ approve=Y 표시": sum(
            1 for r in sources if r.get("approve", "").upper() == "Y"
        ),
        "선수관계 (PREREQUISITE)": len(prerequisites),
        "BOK 문서 (BOK_DOCUMENT)": len(documents),
    }
    _write_csv(args.output_csv, kit.GAP_FIELDS, gaps)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(_gap_markdown(summary, counts), encoding="utf-8")
    print(
        json.dumps({"counts": counts, "summary": summary}, ensure_ascii=False, indent=2)
    )
    print(f"CSV: {args.output_csv}\n요약: {args.output_md}")
    return 0


def _approved_count(rows: list[dict[str, str]]) -> int:
    return sum(
        1 for row in rows if row.get("gold_set_status") == "INDEPENDENT_APPROVED"
    )


def _metric_table(result: dict[str, Any], threshold: float) -> list[str]:
    lines = [
        "| 방법 | 용도 | Precision | Recall | F1 | 상태 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for method in (
        "keyword_only",
        f"llm_only@{threshold:.2f}",
        f"hybrid@{threshold:.2f}",
    ):
        for usage, value in (result.get("methods", {}).get(method) or {}).items():
            metrics = value.get("metrics") or {}
            cells = [
                f"{metrics[key]:.4f}" if isinstance(metrics.get(key), float) else "-"
                for key in ("precision", "recall", "f1")
            ]
            lines.append(
                f"| {method} | {usage} | {' | '.join(cells)} | {value.get('status')} |"
            )
    return lines


def cmd_evaluate(args: argparse.Namespace) -> int:
    from app.dataset_pipeline import gold_review
    from scripts import assemble_independent_gold as assemble

    queue = args.data_dir / PRECISION_QUEUE
    history = args.data_dir / PRECISION_HISTORY
    if not queue.is_file():
        print(f"NOT_READY: 검수 큐가 없습니다 ({queue}).", file=sys.stderr)
        return NOT_READY_EXIT
    rows = assemble._read_queue(queue)
    events = gold_review.load_history(history)
    if events:
        rows = gold_review.build_gold_template_rows(rows, events)
    approved = _approved_count(rows)
    if approved == 0:
        print(
            "NOT_READY: 독립 승인(INDEPENDENT_APPROVED) Gold가 0건입니다. "
            f"전체 {len(rows)}건 중 승인 0건, 검수 이벤트 {len(events)}건. "
            "Precision·Recall·F1을 계산하지 않습니다. "
            "검수: scripts/gold_review_cli.py, 배정: scripts/gold_review_kit.py assign",
            file=sys.stderr,
        )
        return NOT_READY_EXIT
    status = assemble.run(
        output_path=args.gold_output,
        status_path=args.status_output,
        history_path=history if events else None,
        queue_path=queue,
    )
    if status["status"] != "READY":
        print(
            f"NOT_READY: 승인 {approved}/{len(rows)}건. test split "
            f"{status['pending_or_invalid_test_count']}/{status['test_row_count']}건이 "
            "아직 승인 요건(2인 합의·근거 인용·사유)을 충족하지 않았습니다. "
            f"상세: {args.status_output}",
            file=sys.stderr,
        )
        return NOT_READY_EXIT
    from scripts import compare_precision_methods as compare

    result = compare.run(
        workbook_path=args.workbook,
        gold_path=args.gold_output,
        data_dir=args.data_dir,
        output_path=args.result_output,
    )
    lines = [
        "# Keyword / LLM / Hybrid 정밀도 평가 (독립 승인 Gold)",
        "",
        f"- 승인 Gold: {approved}/{len(rows)}건",
        f"- 결과 JSON: `{args.result_output}`",
        "",
        *_metric_table(result, args.threshold),
        "",
    ]
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    sub = parser.add_subparsers(dest="command", required=True)

    assign = sub.add_parser("assign", help="이중 검수 배정 시트")
    assign.add_argument(
        "--reviewer", action="append", help="검수자 이름 (2명 이상, 반복 지정)"
    )
    assign.add_argument(
        "--output", type=Path, default=ROOT / "reports/gold_review/assignment_sheet.csv"
    )
    assign.set_defaults(func=cmd_assign)

    draft = sub.add_parser("draft-map", help="conceptCode·approvedEvidence 후보 초안")
    draft.add_argument("--concepts", default="concept_master_1123.json")
    draft.add_argument("--concept-sources", default="concept_sources_reviewed.csv")
    draft.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/evaluation/tutor_concept_evidence_draft.jsonl",
    )
    draft.set_defaults(func=cmd_draft_map)

    agreement = sub.add_parser("agreement", help="불일치·Cohen's kappa 리포트")
    agreement.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/gold_review/agreement_report.json",
    )
    agreement.set_defaults(func=cmd_agreement)

    gaps = sub.add_parser("audit-gaps", help="검수자/검수일/라이선스 공백 목록")
    gaps.add_argument("--concepts", default="concept_master_1123.json")
    gaps.add_argument("--concept-sources", default="concept_sources_reviewed.csv")
    gaps.add_argument("--prerequisites", default="prerequisite_review.csv")
    gaps.add_argument("--documents", default="bok_documents.csv")
    gaps.add_argument(
        "--normalized", default="processed_full/normalized_documents.jsonl"
    )
    gaps.add_argument(
        "--output-csv",
        type=Path,
        default=ROOT / "reports/curation/curation_review_gaps.csv",
    )
    gaps.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "reports/curation/curation_review_gaps.md",
    )
    gaps.set_defaults(func=cmd_audit_gaps)

    evaluate = sub.add_parser("evaluate", help="승인 후 P/R/F1 원커맨드")
    evaluate.add_argument("--workbook", type=Path, default=None)
    evaluate.add_argument("--threshold", type=float, default=0.7)
    evaluate.add_argument(
        "--gold-output", type=Path, default=ROOT / "reports/independent_gold_test.csv"
    )
    evaluate.add_argument(
        "--status-output",
        type=Path,
        default=ROOT / "reports/independent_gold_assembly_status.json",
    )
    evaluate.add_argument(
        "--result-output",
        type=Path,
        default=ROOT / "reports/method_comparison_result.json",
    )
    evaluate.add_argument(
        "--summary-output",
        type=Path,
        default=ROOT / "reports/gold_review/precision_eval_summary.md",
    )
    evaluate.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
