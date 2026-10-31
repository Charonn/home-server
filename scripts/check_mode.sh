#!/bin/bash
# CHECK-MODE-ONLY ansible run against the real hosts — NEVER applies changes.
#
# Marcel's standing rule (2026-10-16): check-mode against real hosts is allowed,
# real runs from agent contexts are not. This script hard-codes --check and
# refuses to run without it, so neither caller nor alias can accidentally apply.
#
# Usage: scripts/check_mode.sh ['proxmox_ryzen,ryzen_home_server']
# Needs: .vault_pass in repo root (gitignored), ansible + collections installed,
#        SSH policy that admits this node (tailscale ssh section).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

LIMIT="${1:-proxmox_ryzen,ryzen_home_server}"

guard() {
  # paranoia: verify --check is in the exact command we are about to exec
  local cmd="ansible-playbook site.yml --check --diff --limit $LIMIT"
  [[ "$cmd" == *"--check "* ]] || { echo "GUARD: --check missing, refusing"; exit 3; }
  echo "CHECK-MODE-ONLY: $cmd"
  ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook site.yml --check --diff --limit "$LIMIT"
}
guard