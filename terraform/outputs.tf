output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "update_kubeconfig" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${aws_eks_cluster.this.name}"
}

output "node_healer_role_arn" {
  description = "Put this in the eks overlay's ServiceAccount annotation"
  value       = aws_iam_role.node_healer.arn
}

output "cluster_autoscaler_role_arn" {
  value = aws_iam_role.cluster_autoscaler.arn
}
