#!/bin/sh
# Schedule audit-log retention. Run once on the server:
#
#   sudo sh deploy/install-log-retention.sh
#
# One systemd timer:
#   autoca-trim-audit-log   every night at 03:15 UTC (08:45 IST, after the 20:30 UTC backup): deploy/trim-audit-log.sh
#
# Look at it with:  systemctl list-timers 'autoca-*'      and      journalctl -u autoca-trim-audit-log -n 50
set -eu

[ "$(id -u)" -eq 0 ] || { echo "install-log-retention: run this with sudo" >&2; exit 1; }

repo="$(cd "$(dirname "$0")/.." && pwd)"
unit_dir="/etc/systemd/system"

cat > "$unit_dir/autoca-trim-audit-log.service" <<EOF
[Unit]
Description=Delete AutoCA audit-log rows past their retention window
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=$repo
ExecStart=/bin/sh $repo/deploy/trim-audit-log.sh
TimeoutStartSec=300
EOF

cat > "$unit_dir/autoca-trim-audit-log.timer" <<EOF
[Unit]
Description=Run AutoCA audit-log retention every night

[Timer]
OnCalendar=*-*-* 03:15:00 UTC
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now autoca-trim-audit-log.timer
echo
systemctl list-timers 'autoca-*' --no-pager
