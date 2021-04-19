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
    # see: https://raspberrypi.stackexchange.com/a/62522
    if ! grep -q '^dtoverlay=disable-wifi' /boot/config.txt ; then
        echo 'disabling wifi...'
        echo 'dtoverlay=disable-wifi' | sudo tee -a /boot/config.txt >/dev/null
    else
        echo 'wifi already disabled...'
    fi
}

main
