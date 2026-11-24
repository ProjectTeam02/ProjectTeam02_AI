# Leren Tutor 모델 평가 진행 현황

- 전체 상태: `NOT_READY`
- 생성 시각: `2026-11-24T07:01:12.606315+00:00`

| 단계 | 상태 | 실제 결과 | 차단 사유 |
|---|---|---|---|
| Gold 검증 | BLOCKED | 100건, 독립 승인 0건 | conceptCode·근거·라이선스·검수 이력 부족 |
| Mock 비교 | COMPLETED | 5개 모델 하네스 실행 | 교육 품질 점수 대상 아님 |
| Live Smoke | BLOCKED | 실제 채팅 호출 0건 | 비용 상한·실행 승인 없음 |
| Interim 비교 | BLOCKED | 실제 비교 0건 | 승인된 사례 0건 |
| Final 비교 | BLOCKED | 실제 비교 0건 | 전체 Gold 승인 및 Live 결과 없음 |
| 사람 평가 | BLOCKED | 완료된 독립 사람 평가 없음 | 승인 Gold 및 검수 증거 부족 |
| Context A/B/C | BLOCKED | 별도 현재 결과 파일 없음 | 승인 Gold·Live 결과 없음 |

## 다음 필수 조건

1. 100개 사례의 canonical conceptCode 매핑
2. 출처 승인과 라이선스 승인 분리 확인
3. 두 명 이상의 독립 검수와 adjudication 기록
4. 비용 상한을 명시한 `--execute` 승인
5. 5개 모델 동일 조건 Live 비교 및 사람 평가
