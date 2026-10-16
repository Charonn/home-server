#!/bin/bash
# Local pre-push gate: secret-leak scan (fast, no ansible needed).
# Optional deeper check: ansible --syntax-check — needs the vault password and
# an ansible install; on CI this already runs against the live hosts.
set -e
cd "$(git rev-parse --show-toplevel)"
echo "== secret-leak scan (scripts/check_secrets.py)"
python3 scripts/check_secrets.py
echo
echo "PASS — safe to push. (Full check-mode run happens in CI ansible-check.)"