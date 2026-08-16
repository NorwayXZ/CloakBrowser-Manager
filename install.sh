#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/NorwayXZ/CloakBrowser-Manager.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/cloakbrowser-manager}"
CLOAK_DOMAIN="${CLOAK_DOMAIN:-}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
AUTH_TOKEN="${AUTH_TOKEN:-}"
SESSION_SECRET="${SESSION_SECRET:-}"
MANAGER_PORT="${MANAGER_PORT:-8080}"

usage() {
  cat <<'USAGE'
CloakBrowser Manager one-click installer

Usage:
  sudo ./install.sh --domain cloak.example.com

Options:
  --domain DOMAIN       Domain for HTTPS reverse proxy
  --dir PATH            Install directory (default: /opt/cloakbrowser-manager)
  --repo URL            Git repository URL
  --username NAME       Initial admin username (default: admin)
  --password PASSWORD   Initial admin password (generated if omitted)
  --auth-token TOKEN    Optional API bearer token
  --port PORT           Local manager port (default: 8080)

Environment variables with the same names are also supported:
  CLOAK_DOMAIN, INSTALL_DIR, REPO_URL, ADMIN_USERNAME, ADMIN_PASSWORD, AUTH_TOKEN, MANAGER_PORT
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      CLOAK_DOMAIN="${2:-}"
      shift 2
      ;;
    --dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --repo)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --username)
      ADMIN_USERNAME="${2:-}"
      shift 2
      ;;
    --password)
      ADMIN_PASSWORD="${2:-}"
      shift 2
      ;;
    --auth-token)
      AUTH_TOKEN="${2:-}"
      shift 2
      ;;
    --port)
      MANAGER_PORT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root, for example: sudo ./install.sh --domain cloak.example.com" >&2
  exit 1
fi

if [[ -z "${CLOAK_DOMAIN}" ]]; then
  echo "--domain is required" >&2
  usage
  exit 1
fi

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

random_secret() {
  if command_exists openssl; then
    openssl rand -base64 24 | tr -d '\n'
  else
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
  fi
}

install_base_packages() {
  if command_exists apt-get; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git openssl
  elif command_exists dnf; then
    dnf install -y ca-certificates curl git openssl
  elif command_exists yum; then
    yum install -y ca-certificates curl git openssl
  else
    echo "Unsupported Linux distribution: install curl, git, openssl and Docker manually first." >&2
    exit 1
  fi
}

install_certbot_packages() {
  if command_exists apt-get; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot python3-certbot-nginx
  elif command_exists dnf; then
    dnf install -y nginx certbot python3-certbot-nginx
  elif command_exists yum; then
    yum install -y nginx certbot python3-certbot-nginx
  else
    echo "Could not install Certbot automatically on this distribution." >&2
    return 1
  fi
}

install_docker() {
  if command_exists docker; then
    return
  fi
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
}

open_firewall() {
  if command_exists ufw && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp
    ufw allow 443/tcp
  fi
  if command_exists firewall-cmd && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
  fi
}

nginx_is_active_proxy() {
  command_exists nginx && ss -ltnp 2>/dev/null | grep -E ':(80|443)\b' | grep -q nginx
}

sync_repo() {
  mkdir -p "$(dirname "${INSTALL_DIR}")"
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    git -C "${INSTALL_DIR}" fetch origin
    git -C "${INSTALL_DIR}" checkout main
    git -C "${INSTALL_DIR}" pull --ff-only origin main
  elif [[ -e "${INSTALL_DIR}" ]]; then
    echo "${INSTALL_DIR} exists but is not a git repository" >&2
    exit 1
  else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi
}

write_env_if_needed() {
  cd "${INSTALL_DIR}"
  if [[ -f .env ]]; then
    chmod 600 .env
    echo "Existing .env found, keeping current login settings."
    return
  fi

  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    ADMIN_PASSWORD="$(random_secret)"
  fi
  if [[ -z "${SESSION_SECRET}" ]]; then
    SESSION_SECRET="$(random_secret)"
  fi

  umask 077
  cat > .env <<EOF
CLOAK_DOMAIN=${CLOAK_DOMAIN}
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
AUTH_TOKEN=${AUTH_TOKEN}
SESSION_SECRET=${SESSION_SECRET}
MANAGER_PORT=${MANAGER_PORT}
CLOAKBROWSER_MANAGER_ENGINE=cloakbrowser
EOF
  chmod 600 .env
  echo "Initial admin username: ${ADMIN_USERNAME}"
  echo "Initial admin password: ${ADMIN_PASSWORD}"
}

start_stack() {
  cd "${INSTALL_DIR}"
  if nginx_is_active_proxy; then
    docker compose -f docker-compose.prod.yml up -d --build manager
  else
    COMPOSE_PROFILES=caddy docker compose -f docker-compose.prod.yml up -d --build
  fi
}

configure_nginx_proxy() {
  if ! nginx_is_active_proxy; then
    return
  fi

  install_certbot_packages || true

  local conf_path
  if [[ -d /etc/nginx/sites-available && -d /etc/nginx/sites-enabled ]]; then
    conf_path="/etc/nginx/sites-available/cloakbrowser-manager.conf"
  else
    conf_path="/etc/nginx/conf.d/cloakbrowser-manager.conf"
  fi

  cat > "${conf_path}" <<EOF
map \$http_upgrade \$cloakbrowser_connection_upgrade {
  default upgrade;
  '' close;
}

server {
  listen 80;
  listen [::]:80;
  server_name ${CLOAK_DOMAIN};

  client_max_body_size 50m;

  location / {
    proxy_pass http://127.0.0.1:${MANAGER_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$cloakbrowser_connection_upgrade;
    proxy_read_timeout 86400;
  }
}
EOF

  if [[ "${conf_path}" == /etc/nginx/sites-available/* ]]; then
    ln -sf "${conf_path}" /etc/nginx/sites-enabled/cloakbrowser-manager.conf
  fi

  nginx -t
  systemctl reload nginx

  if command_exists certbot; then
    certbot --nginx \
      -d "${CLOAK_DOMAIN}" \
      --non-interactive \
      --agree-tos \
      --register-unsafely-without-email \
      --redirect || echo "Certbot failed; HTTP reverse proxy is still configured."
  fi
}

install_base_packages
install_docker
open_firewall
sync_repo
write_env_if_needed
start_stack
configure_nginx_proxy

echo
echo "CloakBrowser Manager is starting."
echo "URL: https://${CLOAK_DOMAIN}"
echo "Install dir: ${INSTALL_DIR}"
echo "To change login later: open the web UI, click the key icon in the top-right corner."
