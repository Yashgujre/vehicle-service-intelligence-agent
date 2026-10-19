# One Always Free Ampere A1 instance (2 OCPU / 12 GB) running Ubuntu 24.04 aarch64 and the Compose stack.

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# The operating_system filter value "Canonical Ubuntu" is widely used but not confirmed in Oracle docs
# (research section 8.2). Confirm with:
#   oci compute image list -c <compartment> --operating-system "Canonical Ubuntu" --shape VM.Standard.A1.Flex
# The display_name filter excludes the Minimal variant.
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "display_name"
    values = ["^Canonical-Ubuntu-24\\.04-aarch64-.*"]
    regex  = true
  }
}

locals {
  ads                 = data.oci_identity_availability_domains.ads.availability_domains
  availability_domain = local.ads[var.availability_domain_index % length(local.ads)].name
  image_id            = coalesce(var.image_ocid, try(data.oci_core_images.ubuntu_arm.images[0].id, null))

  cloud_init = templatefile("${path.module}/cloud-init.yaml", {
    repo_url = var.repo_url
    repo_ref = var.repo_ref
  })
}

resource "oci_core_instance" "app" {
  availability_domain = local.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = "vsia-app"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_id
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
    hostname_label   = "vsia-app"
  }

  # Secrets are deliberately not placed in metadata (visible in the console and in state);
  # scripts/deploy_vm.sh copies infra/compose/.env over SSH instead (ADR-0085).
  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data           = base64encode(local.cloud_init)
  }

  lifecycle {
    # A newer image or edited cloud-init must not silently replace a running VM and its volumes.
    ignore_changes = [source_details[0].source_id, metadata["user_data"]]
  }
}
