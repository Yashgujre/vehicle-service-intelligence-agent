locals {
  public_ip = oci_core_instance.app.public_ip
  zone      = var.domain != "" ? var.domain : "${replace(local.public_ip, ".", "-")}.sslip.io"
}

output "public_ip" {
  description = "VM public IP."
  value       = local.public_ip
}

output "ssh" {
  description = "SSH command (allowed only from admin_cidr)."
  value       = "ssh ubuntu@${local.public_ip}"
}

output "availability_domain" {
  description = "Availability domain the instance landed in."
  value       = local.availability_domain
}

output "image_id" {
  description = "Image used for the boot volume."
  value       = local.image_id
}

output "compose_hostnames" {
  description = "Values for CHAT_FQDN, N8N_FQDN and API_FQDN in infra/compose/.env."
  value = {
    CHAT_FQDN = "chat.${local.zone}"
    N8N_FQDN  = "n8n.${local.zone}"
    API_FQDN  = "api.${local.zone}"
  }
}

output "urls" {
  description = "Public URLs once Caddy has issued certificates."
  value = {
    chat       = "https://chat.${local.zone}"
    n8n        = "https://n8n.${local.zone}"
    api_health = "https://api.${local.zone}/health"
    mlflow     = "ssh -L 5000:127.0.0.1:5000 ubuntu@${local.public_ip}, then http://localhost:5000"
  }
}

output "pinecone_index_name" {
  description = "Pinecone index name (set PINECONE_INDEX to this)."
  value       = var.manage_pinecone_index ? pinecone_index.vsia[0].name : var.pinecone_index_name
}
