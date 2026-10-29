locals {
  oidc_host = replace(aws_iam_openid_connect_provider.this.url, "https://", "")
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------- node-healer (aws-asg-terminate mode)
data "aws_iam_policy_document" "healer_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.this.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["system:serviceaccount:self-healing:node-healer"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node_healer" {
  name               = "${var.name}-node-healer"
  assume_role_policy = data.aws_iam_policy_document.healer_trust.json
}

data "aws_iam_policy_document" "node_healer" {
  statement {
    actions   = ["autoscaling:DescribeAutoScalingInstances", "ec2:DescribeInstances"]
    resources = ["*"]
  }
  statement {
    # Terminate only instances that belong to this cluster's groups.
    actions   = ["autoscaling:TerminateInstanceInAutoScalingGroup"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/eks:cluster-name"
      values   = [var.name]
    }
  }
}

resource "aws_iam_role_policy" "node_healer" {
  name   = "terminate-in-asg"
  role   = aws_iam_role.node_healer.id
  policy = data.aws_iam_policy_document.node_healer.json
}

# ---------------------------------------------------------------- cluster-autoscaler
data "aws_iam_policy_document" "ca_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.this.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["system:serviceaccount:kube-system:cluster-autoscaler"]
    }
  }
}

resource "aws_iam_role" "cluster_autoscaler" {
  name               = "${var.name}-cluster-autoscaler"
  assume_role_policy = data.aws_iam_policy_document.ca_trust.json
}

data "aws_iam_policy_document" "ca" {
  statement {
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribeAutoScalingInstances",
      "autoscaling:DescribeLaunchConfigurations",
      "autoscaling:DescribeScalingActivities",
      "autoscaling:DescribeTags",
      "ec2:DescribeImages",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeLaunchTemplateVersions",
      "ec2:GetInstanceTypesFromInstanceRequirements",
      "eks:DescribeNodegroup",
    ]
    resources = ["*"]
  }
  statement {
    actions   = ["autoscaling:SetDesiredCapacity", "autoscaling:TerminateInstanceInAutoScalingGroup"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/k8s.io/cluster-autoscaler/${var.name}"
      values   = ["owned"]
    }
  }
}

resource "aws_iam_role_policy" "ca" {
  name   = "cluster-autoscaler"
  role   = aws_iam_role.cluster_autoscaler.id
  policy = data.aws_iam_policy_document.ca.json
}
