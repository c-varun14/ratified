#!/bin/sh
# Ship the committed tree (git archive HEAD: nothing gitignored, no .env) to the host and
# (re)start FalkorDB + the app on port 80. Waits for the host's user-data to finish first.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
IP=${1:-$(cat "$HERE/.host")}
SSH="ssh -i $HOME/.ssh/ratified-key.pem -o StrictHostKeyChecking=accept-new ec2-user@$IP"
until $SSH test -f /var/tmp/userdata-done; do echo "waiting for user-data..."; sleep 10; done
git -C "$HERE/.." archive HEAD | $SSH 'tar -x -C /home/ec2-user/ratified'
$SSH 'cd /home/ec2-user/ratified && RATIFIED_BIND=0.0.0.0 APP_PORT=80 docker compose up -d --build'
until curl -sf "http://$IP/health" >/dev/null; do echo "waiting for the app to rebuild the graph..."; sleep 10; done
echo "live: http://$IP/"
