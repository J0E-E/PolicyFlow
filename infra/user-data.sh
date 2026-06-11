#!/bin/bash
# Host bootstrap for the PolicyFlow EC2 instance (Amazon Linux 2023).
# Rendered by Terraform via templatefile(); $${...} are literal shell, $${region}
# below is the only template variable. Written to be idempotent so a re-run is safe.
set -euo pipefail

# --- Docker -----------------------------------------------------------------
dnf install -y docker
systemctl enable --now docker

# Let ec2-user run docker without sudo.
usermod -aG docker ec2-user

# --- Docker Compose v2 CLI plugin -------------------------------------------
# AL2023's repos don't ship the compose plugin, so install the binary into the
# Docker CLI plugins directory by hand.
COMPOSE_VERSION="v2.29.7"
COMPOSE_PLUGIN_DIR="/usr/local/lib/docker/cli-plugins"
COMPOSE_PLUGIN_PATH="$${COMPOSE_PLUGIN_DIR}/docker-compose"
if [ ! -x "$${COMPOSE_PLUGIN_PATH}" ]; then
  mkdir -p "$${COMPOSE_PLUGIN_DIR}"
  curl -fsSL \
    "https://github.com/docker/compose/releases/download/$${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o "$${COMPOSE_PLUGIN_PATH}"
  chmod +x "$${COMPOSE_PLUGIN_PATH}"
fi

# --- CodeDeploy agent -------------------------------------------------------
# Installed now but idle: Epic 7 gives the host its instance profile, but the
# agent only becomes functional once Epic 9 adds a deployment group. Needs Ruby
# and wget.
dnf install -y ruby wget

if ! systemctl is-active --quiet codedeploy-agent; then
  CODEDEPLOY_INSTALLER="/tmp/codedeploy-install"
  wget -q \
    "https://aws-codedeploy-${region}.s3.${region}.amazonaws.com/latest/install" \
    -O "$${CODEDEPLOY_INSTALLER}"
  chmod +x "$${CODEDEPLOY_INSTALLER}"
  "$${CODEDEPLOY_INSTALLER}" auto
  rm -f "$${CODEDEPLOY_INSTALLER}"
fi

systemctl enable --now codedeploy-agent
