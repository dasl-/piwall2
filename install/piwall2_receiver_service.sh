#!/usr/bin/env bash
# creates the receiver service file
BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
cat <<-EOF | sudo tee /etc/systemd/system/piwall2_receiver.service >/dev/null
[Unit]
Description=piwall2 receiver
After=network-online.target
Wants=network-online.target

[Service]
# Command to execute when the service is started
ExecStart=$BASE_DIR/bin/receiver
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=PIWALL2_RECEIVER

[Install]
WantedBy=multi-user.target
EOF
