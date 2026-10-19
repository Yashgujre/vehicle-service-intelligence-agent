#!/usr/bin/env bash
# Push the repository and infra/compose/.env to the OCI VM and (re)start the Compose stack.
# Idempotent: safe to run after every change.
#
#   scripts/deploy_vm.sh <vm-ip-or-host> [--no-sync] [--no-build]
#
#   --no-sync    do not rsync the working tree (use when cloud-init cloned the repo; runs git pull instead)
#   --no-build   restart without rebuilding the API image (for .env-only changes)
#
# Environment: SSH_USER (default ubuntu), SSH_KEY (optional identity file), REMOTE_DIR (default /opt/vsia).
# Secrets travel only over SSH; they are never written to instance metadata or Terraform state (ADR-0085).

set -euo pipefail

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[[ $# -ge 1 ]] || usage

HOST="$1"; shift
SYNC=1
BUILD=1
for arg in "$@"; do
  case "$arg" in
    --no-sync) SYNC=0 ;;
    --no-build) BUILD=0 ;;
    *) usage ;;
  esac
done

SSH_USER="${SSH_USER:-ubuntu}"
REMOTE_DIR="${REMOTE_DIR:-/opt/vsia}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/infra/compose/.env"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
[[ -n "${SSH_KEY:-}" ]] && SSH_OPTS+=(-i "$SSH_KEY")
TARGET="$SSH_USER@$HOST"

log() { printf '[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
remote() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }

[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (copy infra/compose/.env.example and fill it in)" >&2; exit 1; }
if grep -qE '=change-me' "$ENV_FILE"; then
  echo "refusing to deploy: $ENV_FILE still contains change-me placeholders" >&2
  exit 1
fi

log "waiting for cloud-init on $HOST"
remote 'cloud-init status --wait >/dev/null 2>&1 || true; command -v docker >/dev/null && docker compose version >/dev/null'

remote "sudo mkdir -p '$REMOTE_DIR' && sudo chown '$SSH_USER':'$SSH_USER' '$REMOTE_DIR'"

if [[ $SYNC -eq 1 ]]; then
  log "syncing working tree to $REMOTE_DIR"
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' --exclude 'data/*.db' --exclude 'data/mlartifacts/' --exclude 'data/docs/' \
    --exclude 'data/index/' --exclude 'data/processed/' --exclude 'mlruns/' \
    --exclude 'infra/terraform/.terraform/' --exclude 'infra/terraform/*.tfstate*' \
    --exclude 'infra/terraform/terraform.tfvars' --exclude 'infra/compose/.env' \
    "$REPO_ROOT/" "$TARGET:$REMOTE_DIR/"
else
  log "pulling latest commit in $REMOTE_DIR"
  remote "cd '$REMOTE_DIR' && git pull --ff-only"
fi

log "copying .env (mode 600)"
scp "${SSH_OPTS[@]}" -q "$ENV_FILE" "$TARGET:$REMOTE_DIR/infra/compose/.env"
remote "chmod 600 '$REMOTE_DIR/infra/compose/.env' && rm -f '$REMOTE_DIR/CLOUD_INIT_WAITING_FOR_ENV'"

UP_ARGS="up -d --remove-orphans"
[[ $BUILD -eq 1 ]] && UP_ARGS="$UP_ARGS --build"
log "docker compose $UP_ARGS"
remote "cd '$REMOTE_DIR/infra/compose' && docker compose config --quiet && docker compose $UP_ARGS"

# Copy model artifacts (gitignored, excluded from the image): routing thresholds, per-provider confidence
# calibrators and the component classifier. Without them the API runs on fallback confidence weights and
# routes almost everything to review.
shopt -s nullglob
routing=("$REPO_ROOT"/data/models/routing_*.json "$REPO_ROOT"/data/models/*.joblib)
if [[ ${#routing[@]} -gt 0 ]]; then
  log "copying ${#routing[@]} model artifact file(s) into the API volume"
  scp "${SSH_OPTS[@]}" -q "${routing[@]}" "$TARGET:/tmp/"
  for f in "${routing[@]}"; do
    name="$(basename "$f")"
    remote "cd '$REMOTE_DIR/infra/compose' && docker compose cp '/tmp/$name' vsia-api:/app/data/models/'$name' && rm -f '/tmp/$name'"
  done
fi

log "service status"
remote "cd '$REMOTE_DIR/infra/compose' && docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'"
log "done. API health (internal): docker compose exec vsia-api python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health').read())\""
