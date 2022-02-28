#!/usr/bin/env bash
set -euo pipefail -o errtrace

BRANCH="master"

usage(){
    echo "Usage: $(basename "${0}") [-b <BRANCH>]"
    echo "Builds omxplayer"
    echo "  -b BRANCH : branch to build. Default: $BRANCH"
    exit 1
}

doGitStuff(){
    local base_dir="/home/pi/development"
    local clone_dir="$base_dir/omxplayer"
    if [ -d "$clone_dir" ]; then
        cd "$clone_dir"
        git pull
    else
        git clone https://github.com/dasl-/omxplayer.git $clone_dir
        cd $clone_dir
    fi

    git checkout "$BRANCH"
}

doPackageStuff(){
    sudo apt remove -y omxplayer
    sudo apt update && sudo apt install -y git libasound2-dev libva2 libpcre3-dev libidn11-dev libboost-dev libdbus-1-dev libssh-dev libsmbclient-dev libssl-dev
}

fixBuildScripts(){
    # see https://github.com/popcornmix/omxplayer/issues/731
    sed -i -e 's/git-core/git/g' prepare-native-raspbian.sh
    sed -i -e 's/libva1/libva2/g' prepare-native-raspbian.sh
    sed -i -e 's/libssl1.0-dev/libssl-dev/g' prepare-native-raspbian.sh
    sed -i -e 's/--enable-libsmbclient/--disable-libsmbclient/g' Makefile.ffmpeg

    # See: https://github.com/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#with-native-hdmi-sound
    # See: https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e
    # https://www.raspberrypi.org/forums/viewtopic.php?t=258647
    # git apply <(curl https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e.patch)
}

doBuild(){
    ./prepare-native-raspbian.sh
    make ffmpeg
    make -j"$(nproc)"
    make dist
    sudo make install
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
    fixBuildScripts
    doBuild
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
