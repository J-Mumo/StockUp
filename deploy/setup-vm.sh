#!/usr/bin/env bash
# One-shot bootstrap for a fresh Ubuntu 24.04 Azure VM.
# Run as the default user (azureuser); script will sudo where needed.
#
# Usage on the VM:
#   curl -fsSL https://raw.githubusercontent.com/<you>/stockup/main/deploy/setup-vm.sh | bash
# or after cloning:
#   bash deploy/setup-vm.sh

set -euo pipefail

echo ">>> Updating apt cache"
sudo apt-get update -y
sudo apt-get upgrade -y

echo ">>> Installing baseline packages"
sudo apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git ufw unattended-upgrades

echo ">>> Installing Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "    (you may need to log out and back in for the docker group to take effect)"
fi

echo ">>> Configuring UFW (SSH only — API stays on loopback, tunnel from your laptop)"
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw --force enable

echo ">>> Enabling unattended security upgrades"
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo
echo "Done. Next steps:"
echo "  1) git clone <your repo> ~/stockup && cd ~/stockup"
echo "  2) cp .env.production.example .env.production && nano .env.production"
echo "  3) docker compose --env-file .env.production up -d --build"
echo "  4) From your laptop:  ssh -i stockup.pem -L 8000:localhost:8000 azureuser@<vm-ip>"
echo "     then open http://localhost:8000/docs"
