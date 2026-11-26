#!/usr/bin/env bash
# infra/bootstrap.sh — idempotent one-time VPS provisioning script
#
# Run as root on a fresh Ubuntu 24.04 VPS.
# Running it a second time on an already-provisioned VPS is safe.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<org>/dealbrain/main/infra/bootstrap.sh | sudo bash
#   # OR after cloning:
#   sudo bash infra/bootstrap.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/<org>/dealbrain.git}"
DEPLOY_USER="${DEPLOY_USER:-dealbrain}"
REPO_DIR="/srv/dealbrain"

echo "==> [1/8] Installing system packages"
apt-get update -qq
apt-get install -y -qq \
    ca-certificates \
    curl \
    git \
    ufw

# Docker Engine (idempotent — skips if already installed)
if ! command -v docker &>/dev/null; then
    echo "==> Installing Docker Engine"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-compose-plugin
else
    echo "==> Docker already installed, skipping"
fi

echo "==> [2/8] Creating deploy user '${DEPLOY_USER}'"
if ! id "${DEPLOY_USER}" &>/dev/null; then
    useradd -m -s /bin/bash "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"

echo "==> [3/8] Installing Tailscale"
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "==> Tailscale already installed, skipping"
fi

echo "==> [4/8] Env file instructions"
cat <<'INSTRUCTIONS'

ACTION REQUIRED — write two secret files before continuing:

  1. /etc/tailscale.env  (mode 0600, owner root)
     TS_AUTHKEY=tskey-auth-XXXXXXXXXXXXXXXX

     Get a reusable, non-ephemeral key from:
     https://login.tailscale.com/admin/settings/keys
     (Reusable: yes, Ephemeral: no, Expiry: 90 days)

  2. /etc/dealbrain.env  (mode 0640, owner root:docker)
     TAILSCALE_IP=        # fill after step 5 (tailscale ip -4)
     POSTGRES_PASSWORD=   # strong random string

     Example:
       install -m 0640 -o root -g docker /dev/null /etc/dealbrain.env
       echo "TAILSCALE_IP="        >> /etc/dealbrain.env
       echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >> /etc/dealbrain.env

INSTRUCTIONS

read -r -p "Press ENTER once you have written /etc/tailscale.env, or Ctrl-C to abort..."

echo "==> [5/8] Bringing up Tailscale"
# shellcheck source=/etc/tailscale.env
source /etc/tailscale.env
tailscale up --auth-key="${TS_AUTHKEY}" --hostname=dealbrain-vps
echo ""
echo "    Tailscale IP: $(tailscale ip -4)"
echo "    Update TAILSCALE_IP in /etc/dealbrain.env now."

read -r -p "Press ENTER once you have set TAILSCALE_IP in /etc/dealbrain.env..."

echo "==> [6/8] Configuring ufw"
ufw --force default deny incoming
ufw --force default allow outgoing
ufw allow 41641/udp comment 'tailscale-wireguard'
ufw allow 3478/udp comment 'tailscale-stun'
ufw --force enable
ufw status verbose

echo "==> [7/8] Cloning repo to ${REPO_DIR}"
if [ ! -d "${REPO_DIR}/.git" ]; then
    git clone "${REPO_URL}" "${REPO_DIR}"
    chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${REPO_DIR}"
else
    echo "==> Repo already cloned, skipping"
fi

echo "==> [8/8] First deploy"
# shellcheck source=/etc/dealbrain.env
source /etc/dealbrain.env
export TAILSCALE_IP POSTGRES_PASSWORD
cd "${REPO_DIR}"
docker compose up -d --wait portal

echo ""
echo "====================================================="
echo " Bootstrap complete."
echo " Portal:  http://$(tailscale ip -4):8000/"
echo " Health:  http://$(tailscale ip -4):8000/health"
echo ""
echo " NEXT STEP: close SSH port 22 in the cloud provider"
echo " console. SSH now only works via Tailscale:"
echo "   ssh ${DEPLOY_USER}@$(tailscale ip -4)"
echo "====================================================="
