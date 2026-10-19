# Provider versions verified 2026-10-18 (docs/research/02_technical_verification.md sections 4.3 and 8.2).
# State is local and gitignored (ADR-0084).

terraform {
  required_version = ">= 1.6"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.10"
    }
    pinecone = {
      source  = "pinecone-io/pinecone"
      version = "~> 5.0"
    }
  }
}

# OCI API-key auth. Leave the variables null to fall back to ~/.oci/config (profile DEFAULT).
provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

# Reads PINECONE_API_KEY from the environment; the key is never stored in tfvars.
provider "pinecone" {}
