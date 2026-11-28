#!/usr/bin/env bash
# AI 골든 예시(docs/contracts/examples)를 Backend의 실제 응답 검증 DTO에 넣어 대조한다.
#
# 사용법:
#   scripts/check_backend_contract.sh <ProjectTeam02_Back 경로> [git ref, 기본 origin/develop]
#
# - Backend 작업 트리는 건드리지 않는다. 지정 ref의 src/를 임시 폴더로 git archive 해서 읽는다.
# - valid/* 는 Backend parse(body, requestId, metadataEnabled=true)를 통과해야 하고,
#   invalid/* 는 Backend가 503(SERVICE_UNAVAILABLE)으로 거부해야 한다.
# - Node.js만 필요하다(npm 의존성 없음). CI에는 넣지 않는다(교차 레포 의존 방지).
set -euo pipefail

BACK_REPO="${1:?usage: $0 <ProjectTeam02_Back path> [ref]}"
REF="${2:-origin/develop}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git -C "$BACK_REPO" archive "$REF" src/common/errors src/modules/tutor/dto | tar -x -C "$TMP"
echo "Backend ref: $REF ($(git -C "$BACK_REPO" rev-parse --short "$REF"))"

node - "$TMP" "$ROOT/docs/contracts/examples" <<'NODE'
const fs = require('fs');
const path = require('path');
const [backRoot, examples] = process.argv.slice(2);
const dto = require(path.join(backRoot, 'src/modules/tutor/dto/aiInternalResponse.dto.js'));
let failures = 0;
for (const group of ['valid', 'invalid']) {
  for (const file of fs.readdirSync(path.join(examples, group)).filter(f => f.endsWith('.json')).sort()) {
    const body = JSON.parse(fs.readFileSync(path.join(examples, group, file), 'utf8'));
    let outcome;
    try {
      dto.parse(body, body.requestId, true);
      outcome = 'ACCEPT';
    } catch (error) {
      outcome = `REJECT(${error.statusCode} ${error.invalidField ?? error.message})`;
    }
    const ok = group === 'valid' ? outcome === 'ACCEPT' : outcome.startsWith('REJECT(503');
    if (!ok) failures += 1;
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${group}/${file} -> ${outcome}`);
  }
}
console.log(failures ? `${failures} mismatch(es)` : 'all examples agree with Backend DTO');
process.exit(failures ? 1 : 0);
NODE
