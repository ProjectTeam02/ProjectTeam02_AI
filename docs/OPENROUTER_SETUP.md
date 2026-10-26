# OpenRouter LLM·Embedding 설정

## 기본 설정

프로젝트 루트에 `.env`를 직접 만들고 실제 키를 로컬 파일에만 입력한다.
`.env`와 `.env.example`은 모두 `.gitignore`에 포함되어 있으며 키를 소스나
문서에 저장하지 않는다.

```dotenv
OPENROUTER_API_KEY=sk-or-v1-<local-secret>
LLM_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4o-mini
LLM_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_PROVIDER=openrouter
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_DIMENSION=1536
LLM_TIMEOUT_SECONDS=30
LLM_MAX_OUTPUT_TOKENS=700
```

OpenAI 공식 Provider를 선택하려면 `LLM_PROVIDER=openai` 또는
`EMBEDDING_PROVIDER=openai`로 바꾸고 해당 Provider의 `OPENAI_API_KEY`를 별도로
설정한다. Provider 간 키를 자동으로 대체하지 않는다.

## 구현 동작

- `LLMFactory`는 LlamaIndex `OpenAI` 어댑터에 OpenRouter base URL과
  `OPENROUTER_API_KEY`를 전달한다.
- `EmbeddingModelFactory`는 OpenRouter의 OpenAI 호환 embeddings endpoint를
  사용한다. LlamaIndex 0.14의 내부 enum 검사를 통과시키면서 API 요청에는
  `openai/text-embedding-3-small` 전체 모델 ID를 보존한다.
- 응답 벡터의 길이가 `EMBEDDING_DIMENSION`과 다르면
  `ConfigurationError`를 발생시켜 pgvector 저장을 중단한다. 더미 벡터로
  대체하지 않는다.
- API 키가 없거나 OpenRouter 모델 ID가 `provider/model` 형식이 아니면 Factory
  생성 단계에서 설정 오류를 반환한다.

OpenRouter 공식 [Embedding API 문서](https://openrouter.ai/docs/api/api-reference/embeddings/create-embeddings)와
[Text Embedding 3 Small 모델 문서](https://openrouter.ai/openai/text-embedding-3-small/providers)에
따르면 `openai/text-embedding-3-small`은 `POST /api/v1/embeddings`에서
`dimensions: 1536`으로 요청할 수 있다. LLM은 OpenAI 호환 API base URL을
사용한다. 실제 연결은 키·네트워크·계정 크레딧이 필요하므로 기본 pytest에서는
호출하지 않는다.

## 테스트

```bash
.venv/bin/python -m pytest -q tests/test_openrouter_config.py
.venv/bin/python -m ruff check app tests
```

실제 API 확인이 필요할 때만 로컬 `.env`에 키를 넣고, 소량의 단일 요청으로
별도 통합 테스트를 실행한다. 대량 임베딩 인덱싱은 자동으로 실행하지 않는다.
