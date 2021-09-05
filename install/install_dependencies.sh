#!/usr/bin/env bash

set -eou pipefail

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
is_restart_required=false
installation_type=false

main(){
    # installing and upgrading npm from scratch required a restart / re-login for the shell to recognize the new version
    # when the version changed between `apt install npm` and `npm install npm@latest -g`
    if ! which npm
    then
        is_restart_required=true
    fi

    updateAndInstallPackages
    clearYoutubedlCache

    if [[ "$installation_type" != "receiver" ]]; then
        installNode
    fi

    if [ "$is_restart_required" = true ] ; then
        echo "Restarting..."
        sudo shutdown -r now
    fi
}

usage() {
    local exit_code=$1
    echo "usage: $0 -t INSTALLATION_TYPE"
    echo "    -h  display this help message"
    echo "    -t  Installation type: either 'broadcaster', 'receiver', or 'all'"
    exit "$exit_code"
}

parseOpts(){
    while getopts ":ht:" opt; do
        case $opt in
            h) usage 0 ;;
            t)
                if [[ "$OPTARG" != "broadcaster" && "$OPTARG" != "receiver" && "$OPTARG" != "both" ]]; then
                    echo "Invalid installation type."
                    usage 1
                else
                    installation_type=${OPTARG}
                fi
                ;;
            \?)
                echo "Invalid option: -$OPTARG" >&2
                usage 1
                ;;
            :)
                echo "Option -$OPTARG requires an argument." >&2
                usage 1
                ;;
            *) usage 1 ;;
        esac
    done

    if [ "$installation_type" = false ] ; then
        echo "Installation type must be specified ('-t')."
        usage 1
    fi
}

updateAndInstallPackages(){
    echo -e "\\nUpdating and installing packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc omxplayer python3-pip fbi parallel dsh sshpass mbuffer npm
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl yt-dlp toml pytz
}

# Just in case the youtube-dl cache got polluted, as it has before...
# https://github.com/ytdl-org/youtube-dl/issues/24780
clearYoutubedlCache(){
    echo -e "\\nClearing youtube-dl cache..."
    # shellcheck disable=SC1083
    parallel --will-cite --max-procs 0 --halt never sudo -u {1} {2} --rm-cache-dir ::: root pi ::: youtube-dl yt-dlp
}

installNode(){
    echo -e "\\nInstalling latest version of node and its app dependencies..."

    # The `apt install npm` command installs a very old version of npm. Use npm to upgrade itself to latest.
    npm install npm@latest -g

    # Install app dependencies
    # npm install --prefix "$BASE_DIR/app"
}

main
