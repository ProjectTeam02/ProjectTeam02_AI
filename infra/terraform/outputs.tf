output "alb_url" {
  value = "http://${aws_lb.ai.dns_name}"
}

output "swagger_url" {
  value = "http://${aws_lb.ai.dns_name}/docs"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.ai.repository_url
}

output "s3_data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "rds_endpoint" {
  value = aws_db_instance.ai.address
}

output "ecs_cluster" {
  value = aws_ecs_cluster.ai.name
}

output "ecs_service" {
  value = aws_ecs_service.ai.name
}

output "internal_api_token" {
  value     = coalesce(var.internal_api_token, random_password.internal_api.result)
  sensitive = true
}
