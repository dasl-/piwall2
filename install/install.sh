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
    # TODO: automate setting hdmi modes? https://www.raspberrypi.org/documentation/configuration/config-txt/video.md
    :
}

main
