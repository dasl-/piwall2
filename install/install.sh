#!/usr/bin/env bash

set -eou pipefail

main(){
    updateAndInstallPackages
    disableWifi
}

updateAndInstallPackages(){
    echo -e "\\nUpdating and installing packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc omxplayer python3-pip
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl
}

disableWifi(){
    # TODO: automate setting this: https://raspberrypi.stackexchange.com/a/62522
    # dtoverlay=disable-wifi
}

main
