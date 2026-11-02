# 경제 용어 메타데이터 구조 감사

- 실행 상태: `EXECUTED_WITH_AVAILABLE_ARTIFACTS`
- 본 문서는 현재 보유 파일의 필드 존재 여부와 개선 설계를 구분합니다.

## 실제 파일 감사

### `/Users/a1/Desktop/산학프로젝트 /ProjectTeam02_AI/data/processed/normalized_documents.jsonl` (3539건)

- `keyword`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `root_topic`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `relation_type`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `summary`: 열 `[]`, 채움 `0건`, 비율 `0.0`

### `/Users/a1/Desktop/산학프로젝트 /ProjectTeam02_AI/data/processed/chunks.jsonl` (3545건)

- `keyword`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `root_topic`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `relation_type`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `summary`: 열 `[]`, 채움 `0건`, 비율 `0.0`

### `/Users/a1/Desktop/산학프로젝트 /ProjectTeam02_AI/reports/step3/keyword_predictions.csv` (789건)

- `keyword`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `root_topic`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `relation_type`: 열 `[]`, 채움 `0건`, 비율 `0.0`
- `summary`: 열 `[]`, 채움 `0건`, 비율 `0.0`

## 유지할 요소

`keyword`, `root_topic`, `relation_type`, `summary`는 원문 기반 개념 메타데이터로 유지합니다. 다만 챕터 관련도는 별도 매핑 테이블로 분리합니다.

## 개선할 요소

- `aliases`와 정규화 표기를 공식 표제어와 분리합니다.
- `root_topic`과 학습 `chapter_id`를 혼동하지 않습니다.
- 다중 관계가 가능한 `relation_type`과 `base_concept_id`를 지원합니다.
- `summary`의 원문 근거와 검수 상태를 추적합니다.
- 키워드 매칭 결과는 후보 신호일 뿐, 관련도·정밀도·확률로 해석하지 않습니다.

## 생성된 설계 파일

- `reports/metadata_schema.json`
- `reports/chapter_config.json`
- `reports/keyword_dictionary.json`

인플레이션 챕터는 현재 `DRAFT_NOT_CANONICAL` 상태이며 멘토·교수 확정 전까지 최종 기준으로 사용하지 않습니다.
