# 로컬 데이터 배치 안내

원본 경제·금융 데이터는 사용권과 파일 크기 문제로 Git에 커밋하지 않습니다. EDA와 청크 파이프라인을 실행하려면 다음 구조로 원본 파일을 배치해야 합니다.

```text
data/
├── kdi 시사경제용어/
│   ├── kdi_terms.json
│   └── kdi_terms.jsonl
└── 한국은행/
    ├── bok_terms_2026.json
    └── bok_terms_2026_rag.jsonl
```

JSON과 JSONL이 같은 기관의 미러 파일이면 JSONL을 정규화 기준으로 사용하고, JSON은 중복 집계하지 않고 무결성 비교에만 사용합니다.

원본 데이터가 없는 환경에서 다음 명령은 데이터가 없다는 오류를 명확히 표시합니다.

```bash
./.venv/bin/python -m scripts.run_eda
./.venv/bin/python -m scripts.make_chunks
```

원본 파일의 사용권, 출처, 배포 가능 여부는 저장소에 추가하기 전에 별도로 확인해야 합니다.
