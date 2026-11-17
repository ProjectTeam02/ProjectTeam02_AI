# 최신 연구 검토와 Leren 적용 매핑

검토 기준일: 2026-11-12. ACL Anthology의 원문 PDF/초록과 논문에 명시된 공개 저장소 링크를 확인했다. 논문의 방법·수치·데이터를 복제하지 않고, Leren 코드에는 호환 가능한 독자 구현만 적용한다.

## 연구별 요약

| 연구 | 해결 문제와 핵심 방법 | 기존 방식과 차이 / 평가 | 공개 코드·라이선스 확인 | Leren 적용·난도·변경 |
|---|---|---|---|---|
| SemEval-2026 Task 8, *Hybrid Retrieval and Query Rewriting for Multi-Turn RAG* | 멀티턴 의도 변화·대화 노이즈·context 제한. dense+sparse, controlled rewrite, cross-encoder rerank를 결합한 training-free pipeline. | Task A nDCG@5 0.5453, 38팀 중 3위; baseline 0.4795. Task C quality/faithfulness harmonic mean 0.5312, 29팀 중 15위. | 논문이 `mengsifei/Multi_turn_RAG` 코드를 명시. retrieval components open-source라고 명시하지만 저장소별 상업 라이선스는 별도 검증 필요. ACL 출판물은 CC BY 4.0 범위. | 기존 pgvector를 dense로 두고 PostgreSQL FTS sparse + RRF를 추가했다. cross-encoder는 승인된 모델/라이선스 없이는 넣지 않고 deterministic reranker만 제공. 난도 중간, 추가 인프라 없음. |
| CompCQR | 반복적인 LLM CQR 호출과 retriever 민감도를 줄이기 위해 소수 atomic component를 조합해 많은 query를 만들고, LLM reasoning으로 precision/recall 문서 집합을 선택. | 4개 conversational benchmark에서 최대 22.5% relative MRR 개선, 더 적은 LLM 호출. 세부 수치의 재현은 원문 설정 필요. | 논문에 `YunahJang/CompCQR` 코드 링크. 저장소 라이선스는 검증 필요; 데이터/코드 복제하지 않음. | 현재는 rewrite를 context-dependent turn에만 호출하고 실패 시 deterministic fallback/trace를 둔다. query explosion은 비용·응답 지연 때문에 보류. 난도 중간~상. |
| mtRAG | 사람 작성 end-to-end 멀티턴 RAG benchmark. 후속 turn, unanswerable, non-standalone, 다중 도메인 평가. | 110 conversations, 평균 7.7 turns, 4 domains, 842 tasks. human/automatic 평가에서 SOTA도 어려움을 보임. | `ibm/mt-rag-benchmark` 공개 링크 확인. 저장소 라이선스는 별도 검증 필요. | Leren 평가 포맷에 multi-turn context accuracy와 unanswerable label을 포함한다. 외부 benchmark 데이터는 복제하지 않는다. 난도 낮음~중간. |
| MTRAG-UN | UNanswerable, UNderspecified, NONstandalone question과 UNclear response를 별도 challenge로 구성. | 666 tasks/conversations, 2,800+ turns, 6 domains. retrieval/generation의 open challenge를 측정. | `IBM/mt-rag-benchmark` 공개 링크 확인. 저장소 라이선스는 별도 검증 필요. | query rewrite가 억지로 질문을 확정하지 않도록 context-insufficient 상태와 안전한 보류를 평가한다. 난도 중간. |
| OpenAI Harness Engineering | agent가 읽을 수 있는 repository knowledge, 짧은 AGENTS map, architecture/docs를 system of record로 두고 legibility, architecture checks, quality/entropy 관리. | 모델 자체보다 실행 환경·문서·검증 루프를 개선하는 engineering practice; 학술 benchmark 수치는 논문이 아님. | OpenAI 공식 글. 코드/데이터 배포판이 아님. | `docs/architecture.md`, 계약 문서, 평가 실행 규칙, stage trace를 source of truth로 유지한다. 난도 낮음. |
| Beyond Prompts | fixed model 주변 prompt, tool boundary middleware, state/recovery를 resource-bounded harness selection으로 최적화하고 failure surface별로 수정. | held-out lift, worst-condition lift, repeatability, cost diagnostics, RelLift95(B)를 함께 보고. PRISM의 BFCL/tau2 결과가 원문에 제시됨. | ACL 논문에 별도 공개 저장소 링크가 없어 공개 구현은 검증 필요. | Leren은 stage contract/log/retry/timeout/cost를 기록하고 변경 전후 동일 dataset 비교를 강제한다. PRISM 자체는 복제하지 않는다. 난도 중간. |
| Retrospective Harness Optimization | 과거 trajectory에서 어려운 coreset을 골라 재풀이·self-validation·self-consistency·pairwise self-preference로 harness를 갱신. | 외부 grader 없이 SWE-Bench Pro pass rate 59%→78%라는 논문 보고. 결과 신뢰성은 별도 held-out 검증이 필요. | `wbopan/retro-harness` 코드 링크 확인. 저장소 라이선스는 검증 필요. | 운영 로그에 실패 유형을 남기되 자동 prompt 수정/배포는 하지 않는다. review 후 harness 변경으로 제한. 난도 중간~상. |
| K-FinHallu | 한국 금융 멀티턴 RAG의 source faithfulness와 answerability를 평가하고, context answerability 기반 hallucination taxonomy와 justified abstention을 포함. | 한국 금융 authentic document 기반 대화와 주입 hallucination; open/closed detector 모두 fine-grained diagnosis와 refusal에 어려움. | `eunbyeol-cho/K-FinHallu` code/data 링크 확인. 금융 데이터/코드 상업 사용 조건은 저장소 license 검증 필요. | terminology/number/contradiction/unsupported claim/over-refusal/under-refusal 라벨을 분리한다. 데이터 복제 없이 내부 검수셋으로 독자 평가. 난도 중간. |
| VERGE | task-specific multi-hop 평가 문항을 생성 중 검증. 문항별 multi-chunk criterion과 QA-integrity를 검사하고 실패는 수정 또는 폐기. | 11,052 candidates→2,854 verified MC items; strict-subset/chunk-removal/open-ended re-eval/inter-chunk stratification; verifier κ=0.903 보고. | 논문 원문에서 별도 코드 링크는 이 검토에서 확인하지 못함: 공개 구현 검증 필요. ACL 출판물은 CC BY 4.0 범위. | 현재 QG→QV→REVISE 제한 루프와 source ID 검증이 같은 방향이다. 검수 전 공개 금지와 실패 이유 보존을 명시한다. 난도 중간. |
| ARES | context relevance, answer faithfulness, answer relevance를 synthetic judge와 소수 human annotation/PPI로 평가. | KILT/SuperGLUE/AIS 8 task, 수백 human annotation으로 prediction-powered inference; domain shift도 평가. | ACL 원문은 code/data 공개를 명시하지만 이 검토에서 정확한 repository/license는 검증 필요. | 자동 judge 결과와 사람 검수 결과를 분리 저장한다. PPI 수치나 judge model은 승인 전 도입하지 않고 metric schema만 재사용. 난도 중간~상. |

## 현재 코드와의 차이

- 이미 구현: 내부 Tutor contract, conversation/user ownership check, bounded history, summary cutoff, deterministic/LLM rewrite, approved-only retrieval, citation identity 검사, QG/QV 제한 revision.
- 이번 P0 구현: PostgreSQL FTS sparse adapter, dense/sparse/exact RRF, 선택적 deterministic reranker, query rewrite trace, summary boundary decision, stage timeout/log/trace, ungrounded answer hold, Recall@5/nDCG@5 평가 함수와 JSONL 평가 runner.
- 검증 필요: 실제 pgvector index와 PostgreSQL FTS latency, provider별 token/cost, cross-encoder 품질, paper repository의 상업 라이선스, 80건 Gold의 사람 라벨.

## 라이선스·데이터 원칙

ACL 페이지는 2016년 이후 출판물을 CC BY 4.0으로 표시하지만, 이는 논문 원문 사용 조건과 각 GitHub 저장소·데이터셋의 조건을 동일시하지 않는다. 저장소 license가 확인되지 않은 코드는 복제하지 않고, 공개 논문의 알고리즘 아이디어만 독자 구현한다. KDI/BOK 원문은 기존 승인·license metadata 경계를 유지한다.
