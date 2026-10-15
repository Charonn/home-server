# Home server setup stuff
Uses ansible to setup a home server with docker and these containers:
- traefik
- paperless
- nextcloud
- grafana
- prometheus
- no-ip
- mariadb
- redis

## Apply to home-server
```bash
ansible-playbook site.yml --private-key=~/.ssh/* --tags home-server --diff --limit proxmox_home_server
```


## En/Decrypt secrets
Secret is stored in .vault_pass
```bash
ansible-vault encrypt group_vars/all/default.vault.yml
ansible-vault decrypt group_vars/all/default.vault.yml
```

## Idle-Power-Reduktion (Rolle `idle_power`, Ziel: `proxmox_ryzen`)

Reduziert den Idle-Verbrauch des PVE-Towers (Ryzen 7 5700G):
CPU-Governor (`schedutil`, persistente systemd-Unit), ZFS-`txg_timeout`
(1800 s, Gate bewusst erzwungen — Marcel-OK), HDD-Spin-Down via `hdparm -B/-S`
(Backup 10 min, Daten 20 min, Boot nie), smartd mit `-n standby,q`
(kein Wecken der HDDs durch den 30-min-Poll). Details: Karte t_15bbb646.

Trockenlauf:
```bash
ansible-playbook site.yml --tags idle_power --limit proxmox_ryzen --check --diff
```

Anwenden:
```bash
ansible-playbook site.yml --tags idle_power --limit proxmox_ryzen
```

Wichtige Defaults (Rolle `roles/idle_power/defaults/main.yml`):
- `idle_power_pool_roles` Pool-Namen aus `zpool list` setzen (backup/boot/data)
- `idle_power_txg_force` nur anpassen, wenn das Crash-Fenster akzeptabel ist

### Backup-Interaktion (verifiziert 2026-10-10)
Das tägliche Backup (`/root/backup/backup.sh` auf der home-server-VM,
01:05, Borg + rclone + MariaDB-Dumps) beschreibt über die VM-Disk-
Passthroughs die Pools **HDD-2TB** (Borg-Repo, `sdb`) und **HDD-Big**
(VM-Rootvol, `/opt`). Ablauf: 01:05 Wecken -> Backup (letzte Dauer
12:32 min) -> +10/20 min parkt der Pool wieder; Rest der Nacht geparkt.
`pool_status.sh` (20:00, Telegram-Report) liest nur RAM-Metadaten und
weckt nicht. Konfliktfrei. smartd weckt dank `-n standby,q` nicht beim
30-min-Poll; Tests laufen, sobald die Platte eh wach ist.

Pool-Rollen sind als Defaults gesetzt: HDD-2TB=backup (10 min),
HDD-Big=data (20 min), SSD-Pool=boot (nie).

## NVIDIA GPU stack (roles: `nvidia_driver`, `steam`)

RTX 3070 Ti on the Proxmox host; consumers on the same version:
- **Proxmox host (`proxmox_ryzen`)**: full driver via official `.run` installer
  (DKMS-free, self-built module), persistence mode, DRM modeset.
- **steam CT 110 (`steam_host`)**: userspace-only extraction from the SAME
  installer cached on the host (no own kernel module — device-node
  passthrough). Managed via `pct exec` from the host.

**Deprecated:** das steam-headless-compose-Stack auf home-server (frühere Rolle
`home_server_gpu`) ist außer Betrieb (Marcel, 2026-10-15) und ist aus diesem
Playbook entfernt; die CT-110-`steam`-Baseline ist der Nachfolger.

**Single source of truth** for the version: `group_vars/all/nvidia_driver.yml`
→ `nvidia_driver_version`. Bump consumers by changing that one variable.
Current pin: `595.99.02` (latest production branch WITH keylase NvFBC patch —
595.104.02 is newer but has no NvFBC patch yet).

Dry-run:
```bash
ansible-playbook site.yml --tags nvidia_driver,steam --limit 'proxmox_ryzen,ryzen_home_server,steam_host' --check --diff
```

Anwenden (host driver upgrade — reboot danach nötig):
```bash
ansible-playbook site.yml --tags nvidia_driver --limit proxmox_ryzen
ansible-playbook site.yml --tags nvidia_driver --limit ryzen_home_server
ansible-playbook site.yml --tags steam --limit steam_host
```

Wichtig: nach dem Host-Reboot die steam-CT- und Container-Neuinstallation
nochmal durchlaufen lassen (`--tags steam,nvidia_driver --limit
'ryzen_home_server,steam_host'`), damit die Userspace-Stacks gegen das neue
Kernel-Modul installieren.

## steam CT 110 Baseline (Rolle `steam`, Tag `steam`)

Manage-Vertrag (PR: nvidia driver + steam host): lokale user `gamer` (uid
1000), `opencode` (1001); systemd-Kette `xorg-virtual → x-compositor →
sunshine/steam-headless` auf Display `:99`; Sunshine mit Auto-Encoder-
Wahl (nvenc, wenn CUDA ok; sonst software-Fallback); `xvfb@10.service`
bleibt MASKIERT (Upstream-dummy-Setup, loopt; siehe Log). Die Rolle
schreibt über `pct exec`/`pct push` vom Proxmox-Host aus — kein
`become` im CT (gamer-Sudo braucht PASSWD).