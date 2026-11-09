#!/bin/sh
set -eu

# S3 자료가 지정된 운영 환경에서는 컨테이너 시작 시 읽기 전용 자료를
# ephemeral filesystem으로 내려받습니다. 로컬 Compose에서는 S3 URI를
# 지정하지 않고 ./data volume을 사용합니다.
if [ -n "${BOK_TERMS_S3_URI:-}" ]; then
  export BOK_TERMS_PATH=/tmp/leren-data/bok_terms_2026_rag.jsonl
fi
if [ -n "${BOK_SOURCE_S3_URI:-}" ]; then
  export BOK_SOURCE_PATH=/tmp/leren-data/bok_terms_2026.json
fi
if [ -n "${QUESTION_EVIDENCE_S3_URI:-}" ]; then
  export QUESTION_EVIDENCE_PATH=/tmp/leren-data/question-evidence.jsonl
fi
if [ -n "${QUESTION_APPROVAL_LABEL_S3_URI:-}" ]; then
  export QUESTION_APPROVAL_LABEL_PATH=/tmp/leren-data/question-approval-labels.xlsx
fi

python -m app.deploy.bootstrap_data
exec "$@"
