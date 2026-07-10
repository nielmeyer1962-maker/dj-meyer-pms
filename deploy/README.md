# Deployment configs

Infrastructure for running dj-meyer-pms on the firm's Ubuntu server (`claudedb`).
The app is served by **gunicorn on `127.0.0.1:8000`** (systemd), fronted by **nginx on
`:80`**. PostgreSQL runs locally on `127.0.0.1:5432`.

Files here are the source of truth; the copies under `/etc` on the server are installed
from these.

## Layout

| File | Installed to | Purpose |
|------|--------------|---------|
| `dj-meyer-pms.service` | `/etc/systemd/system/dj-meyer-pms.service` | gunicorn service (user `pms`, 4 workers, sandboxed) |
| `dj-meyer-pms.nginx` | `/etc/nginx/sites-available/dj-meyer-pms` (symlinked into `sites-enabled/`) | reverse proxy `:80 -> 127.0.0.1:8000` |

## Install / update (run as a sudoer on the server)

Prerequisites: repo cloned to `/opt/dj-meyer-pms`, venv built with `requirements.txt`,
`.env` present (mode `640`, owner `djmeyer:pms`) with a real `SECRET_KEY` and a
`DATABASE_URL` whose password is URL-safe, and `flask --app run db upgrade` applied.

```bash
# service user (once)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin pms

# systemd
sudo install -m 644 /opt/dj-meyer-pms/deploy/dj-meyer-pms.service /etc/systemd/system/dj-meyer-pms.service
sudo systemctl daemon-reload
sudo systemctl enable --now dj-meyer-pms

# nginx
sudo apt install -y nginx
sudo install -m 644 /opt/dj-meyer-pms/deploy/dj-meyer-pms.nginx /etc/nginx/sites-available/dj-meyer-pms
sudo ln -sf /etc/nginx/sites-available/dj-meyer-pms /etc/nginx/sites-enabled/dj-meyer-pms
sudo rm -f /etc/nginx/sites-enabled/default   # our config is default_server
sudo nginx -t && sudo systemctl reload nginx
```

Redeploy after `git pull`: `sudo systemctl restart dj-meyer-pms` (and `reload nginx` only
if this file changed).

## Firewall — current state and known deviation

ufw is enabled with **default deny incoming / allow outgoing**. Ports 22 (ssh) and 80
(app) are allowed, but currently via the **broad `Anywhere` rules** (`allow OpenSSH`,
`allow 80/tcp`), not scoped to the LAN. This was **accepted deliberately** (2026-07-09):
the host is a NAT'd private box (`192.168.1.0/24`) with no router port-forward/DMZ, so
"Anywhere" is bounded to the LAN in practice.

**Deferred hardening** — scope both to the LAN in a future pass:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 80 proto tcp
sudo ufw delete allow OpenSSH
sudo ufw delete allow 80/tcp
```

PostgreSQL is bound to `127.0.0.1` only and needs no ufw rule.

## Notes / future work

- Server IP is currently **DHCP** — set a reservation or static IP so the `:80` endpoint
  is stable.
- HTTP only for now. If TLS is added later, also add Flask's `ProxyFix` middleware so the
  app sees the real scheme/host behind nginx.
