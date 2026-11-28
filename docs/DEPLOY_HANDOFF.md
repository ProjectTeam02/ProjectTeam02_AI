# AI 서버 배포 Handoff (인프라 담당용)

작성일: 2026-11-28 · 대상: 인프라 담당(김유비) · 관련 이슈: AI #32, #34 (closed), Back #134·#136

> 이 문서에는 시크릿 값이 없다. 모든 명령은 **값을 화면에 출력하지 않도록** 작성했다.
> 값을 확인해야 할 때는 존재 여부·길이·접속 성공 여부만 본다.

## 1. 현재 운영 배포 경로 (실제 사용 중)

```text
AI main 병합
  └─ AI .github/workflows/build-ai-image.yml   (OIDC → ECR leren-ai:<커밋 12자리>, linux/arm64)
Back Actions → deploy → Run workflow
  └─ action=deploy, backend_tag=<비우면 Back HEAD 12자리>, ai_tag=<AI 커밋 12자리 | current>
       └─ SSM send-command → EC2(tag leren-deploy=app) /opt/leren/deploy/deploy.sh <backend> <ai>
            ├─ Parameter Store /leren/prod/{backend,migrate,ai}/ → /opt/leren/env/*.env (root 600)
            ├─ docker pull leren-backend / leren-ai
            ├─ compose up --wait (ai 이미지 HEALTHCHECK = GET :8000/health)
            └─ 실패 시 직전 태그로 자동 롤백, 기록 /opt/leren/deploy.log, /opt/leren/current.env
```

- AI 레포의 레거시 ECS 워크플로우(`deploy-ai.yml`)는 이 브랜치에서 삭제했다.
  `infra/terraform/`, `deploy/aws/ecs-*.json`은 **미사용(레거시)** 이며 운영 리소스와 다르다
  (ECS Fargate·ALB·x86·자체 RDS·ECR `projectteam02-ai` 기준).
- **주의**: AI `/health`는 프로세스 생존만 본다(DB 미확인). deploy 성공 ≠ RDS 연결 성공.
  RDS 연결은 아래 4·5단계로 따로 확인한다.

## 2. 현재 확인된 상태 (2026-11-28, GitHub Actions 공개 기록 기준)

| 항목 | 상태 | 근거 |
|---|---|---|
| OIDC `Could not load credentials` | 해결됨 | AI run 45787429250(11/26) `configure-aws-credentials` 성공 |
| ECR leren-ai ARM64 push | 동작 | 같은 run의 `빌드·푸시 (linux/arm64)` 성공, 태그 `641b0803…`(main HEAD 12자리) |
| EC2 배포 | 마지막 성공 11/23 | Back deploy run 45128724258 |
| AI #41(11/24)·#43(11/26) 운영 반영 | **미확인** | 11/23 이후 deploy 실행 기록 없음 |
| `ai_user` 인증 실패 | **코드 원인 수정(이 브랜치)** | 아래 3절 |

## 3. `ai_user` 인증 실패: 코드 원인과 수정

`app/rag/indexing/vector_store.py`가 SQLAlchemy `URL` 객체를 `PGVectorStore`에 넘겼고,
llama-index는 내부에서 `str(url)`을 호출한다. SQLAlchemy 2.x의 `str(URL)`은 비밀번호를
`***`로 가리므로 RDS에는 비밀번호 `***`로 접속 시도 → `password authentication failed for user "ai_user"`.

- 수정: `render_as_string(hide_password=False)`로 문자열을 넘기고, SSL 옵션을
  드라이버별로 변환(asyncpg `ssl=` ↔ psycopg `sslmode=`).
- 회귀 테스트: `tests/test_db_ownership.py::test_vector_store_passes_real_password_to_pgvector`,
  `::test_vector_store_translates_ssl_option_per_driver`.
- 이 수정이 병합·배포된 뒤에도 실패하면 원인은 인프라 쪽(SSM 값 ↔ RDS 역할 비밀번호 불일치,
  `pg_hba`/SG, SSL 강제)이다 → 4절로 확인.

`DATABASE_URL` 형식 요구사항(SSM `/leren/prod/ai/DATABASE_URL`):

```text
postgresql+asyncpg://ai_user:<URL 인코딩된 비밀번호>@<rds-endpoint>:5432/<db>?ssl=require
```

- 비밀번호의 `@ : / ? # % +` 등은 반드시 percent-encoding.
- asyncpg 엔진(`app/db/connection.py`)은 `sslmode=`를 받지 못하므로 **`ssl=`로 적는다**.
- 함께 필요한 값: `ENVIRONMENT=production`, `VECTOR_STORE_SCHEMA=ai`,
  `VECTOR_STORE_PERFORM_SETUP=false`, `INTERNAL_API_TOKEN`(Back의 `FASTAPI_INTERNAL_TOKEN`과 동일),
  `OPENROUTER_API_KEY`. production에서 schema=public 또는 perform_setup=true면 기동 시 실패한다.

## 4. 인프라 담당 확인 명령 (사람 필요)

```bash
# 4-1. SSM 파라미터 존재 확인 (값 출력 없음)
aws ssm get-parameters-by-path --region ap-northeast-2 --path /leren/prod/ai/ \
  --query 'Parameters[].Name' --output text
aws ssm get-parameter --region ap-northeast-2 --name /leren/prod/ai/DATABASE_URL \
  --with-decryption --query 'Parameter.Value' --output text \
  | python3 -c 'import sys,urllib.parse as u; p=u.urlsplit(sys.stdin.read().strip()); print("scheme",p.scheme,"user",p.username,"host",p.hostname,"db",p.path,"query",p.query,"pw_len",len(p.password or ""))'

# 4-2. EC2 안에서 ai_user 접속 테스트 (SSM Session Manager로 EC2 접속 후, root)
sudo bash -c 'set -a; . /opt/leren/env/ai.env; set +a;
  docker run --rm --network leren_default -e DATABASE_URL postgres:16-alpine sh -c "
    U=\$(echo \"\$DATABASE_URL\" | sed -e s#postgresql+asyncpg#postgresql# -e s#ssl=#sslmode=#);
    psql \"\$U\" -Atc \"select current_user, current_schema(), has_schema_privilege(current_user,'"'"'ai'"'"','"'"'USAGE'"'"')\"
  "'
# 기대: ai_user|...|t

# 4-3. ai 스키마 벡터 테이블 권한 (같은 방식으로)
#   select has_table_privilege('ai_user','ai.data_projectteam02','SELECT,INSERT');
```

## 5. 배포·스모크 (사람 필요: Back 레포 Actions 실행 권한)

1. AI 이 브랜치 PR 병합 → `build-ai-image` 성공 확인 → 요약의 `leren-ai:<12자리>` 기록.
2. Back Actions → `deploy` → Run workflow: `action=deploy`, `backend_tag=`(비움), `ai_tag=<위 12자리>`.
3. EC2에서:

```bash
sudo tail -n 5 /opt/leren/deploy.log            # DONE backend=... ai=<12자리>
sudo cat /opt/leren/current.env                 # AI_TAG 확인
curl -s http://127.0.0.1:3000/health            # Back
curl -s http://127.0.0.1:3000/api/v1/health/ready
sudo docker compose -p leren exec ai python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"

# 튜터 내부 API 스모크 (토큰은 env 파일에서 읽고 출력하지 않음)
sudo docker compose -p leren exec ai sh -c 'python - <<EOF
import json, os, uuid, urllib.request
body = {"requestId": str(uuid.uuid4()), "conversationId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()), "question": "기준금리가 뭐야?", "modelTier": "BASIC",
        "history": [], "knowledgeScope": {"conceptCodes": []}}
req = urllib.request.Request("http://127.0.0.1:8000/internal/v1/tutor/answer",
    data=json.dumps(body).encode(), method="POST",
    headers={"Content-Type": "application/json", "X-Internal-API-Key": os.environ["INTERNAL_API_TOKEN"]})
r = json.load(urllib.request.urlopen(req, timeout=60))
print(r["groundingStatus"], len(r["sources"]), r["usage"]["latencyMs"], r["usage"]["retrievalStrategy"])
EOF'

# RDS 연결 로그
sudo docker compose -p leren logs ai --since 30m | grep -iE "password authentication|connection refused|ssl|asyncpg|psycopg|pgvector|OperationalError" | tail -20
```

## 6. OIDC Trust Policy 참고 (현재 동작 중, 변경 시 확인용)

두 워크플로우 모두 `environment: production`을 쓰므로 토큰 `sub`는
`repo:ProjectTeam02/<레포>:environment:production` 이다(빌드 로그의 `sub=` 줄로 확인 가능).

```json
{
  "Effect": "Allow",
  "Principal": {"Federated": "arn:aws:iam::955094290134:oidc-provider/token.actions.githubusercontent.com"},
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
    "StringLike": {"token.actions.githubusercontent.com:sub": [
      "repo:ProjectTeam02/ProjectTeam02_AI:environment:production",
      "repo:ProjectTeam02/ProjectTeam02_Back:environment:production"
    ]}
  }
}
```

워크플로우에는 `permissions: id-token: write`와 `vars.AWS_DEPLOY_ROLE_ARN`(production 환경 변수)가 필요하다.

## 7. 성공 판정 기준 (모두 충족 시 P3 완료)

- [ ] `build-ai-image` 성공 + ECR `leren-ai:<12자리>` 존재
- [ ] Back `deploy` 성공, `/opt/leren/current.env`의 `AI_TAG`가 같은 12자리
- [ ] Back `/health` 200, `/api/v1/health/ready` 200
- [ ] AI `:8000/health` → `{"status":"ok"}`
- [ ] 튜터 스모크: HTTP 200, `groundingStatus` 값 존재 (`INSUFFICIENT`도 계약상 정상)
- [ ] 4-2 psql: `ai_user`로 접속 성공, ai 스키마 USAGE `t`
- [ ] 최근 30분 ai 로그에 `password authentication failed` 없음

결과(명령 출력에서 시크릿 제외)는 AI 이슈 #32에 코멘트로 남긴다.
