data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name}-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore", # shell access without SSH
  ])
  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# Managed node group = an EC2 Auto Scaling group that EKS creates and keeps healthy.
#  * The ASG replaces instances that fail EC2 status checks.
#  * node_repair_config lets EKS replace/reboot nodes that stay NotReady or report
#    node-problem-detector conditions (see docs/node-healing.md).
#  * update_config bounds how many nodes may be unavailable during AMI/version upgrades.
resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = module.vpc.private_subnets # 3 AZs => ASG rebalances across zones

  instance_types = var.node_instance_types
  capacity_type  = "ON_DEMAND"
  ami_type       = "AL2023_x86_64_STANDARD"
  disk_size      = 30

  scaling_config {
    min_size     = var.node_min_size
    desired_size = var.node_desired_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  node_repair_config {
    enabled = var.enable_node_auto_repair
  }

  labels = { "node-pool" = "default" }

  # Cluster Autoscaler auto-discovery tags (propagated to the ASG).
  tags = {
    "k8s.io/cluster-autoscaler/enabled"     = "true"
    "k8s.io/cluster-autoscaler/${var.name}" = "owned"
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size] # the autoscaler owns desired_size
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}
