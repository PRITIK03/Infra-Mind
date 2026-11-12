"""
Security group resource definitions for LB, compute, database, and cache tiers.
"""
from __future__ import annotations

def _sg_lb(listener_port: str) -> str:
    return f"""\
resource "aws_security_group" "lb" {{
  name        = "${{var.app_name}}-lb-sg"
  description = "Allow inbound traffic on the public load balancer listener."
  vpc_id      = data.aws_vpc.default.id

  ingress {{
    from_port   = {listener_port}
    to_port     = {listener_port}
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name = "${{var.app_name}}-lb-sg"
  }}
}}
"""


_SG_COMPUTE_FROM_LB = """\
resource "aws_security_group" "compute" {
  name        = "${var.app_name}-compute-sg"
  description = "Allow app port only from load balancer security group."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = var.app_port
    to_port         = var.app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.lb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-compute-sg"
  }
}
"""


_SG_COMPUTE_STANDALONE = """\
resource "aws_security_group" "compute" {
  name        = "${var.app_name}-compute-sg"
  description = "Allow app port directly from 0.0.0.0/0 (standalone, no LB)."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-compute-sg"
  }
}
"""


def _sg_db_from_compute(db_port: int) -> str:
    return f"""\
resource "aws_security_group" "db" {{
  name        = "${{var.app_name}}-db-sg"
  description = "Allow RDS port only from compute security group."
  vpc_id      = data.aws_vpc.default.id

  ingress {{
    from_port       = {db_port}
    to_port         = {db_port}
    protocol        = "tcp"
    security_groups = [aws_security_group.compute.id]
  }}

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name = "${{var.app_name}}-db-sg"
  }}
}}
"""


def _sg_cache_from_compute(cache_port: int) -> str:
    return f"""\
resource "aws_security_group" "cache" {{
  name        = "${{var.app_name}}-cache-sg"
  description = "Allow cache port only from compute security group."
  vpc_id      = data.aws_vpc.default.id

  ingress {{
    from_port       = {cache_port}
    to_port         = {cache_port}
    protocol        = "tcp"
    security_groups = [aws_security_group.compute.id]
  }}

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name = "${{var.app_name}}-cache-sg"
  }}
}}
"""
