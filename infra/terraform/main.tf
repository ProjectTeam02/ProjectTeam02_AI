data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  az_index           = { for index, az in local.availability_zones : az => index }
  name_prefix        = "${var.project_name}-${var.environment}"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  for_each = local.az_index

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, each.value + 1)
  map_public_ip_on_launch = true
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Public HTTP access to the AI service load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol    = "tcp"
    from_port   = 80
    to_port     = 80
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs" {
  name        = "${local.name_prefix}-ecs"
  description = "FastAPI tasks accept traffic only from the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol        = "tcp"
    from_port       = 8000
    to_port         = 8000
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "PostgreSQL access from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.ecs.id]
  }
}

resource "aws_s3_bucket" "data" {
  bucket_prefix = "${local.name_prefix}-data-"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_ecr_repository" "ai" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "ai" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 30
}

resource "aws_db_subnet_group" "ai" {
  name       = "${local.name_prefix}-db"
  subnet_ids = [for subnet in aws_subnet.public : subnet.id]
}

resource "random_password" "database" {
  length  = 32
  special = false
}

resource "random_password" "internal_api" {
  length  = 48
  special = false
}

resource "aws_db_instance" "ai" {
  identifier                 = local.name_prefix
  engine                     = "postgres"
  engine_version             = var.postgres_engine_version
  instance_class             = var.database_instance_class
  allocated_storage          = 20
  max_allocated_storage      = 100
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = "leren"
  username                   = "leren"
  password                   = random_password.database.result
  port                       = 5432
  db_subnet_group_name       = aws_db_subnet_group.ai.name
  vpc_security_group_ids     = [aws_security_group.rds.id]
  publicly_accessible        = false
  backup_retention_period    = 7
  auto_minor_version_upgrade = true
  deletion_protection        = var.environment == "production"
  skip_final_snapshot        = var.skip_final_snapshot
  apply_immediately          = false
}

resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name_prefix}/database-url"
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+asyncpg://leren:%s@%s:5432/leren",
    random_password.database.result,
    aws_db_instance.ai.address,
  )
}

resource "aws_secretsmanager_secret" "openrouter_api_key" {
  name = "${local.name_prefix}/openrouter-api-key"
}

resource "aws_secretsmanager_secret_version" "openrouter_api_key" {
  secret_id     = aws_secretsmanager_secret.openrouter_api_key.id
  secret_string = var.openrouter_api_key
}

resource "aws_secretsmanager_secret" "internal_api_token" {
  name = "${local.name_prefix}/internal-api-token"
}

resource "aws_secretsmanager_secret_version" "internal_api_token" {
  secret_id     = aws_secretsmanager_secret.internal_api_token.id
  secret_string = coalesce(var.internal_api_token, random_password.internal_api.result)
}

resource "aws_iam_role" "execution" {
  name = "${local.name_prefix}-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "execution" {
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = aws_ecr_repository.ai.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.ai.arn}:*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.database_url.arn,
          aws_secretsmanager_secret.openrouter_api_key.arn,
          aws_secretsmanager_secret.internal_api_token.arn,
        ]
      },
    ]
  })
}

resource "aws_iam_role" "task" {
  name = "${local.name_prefix}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.data.arn}/*"
    }]
  })
}

resource "aws_ecs_cluster" "ai" {
  name = var.project_name
}

resource "aws_lb" "ai" {
  name               = substr(replace(local.name_prefix, "_", "-"), 0, 32)
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]
}

resource "aws_lb_target_group" "ai" {
  name        = substr(replace(local.name_prefix, "_", "-"), 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.ai.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ai.arn
  }
}

resource "aws_ecs_task_definition" "ai" {
  family                   = var.project_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.container_cpu
  memory                   = var.container_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "ai"
      image     = "${aws_ecr_repository.ai.repository_url}:latest"
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "LLM_PROVIDER", value = "openrouter" },
        { name = "LLM_BASE_URL", value = "https://openrouter.ai/api/v1" },
        { name = "BOK_TERMS_S3_URI", value = "s3://${aws_s3_bucket.data.bucket}/${var.bok_terms_object_key}" },
        { name = "BOK_SOURCE_S3_URI", value = "s3://${aws_s3_bucket.data.bucket}/${var.bok_source_object_key}" },
        { name = "QUESTION_EVIDENCE_S3_URI", value = "s3://${aws_s3_bucket.data.bucket}/${var.bok_terms_object_key}" },
        { name = "QUESTION_APPROVAL_LABEL_S3_URI", value = "s3://${aws_s3_bucket.data.bucket}/${var.question_label_object_key}" },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
        { name = "OPENROUTER_API_KEY", valueFrom = aws_secretsmanager_secret.openrouter_api_key.arn },
        { name = "INTERNAL_API_TOKEN", valueFrom = aws_secretsmanager_secret.internal_api_token.arn },
      ]
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ai.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ai"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "ai" {
  name            = var.project_name
  cluster         = aws_ecs_cluster.ai.id
  task_definition = aws_ecs_task_definition.ai.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [for subnet in aws_subnet.public : subnet.id]
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ai.arn
    container_name   = "ai"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]
}
