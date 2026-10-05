#!/bin/sh
# Schedule the backups. Run once on the server:
#
#   sudo sh deploy/install-backups.sh
#
# Two systemd timers:
#   autoca-backup            every night at 20:30 UTC (02:00 IST): deploy/backup.sh
#   autoca-backup-heartbeat  every 30 minutes: tells CloudWatch how old the newest backup is
#
# Look at them with:  systemctl list-timers 'autoca-*'      and      journalctl -u autoca-backup -n 50
set -eu

[ "$(id -u)" -eq 0 ] || { echo "install-backups: run this with sudo" >&2; exit 1; }

repo="$(cd "$(dirname "$0")/.." && pwd)"
unit_dir="/etc/systemd/system"

cat > "$unit_dir/autoca-backup.service" <<EOF
[Unit]
Description=AutoCA nightly database backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=$repo
ExecStart=/bin/sh $repo/deploy/backup.sh
TimeoutStartSec=3600
EOF

cat > "$unit_dir/autoca-backup.timer" <<EOF
[Unit]
Description=Run the AutoCA database backup every night

[Timer]
OnCalendar=*-*-* 20:30:00 UTC
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > "$unit_dir/autoca-backup-heartbeat.service" <<EOF
[Unit]
Description=Publish the age of the newest AutoCA backup to CloudWatch
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=$repo
ExecStart=/bin/sh $repo/deploy/backup-heartbeat.sh
TimeoutStartSec=120
EOF

cat > "$unit_dir/autoca-backup-heartbeat.timer" <<EOF
[Unit]
Description=Publish the backup age every 30 minutes

[Timer]
OnBootSec=3min
OnCalendar=*:0/30

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now autoca-backup.timer autoca-backup-heartbeat.timer
echo
systemctl list-timers 'autoca-*' --no-pager
