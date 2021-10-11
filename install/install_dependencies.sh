#!/usr/bin/env bash

set -eou pipefail

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
installation_type=false
only_install_python_deps=false

main(){
    parseOpts "$@"

    if [ "$only_install_python_deps" = true ] ; then
        updateAndInstallPythonPackages
        exit
    fi

    updateAndInstallAptPackages
    updateAndInstallPythonPackages
    clearYoutubedlCache

    if [[ "$installation_type" != "receiver" ]]; then
        installNode
    fi
}

usage() {
    local exit_code=$1
    echo "usage: $0 -t INSTALLATION_TYPE"
    echo "    -h  display this help message"
    echo "    -t  Installation type: either 'broadcaster', 'receiver', or 'all'"
    echo "    -p  only install python dependencies"
    exit "$exit_code"
}

parseOpts(){
    while getopts ":ht:p" opt; do
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
            p) only_install_python_deps=true ;;
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

updateAndInstallAptPackages(){
    echo -e "\\nUpdating and installing apt packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc omxplayer python3-pip fbi parallel dsh sshpass mbuffer sqlite3
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl yt-dlp toml pytz
}

updateAndInstallPythonPackages(){
    echo -e "\\nUpdating and installing python packages..."
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

    # install node and npm
    curl -fsSL https://deb.nodesource.com/setup_16.x | sudo bash -
    sudo apt-get install -y nodejs

    # The `apt install npm` command installs a very old version of npm. Use npm to upgrade itself to latest.
    # sudo npm install npm@latest -g

    # Install app dependencies
    sudo npm install --prefix "$BASE_DIR/app"
}

main "$@"
