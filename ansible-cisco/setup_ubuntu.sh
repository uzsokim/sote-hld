#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v apt >/dev/null 2>&1; then
  echo "This script expects Ubuntu/Debian with apt." >&2
  exit 1
fi

echo "[1/4] apt packages"
sudo apt update
sudo apt install -y python3 python3-pip python3-venv openssh-client sshpass

echo "[2/4] python venv (project-local)"
if [ ! -d "${ROOT_DIR}/.venv" ]; then
  python3 -m venv "${ROOT_DIR}/.venv"
fi
# shellcheck disable=SC1091
source "${ROOT_DIR}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install ansible ansible-lint paramiko netaddr

echo "[3/4] ansible-galaxy collections"
ansible-galaxy collection install ansible.netcommon cisco.ios

echo "[4/4] versions"
ansible --version
ansible-galaxy collection list | sed -n '1,160p'

echo "OK. Next: run a playbook with:"
echo "  ${ROOT_DIR}/.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/show_version.yml"
