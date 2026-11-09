variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "project_name" {
  type    = string
  default = "projectteam02-ai"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "container_cpu" {
  type    = number
  default = 512
}

variable "container_memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "database_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "postgres_engine_version" {
  type     = string
  default  = null
  nullable = true
}

variable "openrouter_api_key" {
  type      = string
  sensitive = true

  validation {
    condition     = length(trimspace(var.openrouter_api_key)) > 0
    error_message = "openrouter_api_key must be provided."
  }
}

variable "internal_api_token" {
  type      = string
  sensitive = true
  default   = null
  nullable  = true
}

variable "bok_terms_object_key" {
  type    = string
  default = "leren-ai/bok_terms_2026_rag.jsonl"
}

variable "bok_source_object_key" {
  type    = string
  default = "leren-ai/bok_terms_2026.json"
}

variable "question_label_object_key" {
  type    = string
  default = "leren-ai/BOK_라벨링.xlsx"
}

variable "skip_final_snapshot" {
  type    = bool
  default = false
}
