# Pure Serverless Terraform Infrastructure for Mercury Voice CTO Cockpit on AWS (eu-west-1)
# Architecture: AWS Lambda + public demo Function URL + DynamoDB durable state

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Provider 6 adds both permissions required for new public Function URLs:
      # InvokeFunctionUrl and InvokeFunction constrained to URL invocations.
      version = "~> 6.0"
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

  validation {
    condition     = var.environment == "prod" || can(regex("^ci-[0-9]+-[0-9]+$", var.environment))
    error_message = "Environment must be prod or the guarded ci-RUN_ID-RUN_ATTEMPT form."
  }
}

variable "lambda_package_path" {
  type        = string
  default     = "../dist/mercury_lambda.zip"
  description = "Path to the built Lambda deployment package"
}

variable "source_revision" {
  type        = string
  description = "Immutable Git commit deployed in the Lambda package"

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase 40-character Git SHA."
  }
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

# 2. Least-privilege policy for the public, fixture-only demo deployment.
# The application can use Cost Explorer and CloudWatch in a separately secured
# operator deployment. This Function URL is anonymous, so its Lambda role must
# not be able to read account telemetry.
resource "aws_iam_policy" "mercury_serverless_policy" {
  name        = "mercury-serverless-policy-euw1-${var.environment}"
  description = "Least privilege state and logging access for the public fixture-only demo"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock-mantle:CreateInference"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
          "arn:aws:bedrock:${var.aws_region}:*:inference-profile/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mercury_attach" {
  role       = aws_iam_role.mercury_lambda_role.name
  policy_arn = aws_iam_policy.mercury_serverless_policy.arn
}

# 3. Explicit log group so a disposable cycle removes every resource it creates.
resource "aws_cloudwatch_log_group" "mercury_lambda_logs" {
  name              = "/aws/lambda/mercury-wallboard-euw1-${var.environment}"
  retention_in_days = 14

  tags = {
    Project     = "mercury"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# 4. AWS Lambda Serverless Wallboard API Function ($0.00 Idle Cost)
resource "aws_lambda_function" "mercury_wallboard_function" {
  function_name    = "mercury-wallboard-euw1-${var.environment}"
  role             = aws_iam_role.mercury_lambda_role.arn
  runtime          = "python3.11"
  handler          = "src.interfaces.lambda_handler.handler"
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)
  memory_size      = 1769
  timeout          = 30

  environment {
    variables = {
      ENVIRONMENT         = var.environment
      MERCURY_BUILD_SHA   = var.source_revision
      MERCURY_STATE_TABLE = aws_dynamodb_table.mercury_state.name
      # Anonymous demo traffic must never read AWS account telemetry or create
      # billable Cost Explorer traffic, regardless of resolved role credentials.
      MERCURY_OFFLINE = "1"
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

# 5. HTTPS Lambda Function URL for Fire TV 10-Foot Wallboard
resource "aws_lambda_function_url" "mercury_wallboard_url" {
  function_name      = aws_lambda_function.mercury_wallboard_function.function_name
  authorization_type = "NONE"

  # Provider 6 also adds these statements during URL creation. Creating the
  # tracked permission resources first is safe because the provider treats the
  # exact duplicate SIDs as already satisfied, while Terraform can still own
  # and remove both statements deterministically.
  depends_on = [
    aws_lambda_permission.mercury_function_url,
    aws_lambda_permission.mercury_function_url_invoke,
  ]

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    # Lambda handles CORS preflight itself. AllowMethods entries are limited to
    # six characters, so the seven-character OPTIONS token is rejected by AWS.
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type", "x-mcp-version"]
    max_age       = 86400
  }
}

# Public Function URLs created after October 2025 require both resource-policy
# permissions. The conditions are emitted by the provider from these dedicated
# arguments, so regular Lambda invocation remains unavailable through this grant.
resource "aws_lambda_permission" "mercury_function_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.mercury_wallboard_function.function_name
  principal              = "*"
  function_url_auth_type = "NONE"

}

resource "aws_lambda_permission" "mercury_function_url_invoke" {
  statement_id             = "FunctionURLAllowInvokeAction"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.mercury_wallboard_function.function_name
  principal                = "*"
  invoked_via_function_url = true

}

output "wallboard_endpoint_url" {
  value       = aws_lambda_function_url.mercury_wallboard_url.function_url
  description = "Public HTTPS endpoint for Amazon Fire TV 10-Foot Wallboard"
}
