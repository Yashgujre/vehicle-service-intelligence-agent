# Terraform: OCI Always Free VM and Pinecone index

This module creates everything the cloud deployment needs outside Docker:

- an OCI network (VCN, internet gateway, route table, security list, public subnet);
- one `VM.Standard.A1.Flex` instance with 2 OCPUs and 12 GB of memory (the whole Always Free A1
  allowance since about 2026-06-15) running Ubuntu 24.04 aarch64, bootstrapped by `cloud-init.yaml`;
- the Pinecone integrated-embedding index (`llama-text-embed-v2`, `field_map text = chunk_text`, AWS
  `us-east-1`).

Provider versions and resource names come from `docs/research/02_technical_verification.md` sections
4.3 and 8. The deployment view is in `docs/architecture/deployment.md`.

## Files

| File | Purpose |
|---|---|
| `versions.tf` | Terraform and provider pins (`oracle/oci ~> 9.10`, `pinecone-io/pinecone ~> 5.0`), provider blocks |
| `variables.tf` | Inputs, with validation that keeps the instance inside the Always Free allowance |
| `network.tf` | VCN, gateway, route table, security list (22 from `admin_cidr` only; 80 and 443 public), subnet |
| `compute.tf` | Ubuntu image lookup and the A1 instance |
| `cloud-init.yaml` | First-boot script: Docker, Compose plugin, swap, host firewall, repository clone |
| `pinecone.tf` | Pinecone index |
| `outputs.tf` | Public IP, SSH command, host names for `infra/compose/.env`, URLs |
| `terraform.tfvars.example` | Copy to `terraform.tfvars` |

## Prerequisites

1. An OCI account, with an API signing key uploaded for your user (Profile, API keys). Note the tenancy
   OCID, user OCID, fingerprint and home region.
2. Terraform 1.6 or newer.
3. A Pinecone Starter project and its API key, exported as `PINECONE_API_KEY`.
4. An SSH key pair (`~/.ssh/id_ed25519.pub` by default).

## Apply

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars      # fill in OCIDs, region, admin_cidr
export PINECONE_API_KEY=...                       # never put it in tfvars
terraform init
terraform plan -out tfplan
terraform apply tfplan
terraform output
```

Then deploy the stack from the repository root:

```bash
cp infra/compose/.env.example infra/compose/.env  # fill in secrets; copy host names from `terraform output compose_hostnames`
scripts/deploy_vm.sh "$(terraform -chdir=infra/terraform output -raw public_ip)"
```

Cloud-init takes a few minutes. Check progress with `ssh ubuntu@<ip> cloud-init status --wait`.

## "Out of host capacity"

Always Free A1 capacity is often exhausted in popular regions. The apply then fails on
`oci_core_instance.app` with `500-InternalError, Out of host capacity`. The network resources are kept,
so only the instance needs to be retried:

1. Set `availability_domain_index = 1` (then 2) in `terraform.tfvars` and apply again. Regions with one
   availability domain wrap around to index 0.
2. Retry later; capacity frees up during the day. A simple loop:
   `until terraform apply -auto-approve; do sleep 300; done`
3. Temporarily ask for less (`instance_ocpus = 1`, `instance_memory_gbs = 6`) and scale up later.
   `shape_config` is updatable in place, but the Compose memory limits assume 12 GB; see
   `docs/operations/runbooks/vm-out-of-capacity.md`.

## Pinecone index ownership

`vsia.retrieval.PineconeStore` also creates the index when it is missing. If the API or a notebook
created it first, import it rather than letting Terraform fail on a name conflict:

```bash
terraform import 'pinecone_index.vsia[0]' vsia
```

Set `manage_pinecone_index = false` to leave the index entirely to the application. `terraform destroy`
deletes the index and all records in it.

## State stays local

State lives in `infra/terraform/terraform.tfstate`, which is gitignored (ADR-0084). One person manages one
small free-tier environment, so a remote backend (OCI Object Storage) adds setup without a collaborator
who needs it. The state contains OCIDs and the instance's public IP but no API keys, because the Pinecone
key comes from the environment and no secret is written to instance metadata. Back the state file up
(for example to a password manager attachment) after every apply; losing it means importing resources
by hand.

## Validation status

- `terraform fmt -check`: see the latest result in `docs/architecture/deployment.md` (verified list).
- `terraform validate` and `plan` need the providers downloaded. The OCI provider is several hundred MB
  and was not downloaded on the development laptop (disk constraint, ADR-0008), so the module has been
  format-checked only. Run `terraform init && terraform validate` on a machine with free disk before the
  first apply.
- Not verified against Oracle docs: the image filter value `"Canonical Ubuntu"` and the need to open host
  iptables for 80 and 443.
