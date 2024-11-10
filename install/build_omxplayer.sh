#!/usr/bin/env bash
set -euo pipefail -o errtrace

BRANCH="paused"
BASE_DIR="/home/pi/development"

usage(){
    echo "Usage: $(basename "${0}") [-b <BRANCH>]"
    echo "Builds omxplayer"
    echo "  -b BRANCH : branch to build. Default: $BRANCH"
    exit 1
}

main(){
    trap 'fail $? $LINENO' ERR

    while getopts "b:h" opt; do
        case ${opt} in
            b) BRANCH=${OPTARG} ;;
            h) usage ;;
            *) usage ;;
          esac
    done

    doGitStuff
    doPackageStuff
    buildUserland
    buildOmxplayer
}

doGitStuff(){
    info "Cloning omxplayer repo..."
    local clone_dir="$BASE_DIR/omxplayer"
    if [ -d "$clone_dir" ]; then
        cd "$clone_dir"
        git pull
    else
        git clone https://github.com/dasl-/omxplayer.git $clone_dir
        cd $clone_dir
    fi

    git checkout "$BRANCH"

    info "Cloning userland repo..."
    local clone_dir="$BASE_DIR/userland"
    if [ -d "$clone_dir" ]; then
        cd "$clone_dir"
        git pull
    else
        git clone https://github.com/raspberrypi/userland.git $clone_dir
        cd $clone_dir
    fi
}

doPackageStuff(){
    info "Installing package dependencies..."
    sudo apt remove -y omxplayer
    sudo apt update && sudo apt install -y git libasound2-dev libva2 libpcre3-dev libidn11-dev libboost-dev libdbus-1-dev libssh-dev libsmbclient-dev libssl-dev cmake
}

# Userland is necessary when building on bullseye. It comes by default on buster, but we have to
# install / build it manually on bullseye
# See: https://github.com/mjfwalsh/omxplayer?tab=readme-ov-file#compiling
buildUserland(){
    info "Building userland..."
    cd "$BASE_DIR/userland"
    ./buildme
}

buildOmxplayer(){
    info "Building omxplayer..."

    # See: https://github.com/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#with-native-hdmi-sound
    # See: https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e
    # https://www.raspberrypi.org/forums/viewtopic.php?t=258647
    # git apply <(curl https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e.patch)

    ./prepare-native-raspbian.sh
    make ffmpeg
    make -j"$(nproc)"
    make dist
    sudo make install
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
