#!/usr/bin/env bash
# creates the piwall2 cron file
BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
cat <<-EOF | sudo tee /etc/cron.d/piwall2 >/dev/null
31 09 * * * root $BASE_DIR/utils/update_yt-dlp.sh >>/var/log/piwall2/update_yt-dlp.log 2>&1
EOF
