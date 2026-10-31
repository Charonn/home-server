# Home server setup stuff
Uses ansible to setup a home server with docker and these containers:
- traefik
- paperless
- nextcloud
- grafana
- prometheus
- mariadb
- redis
- steam-headless (remote gaming: Steam + Sunshine/Moonlight, on `ryzen_home_server` LXC)

## Apply to home-server
```bash
ansible-playbook site.yml --private-key=~/.ssh/* --tags home-server --diff --limit proxmox_home_server
```

## Steam Headless (remote gaming)

Deployed as `josh5/steam-headless` to the `home-server` LXC (id 102) on the
`proxmox_ryzen` host with NVIDIA GTX 1050 Ti GPU passthrough. Provides:

- **Moonlight/Sunshine** for low-latency game streaming (enabled)
- noVNC web UI on `http://home-server.shark-scylla.ts.net:8083` and via the
  Tailscale sidecar at `https://steam-headless.shark-scylla.ts.net`
- Steam Remote Play (host networking)

Note: the Tailscale sidecar serves the **web UI** only. Moonlight streaming
requires direct UDP to the LXC, so it connects to
`home-server.shark-scylla.ts.net` (or the LAN IP), not via the sidecar.

The playbook fully automates the setup:
1. `proxmox_host` role (runs on `proxmox_ryzen`): ensures the `home-server` LXC
   (id 102) exists — **only if it is missing** (never recreated) —, applies
   `/dev/fuse` + `/dev/uinput` device passthrough and cgroup device allows to
   `/etc/pve/lxc/102.conf` and restarts the container **only when this config
   changed** (needed once).
2. `home-server` role on the LXC: registers the NVIDIA container runtime with
   Docker (`nvidia-ctk runtime configure`), deploys the compose stack.

Secrets (desktop password, Sunshine credentials, paths, image version) are in
the vault, mapped via `group_vars/ryzen_home_server/all.yml`.

Apply the LXC provisioning (device passthrough config on the Proxmox host):
```bash
ansible-playbook site.yml --tags home-server --diff --limit proxmox_ryzen
```
Apply the Steam Headless application on the LXC:
```bash
ansible-playbook site.yml --tags steam-headless --diff --limit ryzen_home_server
```
Dry run (no changes applied):
```bash
ansible-playbook site.yml --check --diff --limit proxmox_ryzen,ryzen_home_server
```


## En/Decrypt secrets
Secret is stored in .vault_pass
```bash
ansible-vault encrypt group_vars/all/default.vault.yml
ansible-vault decrypt group_vars/all/default.vault.yml
```

## Idle-Power-Reduktion (Rolle `idle_power`, Ziel: `proxmox_ryzen`)

Reduziert den Idle-Verbrauch des PVE-Towers (Ryzen 7 5700G):
CPU-Governor (`schedutil`, persistente systemd-Unit), HDD-Spin-Down via
`hdparm -B/-S` (Daten 10 min; Pools ohne Eintrag in `idle_power_pool_roles`
bekommen den `data`-Fallback), smartd mit `-n standby,q` (kein Wecken der
HDDs durch den 30-min-Poll). ZFS-TXG-Batching auf dem Proxmox-Host ist
zurückgenommen: der frühere **globale** Modul-Param (txg=1800 via tmpfiles.d)
traf auch SSD-Pool (LXC-Rootfs) und blockierte docker in jedem LXC
(hung-task in zfs_freesp/zfs_setattr) — auf dem Host revertiert
(txg=5, fixup.md 2026-10-27). Die Rolle schreibt das globale Modul-Param
nie wieder: sie entfernt Legacy-Dateien (`/etc/tmpfiles.d/zfs-txg-idle.conf*`)
self-healing und setzt Txg-Batching nur noch **per Pool** (`zpool set
txg_timeout`) — das existiert erst ab OpenZFS 2.3 (PVE 9), auf 2.2.x meldet
der Lauf SKIP und ändert nichts. Mischpools mit SSD-Membern ausgeschlossen.
Die `idle-spin`-Unit fällt per `Restart=on-failure`/`RestartSec=15`
fail-soft aus, wenn eine HDD beim Boot noch nicht enumeriert ist
(fixup.md Phase 9b).

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
- `idle_power_txg_pools_timeout` = Sekunden pro reiner HDD-Pool (default 1800);
  `idle_power_txg_pools_enable: false` schaltet das Batching komplett aus

### Backup-Interaktion (Stand 2026-10-27, fixup.md)
Der Pool **HDD-2TB** existiert nicht mehr (`zpool list` zeigt HDD-Big +
SSD-Pool; fixup.md Phase 9a klärt Disable vs. Neuaufbau der Import-Unit).
Borg-Repos/Backups wandern über die neue vzdump-/mp0-Strecke nach
`HDD-Big/backups` — das Backup-Fenster (01:05) weckt damit HDD-Big, das
durch die VM-Disk-Passthroughs (VM-Rootvol, /opt) ohnehin beschrieben wird.
Ablauf unverändert: 01:05 Wecken -> Backup -> +10 min parkt der Pool
wieder. `pool_status.sh` (20:00, Telegram-Report) liest nur RAM-Metadaten
und weckt nicht. smartd weckt dank `-n standby,q` nicht beim 30-min-Poll.

Pool-Rollen sind als Defaults gesetzt: HDD-Big=data (10 min),
SSD-Pool=boot (nie).

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
