# 남은 작업 분류

현재 FastAPI 브랜치의 P0 범위와 OpenRouter 단일 모델 연동은 구현되어 있다.
아래 항목은 Node.js Backend, AI 서버, 양쪽 협의가 필요한 작업으로 나눈 후속 목록이다.

## Node.js Backend 담당

| 우선순위 | 작업 | 완료 기준 |
|---|---|---|
| P0 | JWT 인증 및 내부 서비스 토큰 운영 | FastAPI는 Node.js 서버 요청만 수락하고 토큰 교체 절차가 있다. |
| P0 | `conversationId` 생성·소유권 검증 | 새 대화 ID를 Node.js가 만들고 후속 요청에 재사용한다. |
| P0 | `ai_conversations`, `ai_messages` 저장 | 요청·응답·sequence·summary·historyFromSeq가 ERD에 저장된다. |
| P0 | `ai_message_sources` 저장 | FastAPI의 source 응답을 문서 버전·청크·rank와 함께 저장한다. |
| P0 | `ai_requests` 및 사용량 저장 | requestId 멱등성, 상태, 모델, 토큰, latency, 비용을 기록한다. |
| P0 | 무료/프리미엄 제한과 rate limit | 일일 한도·동시 요청 예약·중복 요청 처리가 Node.js에서 동작한다. |
| P1 | 퀴즈·보상·학습 진행 연계 | AI 서버가 점수나 보상을 직접 변경하지 않고 Node.js 도메인 로직으로 처리한다. |

## AI 서버 담당

| 우선순위 | 작업 | 완료 기준 |
|---|---|---|
| P0 | 운영 PostgreSQL/pgvector 연결 | 승인 문서만 인덱싱되고 embedding provider/model/dimension 불일치가 차단된다. |
| P0 | 검수된 BOK 문서 배포 | 789개 원문 중 검토 대상 29개가 자동 승인되지 않고 라이선스가 확인된다. |
| P0 | 실제 RAG 통합 테스트 | 검색·답변·citation·grounding을 staging DB에서 검증한다. |
| P1 | 검색 평가셋 30~50개 운영 | Recall@5, MRR, citation 정확성, groundedness, latency를 정기 측정한다. |
| P1 | BASIC/ADVANCED 모델 라우팅 | `modelTier`별 모델·비용·timeout 정책을 백엔드와 합의하고 적용한다. 현재는 설정된 단일 모델을 사용한다. |
| P1 | 관측성 및 비용 분석 | OpenRouter 실제 usage, latency, 오류율, 추정 비용을 민감정보 없이 기록한다. |
| P1 | 검색 품질 개선 | reranking, exact/vector hybrid 가중치, context budget을 평가 결과로 조정한다. |
| P2 | 장기 메모리·개인화 | Node.js History와 분리된 사용자 선호/학습 패턴 메모리를 별도 설계한다. |

## 공동 협의 및 운영

- `TUTOR_INTERNAL_API_CONTRACT.md`의 nullable 필드와 Enum을 Node.js DTO와 고정한다.
- ERD PDF 원문과 실제 운영 DB 스키마를 대조하고, FastAPI가 Node 소유 테이블을 생성하지 않는지 확인한다.
- `documentId`, `documentVersion`, `chunkId`, `conceptCode`의 식별자 규칙을 확정한다.
- 한국은행 자료의 이용 허가, 출처 표기, 갱신 주기와 검수 책임을 문서화한다.
- Python 3.12, Docker Compose PostgreSQL/pgvector, staging OpenRouter secret 주입을 CI에서 검증한다.
- OpenRouter API 호출은 단일 smoke test와 승인된 인덱싱 작업으로 제한하고 대량 호출은 별도 승인한다.

## 현재 확인된 상태

- OpenRouter chat completion smoke test: 성공
- OpenRouter embedding smoke test: 성공, 벡터 길이 1536
- LlamaIndex Factory 직접 호출: 성공
- PostgreSQL/pgvector 운영 연결 및 대량 BOK 재인덱싱: 미실행
- 실제 Node.js 연동 및 ERD DB 저장: 미검증
