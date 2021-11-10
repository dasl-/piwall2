#!/usr/bin/env bash
# creates the queue service file
BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
cat <<-EOF | sudo tee /etc/systemd/system/piwall2_queue.service >/dev/null
[Unit]
Description=piwall2 queue
After=network-online.target
Wants=network-online.target

[Service]
Environment=HOME=/home/pi
ExecStart=$BASE_DIR/bin/queue
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=PIWALL2_QUEUE

[Install]
WantedBy=multi-user.target
EOF
