#!/usr/bin/env bash
# creates the server service file
BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
cat <<-EOF | sudo tee /etc/systemd/system/piwall2_server.service >/dev/null
[Unit]
Description=piwall2 server
After=network-online.target
Wants=network-online.target

[Service]
# Command to execute when the service is started
ExecStart=$BASE_DIR/bin/server
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=PIWALL2_SERVER

[Install]
WantedBy=multi-user.target
EOF
