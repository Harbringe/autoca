#!/bin/sh
# Sets up a SEPARATE, throwaway server to run the scale kit on, so a load or stress test cannot touch the live site. Run it once, on the new
# server, in a Session Manager shell:
#
#   curl -fsSL https://raw.githubusercontent.com/Harbringe/autoca/dev/scripts/scale/bootstrap-ec2.sh | sh
#
# It installs Docker and git, clones the (public) repository, and builds the same app image the live server builds (autoca-app:prod). After it,
# the commands in docs/SCALE.md work unchanged, from /srv/autoca/scripts/scale. It holds no live key or password and cannot reach the live
# database: the scratch kit makes its own throwaway ones. Terminate the server when the tests are done.
#
# Works on Amazon Linux 2023 and on Ubuntu. Use the same size as production (t3.small) so the numbers mean the same thing.
set -eu

BRANCH="${1:-dev}"

if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y docker git openssl
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y docker.io git curl openssl
else
    echo "bootstrap: neither dnf nor apt-get found; install Docker, git and openssl by hand" >&2
    exit 1
fi
sudo systemctl enable --now docker

if ! sudo docker compose version >/dev/null 2>&1; then
    # The Compose plugin: Docker's own release, pinned.
    version="v2.29.7"
    arch="$(uname -m)"
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -fsSL "https://github.com/docker/compose/releases/download/${version}/docker-compose-linux-${arch}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

if [ -d /srv/autoca/.git ]; then
    cd /srv/autoca && sudo git fetch origin "$BRANCH" && sudo git checkout -q "origin/$BRANCH"
else
    sudo mkdir -p /srv
    sudo git clone --depth 1 --branch "$BRANCH" https://github.com/Harbringe/autoca.git /srv/autoca
fi

cd /srv/autoca
sudo docker build -t autoca-app:prod .

echo
echo "bootstrap: ready. Next:"
echo "  cd /srv/autoca/scripts/scale"
echo "  sh scale.sh check"
echo "  sh scale.sh up"
