#!/usr/bin/env python3
"""Ansible repo secret-leak scanner (local CI gate — the CI --diff leak class).

Why: CI runs `ansible-playbook --check --diff`, which prints the full RENDER of
every template whose file would change. A rendered file leaks a credential the
moment a template inlines a secret var — that is exactly how MYSQL_PWD and
BORG_PASSPHRASE landed in public CI logs (runs 38755625627 + 38170084049).

What this script enforces (three-tier model):
  Tier CREDS (FAIL): credential variables — !vault literals, *_vault names,
     exact "{{ ..._vault }}" chains, and any var whose NAME matches a
     credential pattern (password/passphrase/token/key/secret/access_key/...).
     Rendering a CREDS var into a template FAILS unless the task deploying
     that template runs with no_log: true (derived from the tasks).
  Tier SOFT (report only): vault-managed but non-credential values (paths,
     versions, usernames, emails, log paths, hostnames). Rendering them is
     reported for the follow-up card, never fails the gate.
  Tier HARDCODED (FAIL): literal secret formats (tskey-auth-, AKIA, ghp_, ...)
     anywhere outside group_vars; long opaque blobs are manual-review warnings.

Exit 0 = pass (soft/guarded items may be listed), exit 1 = FAIL findings,
exit 2 = usage/IO error.
Pure stdlib; no ansible installation needed — runs in <1 s.
"""
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- config
GENERIC_NAME_RE = re.compile(
    r"(password|passwd|passphrase|_pass_|_token|authkey|auth_key|"
    r"api_key|apikey|_secret|_creds|_credential|access_key|bot_token)"
)
HARDCODED_RE = re.compile(
    r"(tskey-auth-[A-Za-z0-9]|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]|xox[bap]-[A-Za-z0-9-]{10,})"
)
BLOB_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{43,}\b")
BLOB_ALLOW = ("$ANSIBLE_VAULT", "-----BEGIN")

JINJA_RE = re.compile(r"\{\{[^}]*\}\}")
REPO_ROOT = Path(__file__).resolve().parent.parent

# Path-prefix allow-list: findings whose relative path starts with one of these
# entries are reported as KNOWN-FOLLOWUP, not FAIL. Every entry must map to an
# open kanban card. Do NOT add entries to silence real regressions.
ALLOW_FILE = REPO_ROOT / ".check_secrets_allow"


def load_path_allow() -> list:
    if not ALLOW_FILE.exists():
        return []
    out = []
    for line in ALLOW_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def find_files(pattern: str, exclude_dir_parts=("group_vars", ".git")):
    for p in REPO_ROOT.rglob(pattern):
        if any(part in exclude_dir_parts for part in p.parts):
            continue
        if p.is_file():
            yield p


def definition_scope_files():
    """Files where variables are DEFINED (not used): group_vars, role defaults/vars.
    Scanning tasks too produced false secret names from compose/dict keys."""
    files = []
    files += list((REPO_ROOT / "group_vars").rglob("*.yml"))
    files += list((REPO_ROOT / "group_vars").rglob("*.yaml"))
    for sub in ("defaults", "vars"):
        files += list((REPO_ROOT / "roles").glob(f"*/{sub}/*.yml"))
        files += list((REPO_ROOT / "roles").glob(f"*/{sub}/*.yaml"))
    return [f for f in files if f.is_file()]


# ------------------------------------------------- 1) secret-var derivation
def derive_secret_names():
    """Returns (creds, soft): credential var names that must never render into
    logs, and vault-managed-but-non-credential names (paths/versions/...) that
    are reported only."""
    names = set()
    # exact vault-chain value: the WHOLE value is one Jinja expr referencing *_vault
    chain_value_re = re.compile(r'^\s*"?\'?\{\{[^}]*_vault[^}]*\}\}"?\'?\s*$')
    var_def_re = re.compile(r"^\s*([A-Za-z0-9_]+):\s*", re.M)
    for f in definition_scope_files():
        text = f.read_text(errors="replace")
        for m in re.finditer(r"^([A-Za-z0-9_]+):\s*(?:\n.*)?!vault\s*\|", text, re.M):
            names.add(m.group(1))
        # value is EXACTLY a Jinja chain to a *_vault var (no dict keys, no prose)
        for line in text.splitlines():
            kv = re.match(r"^\s*-?\s*([A-Za-z0-9_]+):\s*(.+)$", line)
            if kv and chain_value_re.match(kv.group(0)[kv.group(0).index(":") + 1:]):
                names.add(kv.group(1))
        # name of a var DEFINED ending in _vault
        for m in var_def_re.finditer(text):
            if m.group(1).endswith("_vault"):
                names.add(m.group(1))
        # generic high-risk names defined in definition scope
        for m in var_def_re.finditer(text):
            if GENERIC_NAME_RE.search(m.group(1)):
                names.add(m.group(1))
    creds = {n for n in names if GENERIC_NAME_RE.search(n) or n.endswith("_vault")}
    soft = names - creds
    return creds, soft


# --------------------------------------------- 2) no_log allow-derivation
def derive_no_log_templates() -> set:
    """Template basenames deployed by a task block that carries no_log: true."""
    allowed = set()
    for f in find_files("*.yml"):
        text = f.read_text(errors="replace")
        # split into task blocks at '- name:'
        blocks = re.split(r"(?=^\s*-\s+name:)", text, flags=re.M)
        for block in blocks:
            if "no_log: true" in block:
                for m in re.finditer(r"src:\s*([A-Za-z0-9_./-]+\.j2)", block):
                    allowed.add(Path(m.group(1)).name)
    return allowed


# ------------------------------------------------------------ main checks
def main() -> int:
    creds, soft = derive_secret_names()
    allow = derive_no_log_templates()
    path_allow = load_path_allow()
    findings = []
    warnings = []
    followups = []

    def classify(rel, lineno, hits, excused):
        item = f"{rel}:{lineno}: secret var(s) {sorted(hits)} rendered into file output"
        if excused:
            return  # deployed by a no_log: true task — by-contract safe
        if any(str(rel).startswith(a) or str(rel) == a for a in path_allow):
            followups.append(item + "  [allow-listed]")
        else:
            findings.append(item + "  [NOT no_log-guarded -> LEAK]")

    for f in find_files("*.j2"):
        rel = f.relative_to(REPO_ROOT)
        text = f.read_text(errors="replace")
        excused = f.name in allow
        for lineno, line in enumerate(text.splitlines(), 1):
            for expr in JINJA_RE.findall(line):
                hit_creds = {s for s in creds if re.search(rf"\b{re.escape(s)}\b", expr)}
                hit_soft = {s for s in soft if re.search(rf"\b{re.escape(s)}\b", expr)}
                if hit_creds:
                    classify(rel, lineno, hit_creds, excused)
                elif hit_soft:
                    followups.append(
                        f"{rel}:{lineno}: vault-managed non-credential var(s) "
                        f"{sorted(hit_soft)} rendered (env-file follow-up)")
            hm = HARDCODED_RE.search(line)
            if hm:
                item = f"{rel}:{lineno}: hardcoded secret pattern: {hm.group(0)[:12]}..."
                (followups if any(str(rel).startswith(a) for a in path_allow)
                 else findings).append(item)

    for f in find_files("*.yml"):
        rel = f.relative_to(REPO_ROOT)
        if "group_vars" in rel.parts:
            continue  # vault blobs live here by design
        for lineno, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            allowed_path = any(str(rel).startswith(a) or str(rel) == a for a in path_allow)
            hm = HARDCODED_RE.search(line)
            if hm:
                item = f"{rel}:{lineno}: hardcoded secret pattern: {hm.group(0)[:12]}..."
                (followups if allowed_path else findings).append(item)
            if BLOB_RE.search(line) and not any(a in line for a in BLOB_ALLOW):
                if re.fullmatch(r"[0-9a-f]{43,}", line.strip().split(":")[0]) or \
                   re.fullmatch(r"[0-9a-f]+", re.sub(r"[^\w]", "", line).lower()):
                    continue  # hex checksum/digest lines, not secrets
                warnings.append(f"{rel}:{lineno}: long opaque blob (verify manually)")

    print(f"scanner: {len(creds)} credentials, {len(soft)} vault-managed non-creds, "
          f"{len(allow)} no_log-guarded templates")
    if not creds:
        print("scanner: WARNING — no credential vars derived (vault layer missing?)")
    if warnings:
        print(f"manual-review ({len(warnings)}):")
        for x in warnings:
            print("  ? " + x)
    if followups:
        print(f"KNOWN-FOLLOWUP ({len(followups)} — allow-listed in .check_secrets_allow):")
        for x in followups:
            print("  ~ " + x)
    if findings:
        print(f"FAIL: {len(findings)} finding(s):")
        for x in findings:
            print("  " + x)
        return 1
    print("PASS: no secret vars rendered by any template outside no_log-guarded files")
    return 0


if __name__ == "__main__":
    sys.exit(main())