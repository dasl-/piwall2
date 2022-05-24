#!/usr/bin/env bash

set -euo pipefail -o errtrace

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
installation_type=false
only_install_python_deps=false
omxplayer_branch='master'

main(){
    trap 'fail $? $LINENO' ERR

    parseOpts "$@"

    if [ "$only_install_python_deps" = true ] ; then
        updateAndInstallPythonPackages
        exit
    fi

    stopPiwallServices
    updateAndInstallAptPackages
    updateAndInstallPythonPackages
    buildAndInstallOmxplayerFork
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
    echo "    -b  omxplayer branch to build. Default: $omxplayer_branch (uses https://github.com/dasl-/omxplayer/ )"
    exit "$exit_code"
}

parseOpts(){
    while getopts ":ht:pb:" opt; do
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
            b) omxplayer_branch=${OPTARG} ;;
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

stopPiwallServices(){
    info "\\nStopping piwall services..."
    # stop the services because in particular, a running omxplayer instance can cause the installation to fail,
    # specifically the `buildAndInstallOmxplayerFork` step:
    #   pi@piwall8.local: cp: cannot create regular file '/usr/bin/omxplayer.bin': Text file busy
    #   pi@piwall8.local: make: *** [Makefile:98: install] Error 1`
    local piwall2_units
    piwall2_units=$(systemctl --all --no-legend list-units 'piwall2_*' | awk '{ print $1; }' | paste -sd ' ')
    if [ -n "${piwall2_units}" ]; then
        # shellcheck disable=SC2086
        sudo systemctl stop $piwall2_units || true
    fi
}

updateAndInstallAptPackages(){
    info "\\nUpdating and installing apt packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc python3-pip fbi parallel dsh sshpass mbuffer sqlite3 pv
    sudo apt -y full-upgrade
}

updateAndInstallPythonPackages(){
    info "\\nUpdating and installing python packages..."
    sudo pip3 install --upgrade youtube_dl yt-dlp toml pyjson5 pytz
}

# A fork of omxplayer with millisecond granularity in the log files. Helpful for debugging timing issues.
buildAndInstallOmxplayerFork(){
    info "\\nBuilding and installing omxplayer fork..."
    "$BASE_DIR"/install/build_omxplayer.sh -b "$omxplayer_branch"
}

# Just in case the youtube-dl cache got polluted, as it has before...
# https://github.com/ytdl-org/youtube-dl/issues/24780
clearYoutubedlCache(){
    info "\\nClearing youtube-dl cache..."
    # shellcheck disable=SC1083
    parallel --will-cite --max-procs 0 --halt never sudo -u {1} {2} --rm-cache-dir ::: root pi ::: youtube-dl yt-dlp
}

installNode(){
    info "\\nInstalling node and npm..."

    # Install node and npm. Installing this with the OS's default packages provided by apt installs a pretty old
    # version of node and npm. We need a newer version.
    # See: https://github.com/nodesource/distributions/blob/master/README.md#installation-instructions
    curl -fsSL https://deb.nodesource.com/setup_18.x | sudo bash -
    sudo apt-get install -y nodejs

    info "\\nInstalling react app dependencies..."
    # TODO: when installing from scratch on a fresh OS installation, this step once failed with
    # and error: https://gist.github.com/dasl-/01b9bf9650730c7dbfab6c859ea6c0dc
    # See if this is reproducible on a fresh install sometime...
    # It's weird because apparently it's a node error, but the line that is executing below is a
    # npm command. Could npm be shelling out to node? Maybe I can figure this out by running
    # checking the process list while the next step is running, and htop to look at RAM usage.`
    npm install --prefix "$BASE_DIR/app"
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
