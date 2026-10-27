#!/usr/bin/env bash
# One paste for Zynoo noVNC / phone console
set -euo pipefail
REPO="https://github.com/thekingmock-code/kalshi-desk.git"
DIR="/root/kalshi-desk"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl
rm -rf "$DIR"
git clone "$REPO" "$DIR"
cd "$DIR"
export REPO_URL="$REPO"
bash deploy/zynoo-bootstrap.sh
