# --- OCI identity (see terraform.tfvars.example) ---

variable "tenancy_ocid" {
  description = "Tenancy OCID. Also used to list availability domains."
  type        = string
}

variable "user_ocid" {
  description = "API signing user OCID. Null falls back to ~/.oci/config."
  type        = string
  default     = null
}

variable "fingerprint" {
  description = "API signing key fingerprint. Null falls back to ~/.oci/config."
  type        = string
  default     = null
}

variable "private_key_path" {
  description = "Path to the API signing private key (PEM). Null falls back to ~/.oci/config."
  type        = string
  default     = null
}

variable "region" {
  description = "Home region (Always Free A1 capacity exists only in the home region), for example us-ashburn-1."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment for every resource. The tenancy OCID (root compartment) works for a personal account."
  type        = string
}

# --- Network ---

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH (22), for example your home IP as x.x.x.x/32. Never 0.0.0.0/0."
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a valid CIDR and must not be 0.0.0.0/0."
  }
}

variable "vcn_cidr" {
  description = "VCN address space."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "Public subnet address space."
  type        = string
  default     = "10.0.1.0/24"
}

# --- Compute ---

variable "instance_ocpus" {
  description = "A1 OCPUs. The Always Free allowance is 2 OCPUs in total (since about 2026-06-15)."
  type        = number
  default     = 2

  validation {
    condition     = var.instance_ocpus >= 1 && var.instance_ocpus <= 2
    error_message = "Stay inside the Always Free allowance: 1 or 2 OCPUs."
  }
}

variable "instance_memory_gbs" {
  description = "A1 memory in GB. The Always Free allowance is 12 GB in total."
  type        = number
  default     = 12

  validation {
    condition     = var.instance_memory_gbs >= 6 && var.instance_memory_gbs <= 12
    error_message = "Stay inside the Always Free allowance: 6 to 12 GB."
  }
}

variable "boot_volume_gbs" {
  description = "Boot volume size. Minimum 50 GB; Always Free covers 200 GB of block storage in total."
  type        = number
  default     = 100
}

variable "availability_domain_index" {
  description = "Which availability domain to use (0-based). Change it when apply fails with 'Out of host capacity'."
  type        = number
  default     = 0
}

variable "image_ocid" {
  description = "Optional explicit image OCID. Null looks up the newest Canonical Ubuntu 24.04 aarch64 image."
  type        = string
  default     = null
}

variable "ssh_public_key_path" {
  description = "Public key installed for the ubuntu user."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "repo_url" {
  description = "Git URL cloned by cloud-init into /opt/vsia. Empty skips the clone (deploy_vm.sh can rsync instead)."
  type        = string
  default     = ""
}

variable "repo_ref" {
  description = "Branch or tag checked out by cloud-init."
  type        = string
  default     = "main"
}

variable "domain" {
  description = "Optional DNS zone you control (chat.<domain>, n8n.<domain>, api.<domain>). Empty uses <ip>.sslip.io names."
  type        = string
  default     = ""
}

# --- Pinecone ---

variable "manage_pinecone_index" {
  description = "Create the Pinecone integrated-embedding index with Terraform (needs PINECONE_API_KEY in the environment)."
  type        = bool
  default     = true
}

variable "pinecone_index_name" {
  description = "Index name. Must match PINECONE_INDEX in the API environment (default vsia)."
  type        = string
  default     = "vsia"
}
