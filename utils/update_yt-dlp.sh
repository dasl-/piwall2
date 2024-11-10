#!/usr/bin/bash

# Script that is run via cron to update yt-dlp.
# Youtube releases updates every once in a while that breaks yt-dlp. If we don't constantly update
# to the latest yt-dlp version, piwall2 will stop working.

set -x

echo "starting update_yt-dlp at $(date -u)"
sudo yt-dlp -U

# Just in case the yt-dlp cache got polluted, as it has before...
# https://github.com/ytdl-org/youtube-dl/issues/24780
#
# e.g.: sudo -u root yt-dlp --rm-cache-dir
# shellcheck disable=SC1083
parallel --will-cite --max-procs 0 --halt never sudo -u {1} yt-dlp --rm-cache-dir ::: root pi

# repopulate the cache that we just deleted? /shrug
# e.g.: sudo -u root yt-dlp --output - --restrict-filenames --format 'worst[ext=mp4]/worst' --newline 'https://www.youtube.com/watch?v=IB_2jkwxqh4' > /dev/null
# shellcheck disable=SC1083
parallel --will-cite --max-procs 0 --halt never sudo -u {1} yt-dlp --output - --restrict-filenames --format 'worst[ext=mp4]/worst' --newline 'https://www.youtube.com/watch?v=IB_2jkwxqh4' > /dev/null ::: root pi

echo "finished update_yt-dlp at $(date -u)"
