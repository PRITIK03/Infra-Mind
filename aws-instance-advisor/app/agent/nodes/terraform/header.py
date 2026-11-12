"""
Terraform provider, data source headers, warning blocks, and comment helpers.
"""
from __future__ import annotations

AWS_PROVIDER_VERSION = ">= 5.73.0"

_AI_WARNING_BLOCK = """\
/*
 * ============================================================
 *  AI-GENERATED INFRASTRUCTURE CODE
 * ============================================================
 *
 *  This Terraform configuration was generated automatically by
 *  aws-instance-advisor as a STARTING POINT, not a final
 *  deployment.
 *
 *  The template assumes the account's default VPC and a stock
 *  Amazon Linux 2023 image. Before applying, configure the network,
 *  workload bootstrap, TLS, IAM, scaling policies, and monitoring.
 *  Review resource availability, costs, and the Terraform plan in
 *  the target AWS account and region.
 * ============================================================
 */
"""


def _header(compute_instance: str) -> str:
    return f"""\
terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "{AWS_PROVIDER_VERSION}"
    }}
  }}
}}

provider "aws" {{
  region = var.aws_region
}}

data "aws_vpc" "default" {{
  default = true
}}

data "aws_subnets" "default" {{
  filter {{
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }}

  filter {{
    name   = "default-for-az"
    values = ["true"]
  }}
}}

data "aws_ec2_instance_type" "app" {{
  instance_type = "{compute_instance}"
}}

data "aws_ami" "app" {{
  most_recent = true
  owners      = ["amazon"]

  filter {{
    name   = "name"
    values = ["al2023-ami-2023.*"]
  }}

  filter {{
    name   = "architecture"
    values = data.aws_ec2_instance_type.app.supported_architectures
  }}
}}
"""


def _comment_block(text: str) -> str:
    return "\n".join(f"# {line}" if line else "#" for line in text.splitlines())
