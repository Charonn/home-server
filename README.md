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
