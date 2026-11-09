# AWS 배포

이 구성은 다음 AWS 리소스를 생성합니다.

- ECR: FastAPI 이미지 저장소
- ECS Fargate + ALB: FastAPI 실행 및 `/health` 기반 라우팅
- RDS PostgreSQL: `pgvector`를 사용할 데이터베이스
- S3: 승인된 BOK/KDI 자료 저장소
- Secrets Manager: DB URL, OpenRouter key, 내부 API token
- CloudWatch Logs: ECS 로그

Terraform state와 실제 secret 값은 저장소에 커밋하지 않습니다.

## 적용 순서

```bash
cd infra/terraform
terraform init
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars의 openrouter_api_key를 실제 값으로 교체

# ECR과 S3만 먼저 만듭니다. 최초 ECS task가 받을 이미지를 준비하기 위한 단계입니다.
terraform apply \
  -target=aws_ecr_repository.ai \
  -target=aws_s3_bucket.data \
  -target=aws_s3_bucket_public_access_block.data \
  -target=aws_s3_bucket_versioning.data \
  -target=aws_s3_bucket_server_side_encryption_configuration.data
```

ECR 로그인 후 이미지를 빌드하고 업로드합니다.

```bash
AWS_REGION=ap-northeast-2
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPOSITORY=projectteam02-ai

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker buildx build --platform linux/amd64 \
  -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:latest" \
  --push ../..
```

그 다음 전체 인프라를 생성합니다.

```bash
terraform apply
```

승인 자료는 저장소에 포함하지 않으므로 S3에 별도로 업로드합니다.

```bash
DATA_BUCKET=$(terraform output -raw s3_data_bucket)
aws s3 cp ../../data/bok_terms_2026_rag.jsonl \
  "s3://$DATA_BUCKET/leren-ai/bok_terms_2026_rag.jsonl"
aws s3 cp ../../data/bok_terms_2026.json \
  "s3://$DATA_BUCKET/leren-ai/bok_terms_2026.json"
aws s3 cp ../../data/BOK_라벨링.xlsx \
  "s3://$DATA_BUCKET/leren-ai/BOK_라벨링.xlsx"

aws ecs update-service \
  --cluster "$(terraform output -raw ecs_cluster)" \
  --service "$(terraform output -raw ecs_service)" \
  --force-new-deployment
```

RDS는 private access로 생성됩니다. 기존 `migrations/` SQL은 VPC 내부의 임시
migration runner 또는 ECS one-off task에서 실행해야 합니다. 운영에서는 애플리케이션
시작 시 자동 migration하지 말고 배포 단계에서 별도로 실행하세요.
