variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "name" {
  description = "Cluster name / resource prefix"
  type        = string
  default     = "self-healing-demo"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "node_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

variable "node_min_size" {
  type    = number
  default = 3
}

variable "node_desired_size" {
  type    = number
  default = 3
}

variable "node_max_size" {
  type    = number
  default = 6
}

variable "enable_node_auto_repair" {
  description = "EKS managed node group auto repair (replaces nodes that fail EKS/NPD health signals)"
  type        = bool
  default     = true
}

variable "enable_self_managed_asg" {
  description = "Also create a self-managed ASG node pool that demonstrates ASG health checks + instance refresh"
  type        = bool
  default     = false
}

variable "single_nat_gateway" {
  description = "One NAT gateway keeps the demo cheap; set false for one per AZ (production)"
  type        = bool
  default     = true
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public API endpoint. Restrict this to your IP!"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
