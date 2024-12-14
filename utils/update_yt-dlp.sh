#!/usr/bin/env bash

# Script that is run via cron to update yt-dlp.
# Youtube releases updates every once in a while that breaks yt-dlp. If we don't constantly update
# to the latest yt-dlp version, piwall2 will stop working.
#
# We install yt-dlp as a standalone binary (rather than using pip) to ensure that even if we are using an outdated
# version of python3, we can still run yt-dlp.
# https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#release-files
#
# Why don't we just use `yt-dlp -U` to update? It didn't work properly on raspberry pi:
# https://github.com/yt-dlp/yt-dlp/issues/11813

set -euo pipefail -o errtrace

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
VERSION_FILE=$BASE_DIR/.yt-dlp-version

main(){
    trap 'fail $? $LINENO' ERR
    info "starting update_yt-dlp at $(date -u)"

    local latest_version_url
    latest_version_url=$(curl --max-time 5 https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest | jq --raw-output '.assets[] | select(.name == "yt-dlp_linux_armv7l") | .browser_download_url')
    if shouldDownloadNewVersion "$latest_version_url" ; then
        downloadNewVersion "$latest_version_url"
        repopulateYtDlpCache
    fi
    info "finished update_yt-dlp at $(date -u)"
}

shouldDownloadNewVersion(){
    local latest_version=$1

    if [ ! -f "$VERSION_FILE" ]; then
        info "No version file found at $BASE_DIR/.yt-dlp-version -- we need to download yt-dlp"
        return 0
    fi

    local current_version
    current_version=$(cat "$VERSION_FILE")
    if [ "$current_version" != "$latest_version" ]; then
        info "Found version $current_version but wanted version $latest_version -- we need to download yt-dlp"
        return 0
    fi

    info "Current yt-dlp version is the latest version: $current_version -- we don't need to download yt-dlp"
    return 1
}

downloadNewVersion(){
    local latest_version_url=$1
    # https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux_armv7l would also work for the URL
    curl --location --max-time 300 "$latest_version_url" | sudo tee /usr/local/bin/yt-dlp.tmp >/dev/null
    sudo chmod a+rwx /usr/local/bin/yt-dlp.tmp
    sudo mv /usr/local/bin/yt-dlp.tmp /usr/local/bin/yt-dlp
    echo "$latest_version_url" | sudo tee "$VERSION_FILE"
}

repopulateYtDlpCache(){
    info "Removing yt-dlp cache directory..."
    # Just in case the yt-dlp cache got polluted, as it has before...
    # https://github.com/ytdl-org/youtube-dl/issues/24780
    #
    # e.g.: sudo -u root yt-dlp --rm-cache-dir
    # shellcheck disable=SC1083
    parallel --will-cite --max-procs 0 --halt never sudo -u {1} yt-dlp --rm-cache-dir ::: root pi

    info "Repopulating yt-dlp cache..."
    # repopulate the cache that we just deleted? /shrug
    # e.g.: sudo -u root yt-dlp --output - --restrict-filenames --format 'worst[ext=mp4]/worst' --newline 'https://www.youtube.com/watch?v=IB_2jkwxqh4' > /dev/null
    # shellcheck disable=SC1083
    parallel --will-cite --max-procs 0 --halt never sudo -u {1} yt-dlp --output - --restrict-filenames --format 'worst[ext=mp4]/worst' --newline 'https://www.youtube.com/watch?v=IB_2jkwxqh4' > /dev/null ::: root pi
}

fail(){
    local exit_code=$1
    local line_no=$2
    local script_name
    script_name=$(basename "${BASH_SOURCE[0]}")
    die "Error in $script_name at line number: $line_no with exit code: $exit_code"
}

info(){
    echo -e "\x1b[32m$*\x1b[0m" # green stdout
}

warn(){
    echo -e "\x1b[33m$*\x1b[0m" # yellow stdout
}

die(){
    echo
    echo -e "\x1b[31m$*\x1b[0m" >&2 # red stderr
    exit 1
}

main "$@"
