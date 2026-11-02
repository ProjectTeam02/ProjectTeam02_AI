# Leren 데이터셋 EDA 보고서

## 실행 상태

- 실행 스크립트: `scripts/run_eda.py`
- 데이터셋 버전: `50047d6bd740671252df664aba2ee0bbac845bbf68addbc4f90d6c5efe8e7d0d`
- 토크나이저: `o200k_base` (`tiktoken`, 실측)
- 원본 파일: 4개, canonical 고유 문서: 3539건
- JSON/JSONL 쌍은 중복 집계하지 않았고, 원본 파일 자체는 수정하지 않았습니다.

## 실제 규모

- 기관별 문서: {'BOK': 789, 'KDI': 2750}
- 전체 토큰: 770,607 tokens
- 평균 토큰: 217.75 tokens
- 중앙값 / p95: 195.00 / 449.00
- 청크: 3,539건 → 3,545건

## 품질 및 해석 주의사항

- BOK 데이터의 source URL·review status·license approval이 canonical 파일에 없거나 미확정이므로 운영 승인으로 해석하지 않았습니다.
- 챕터 설정은 production curriculum이 없어 `DRAFT_NOT_CANONICAL` 임시 파일입니다.
- 키워드 매칭은 후보 추출 결과이며 관련성 확정, 확률, 정답 라벨이 아닙니다.
- 상세 결과: `dataset_statistics.json`, `dataset_quality_report.csv`, `figures/`.

## 기존 리포트와의 관계

이번 실행은 현재 `data/` 하위 파일을 직접 읽었습니다. 이전 시점의 보고서에는 다른 BOK 스키마가 기록되어 있을 수 있으므로, 이 파일의 dataset_version과 file inventory를 기준으로 사용합니다.
