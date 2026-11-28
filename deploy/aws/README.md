# deploy/aws (레거시)

`ecs-task-definition.json`과 IAM 정책 예시는 ECS 전환을 검토할 때 만든 자료로, 현재 운영에서
사용하지 않는다. 운영 배포는 `build-ai-image.yml` → Back `deploy.yml`(EC2/SSM)이며
`docs/DEPLOY_HANDOFF.md`에 정리했다.
