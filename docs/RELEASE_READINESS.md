# Release readiness gate

RAG 운영 색인과 최종 성능 수치를 배포하기 전에 데이터 승인·평가·커리큘럼
상태를 확인합니다. 이 검사는 원본 데이터나 라벨을 수정하지 않습니다.

```bash
# 현재 상태를 확인하되 명령은 성공으로 끝냄
.venv/bin/python scripts/check_release_readiness.py --report-only

# 배포 단계에서 미해결 항목이 있으면 실패
.venv/bin/python scripts/check_release_readiness.py
```

다음 조건을 모두 만족해야 `READY`입니다.

- BOK source URL 누락 없음
- source review 미확정 없음
- license 승인 미확정 없음
- 독립 Gold 상태가 `READY`
- 커리큘럼 상태가 `CANONICAL`

현재 저장소의 보고서는 이 조건을 만족하지 않으므로 `BLOCKED`가 정상입니다.
이 명령은 자동으로 승인 상태를 만들지 않으며, 사람의 라이선스 확인·Gold
합의·커리큘럼 확정 후 보고서를 재생성해야 통과합니다.
