# Pure Serverless Terraform Infrastructure for Mercury Voice CTO Cockpit on AWS (eu-west-1)
# Architecture: AWS Lambda + Function URL + AWS Cost Explorer API + CloudWatch

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
  type        = string
  default     = "eu-west-1"
  description = "Primary AWS region for deployment"
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Environment tier"
}

variable "lambda_package_path" {
  type        = string
  default     = "../dist/mercury_lambda.zip"
  description = "Path to the built Lambda deployment package"
}

variable "source_revision" {
  type        = string
  description = "Immutable Git commit deployed in the Lambda package"
}

resource "aws_dynamodb_table" "mercury_state" {
  name         = "mercury-state-euw1-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Project     = "mercury"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# 1. IAM Execution Role for Lambda
resource "aws_iam_role" "mercury_lambda_role" {
  name = "mercury-lambda-role-euw1-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# 2. Least-Privilege Read Policy for Cost Explorer & CloudWatch
resource "aws_iam_policy" "mercury_serverless_policy" {
  name        = "mercury-serverless-policy-euw1-${var.environment}"
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
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/mercury-wallboard-euw1-${var.environment}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.mercury_state.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mercury_attach" {
  role       = aws_iam_role.mercury_lambda_role.name
  policy_arn = aws_iam_policy.mercury_serverless_policy.arn
}

# 3. AWS Lambda Serverless Wallboard API Function ($0.00 Idle Cost)
resource "aws_lambda_function" "mercury_wallboard_function" {
  function_name = "mercury-wallboard-euw1-${var.environment}"
  role          = aws_iam_role.mercury_lambda_role.arn
  runtime       = "python3.11"
  handler          = "src.interfaces.lambda_handler.handler"
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)
  memory_size      = 256
  timeout          = 15

  environment {
    variables = {
      ENVIRONMENT       = var.environment
      MERCURY_BUILD_SHA = var.source_revision
      MERCURY_STATE_TABLE = aws_dynamodb_table.mercury_state.name
    }
  }

  tags = {
    Project     = "mercury"
    Environment = var.environment
    Region      = var.aws_region
    ManagedBy   = "terraform"
    Hackathon   = "amazon-developer-2026"
  }
}

# 4. HTTPS Lambda Function URL for Fire TV 10-Foot Wallboard
resource "aws_lambda_function_url" "mercury_wallboard_url" {
  function_name      = aws_lambda_function.mercury_wallboard_function.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["GET", "POST", "OPTIONS"]
    allow_headers     = ["content-type", "x-mcp-version"]
    max_age           = 86400
  }
}

output "wallboard_endpoint_url" {
  value       = aws_lambda_function_url.mercury_wallboard_url.function_url
  description = "Public HTTPS endpoint for Amazon Fire TV 10-Foot Wallboard"
}
