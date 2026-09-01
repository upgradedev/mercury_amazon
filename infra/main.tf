# Terraform Infrastructure for Mercury Voice CTO Cockpit on AWS

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "prod"
}

# IAM Role with Least Privilege for AWS Cost Explorer & CloudWatch
resource "aws_iam_role" "mercury_exec_role" {
  name = "mercury-cto-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "mercury_telemetry_policy" {
  name        = "mercury-telemetry-policy-${var.environment}"
  description = "Least privilege read access for AWS Cost Explorer & CloudWatch metrics"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
          "ce:GetAnomalies",
          "cloudwatch:GetMetricData"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mercury_attach" {
  role       = aws_iam_role.mercury_exec_role.name
  policy_arn = aws_iam_policy.mercury_telemetry_policy.arn
}

resource "aws_ecs_cluster" "mercury_cluster" {
  name = "mercury-cto-cluster-${var.environment}"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.mercury_cluster.name
  description = "Name of the Mercury ECS cluster"
}
