#!/bin/bash
# EC2 user-data for the Ratified host (Amazon Linux 2023): Docker plus the Compose and
# Buildx plugins at the versions the Swap host runs (AL2023 ships neither plugin).
set -eux
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v5.6.0/docker-compose-linux-x86_64
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-buildx \
  https://github.com/docker/buildx/releases/download/v0.38.0/buildx-v0.38.0.linux-amd64
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-buildx
mkdir -p /home/ec2-user/ratified
chown ec2-user:ec2-user /home/ec2-user/ratified
touch /var/tmp/userdata-done
