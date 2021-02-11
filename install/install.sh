#!/usr/bin/env bash

set -eou pipefail

main(){
    updateAndInstallPackages
}

updateAndInstallPackages(){
    echo -e "\\nUpdating and installing packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc python3-pip
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl
}

main
