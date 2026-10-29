# Optional (enable_self_managed_asg = true): a self-managed node pool that shows the *raw* ASG
# self-healing knobs that EKS managed node groups hide:
#   - health_check_type + grace period  => ASG terminates & replaces instances that fail health checks
#   - instance_refresh                  => rolling replacement when the launch template changes
#   - capacity_rebalance                => proactive replacement of Spot instances at risk
# Nodes join through EKS access entries + nodeadm user data (AL2023).

data "aws_ssm_parameter" "al2023" {
  count = var.enable_self_managed_asg ? 1 : 0
  name  = "/aws/service/eks/optimized-ami/${var.kubernetes_version}/amazon-linux-2023/x86_64/standard/recommended/image_id"
}

resource "aws_eks_access_entry" "self_managed" {
  count         = var.enable_self_managed_asg ? 1 : 0
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_iam_role.node.arn
  type          = "EC2_LINUX"
}

resource "aws_launch_template" "self_managed" {
  count         = var.enable_self_managed_asg ? 1 : 0
  name_prefix   = "${var.name}-selfmanaged-"
  image_id      = data.aws_ssm_parameter.al2023[0].value
  instance_type = var.node_instance_types[0]

  iam_instance_profile {
    name = aws_iam_instance_profile.node[0].name
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2
  }

  user_data = base64encode(<<-EOT
    MIME-Version: 1.0
    Content-Type: multipart/mixed; boundary="BOUNDARY"

    --BOUNDARY
    Content-Type: application/node.eks.aws

    ---
    apiVersion: node.eks.aws/v1alpha1
    kind: NodeConfig
    spec:
      cluster:
        name: ${aws_eks_cluster.this.name}
        apiServerEndpoint: ${aws_eks_cluster.this.endpoint}
        certificateAuthority: ${aws_eks_cluster.this.certificate_authority[0].data}
        cidr: ${aws_eks_cluster.this.kubernetes_network_config[0].service_ipv4_cidr}
    --BOUNDARY--
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name                                = "${var.name}-selfmanaged"
      "eks:cluster-name"                  = var.name
      "kubernetes.io/cluster/${var.name}" = "owned"
    }
  }
}

resource "aws_iam_instance_profile" "node" {
  count = var.enable_self_managed_asg ? 1 : 0
  name  = "${var.name}-selfmanaged"
  role  = aws_iam_role.node.name
}

resource "aws_autoscaling_group" "self_managed" {
  count               = var.enable_self_managed_asg ? 1 : 0
  name                = "${var.name}-selfmanaged"
  min_size            = 1
  desired_capacity    = 1
  max_size            = 3
  vpc_zone_identifier = module.vpc.private_subnets

  # EC2 = replace on failed instance/system status checks. (Use "ELB" when the group is behind a target group.)
  health_check_type         = "EC2"
  health_check_grace_period = 300
  capacity_rebalance        = true

  launch_template {
    id      = aws_launch_template.self_managed[0].id
    version = aws_launch_template.self_managed[0].latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 66
      instance_warmup        = 120
    }
  }

  tag {
    key                 = "k8s.io/cluster-autoscaler/enabled"
    value               = "true"
    propagate_at_launch = true
  }
  tag {
    key                 = "k8s.io/cluster-autoscaler/${var.name}"
    value               = "owned"
    propagate_at_launch = true
  }
  tag {
    key                 = "eks:cluster-name"
    value               = var.name
    propagate_at_launch = true
  }
}
