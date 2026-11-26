#!/usr/bin/env bash
# infra/deploy.sh — SSH-over-Tailscale deploy script
#
# Prerequisites (caller's shell):
#   export DEALBRAIN_HOST=100.x.x.x   # VPS Tailscale IP
#   export DEALBRAIN_USER=dealbrain    # SSH user on VPS
#
# The calling machine's SSH key must be in the VPS authorized_keys.
# SSH must be reachable via the Tailscale IP (not the public IP).

set -euo pipefail

DEALBRAIN_HOST="${DEALBRAIN_HOST:?DEALBRAIN_HOST must be set to the VPS Tailscale IP}"
DEALBRAIN_USER="${DEALBRAIN_USER:-dealbrain}"
REPO_DIR="/srv/dealbrain"

SSH="ssh -o StrictHostKeyChecking=accept-new ${DEALBRAIN_USER}@${DEALBRAIN_HOST}"

echo "==> Deploying to ${DEALBRAIN_USER}@${DEALBRAIN_HOST}"

echo "==> [1/3] git pull"
${SSH} "cd ${REPO_DIR} && git pull --ff-only origin main"

echo "==> [2/3] docker compose up"
${SSH} "source /etc/dealbrain.env && export TAILSCALE_IP POSTGRES_PASSWORD && \
    cd ${REPO_DIR} && docker compose up -d --wait portal"

echo "==> [3/3] status"
${SSH} "cd ${REPO_DIR} && docker compose ps portal"

echo "==> Deploy complete."
