#!/usr/bin/env bash

set -eou pipefail

CONFIG=/boot/config.txt
is_restart_required=false

main(){
    updateAndInstallPackages
    disableWifi

    if [ "$is_restart_required" = true ] ; then
        echo "Restarting..."
        sudo shutdown -r now
    fi
}

updateAndInstallPackages(){
    echo -e "\\nUpdating and installing packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc omxplayer python3-pip
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl
}

# see: https://raspberrypi.stackexchange.com/a/62522
disableWifi(){
    if ! grep -q '^dtoverlay=disable-wifi' $CONFIG ; then
        echo 'disabling wifi...'

        # uncomment it if the stanza is commented out
        sudo sed $CONFIG -i -e "s/^#\?dtoverlay=disable-wifi *$/dtoverlay=disable-wifi/"

        # create the stanza if it doesn't yet exist
        if ! grep -q '^dtoverlay=disable-wifi' $CONFIG ; then
            echo 'dtoverlay=disable-wifi' | sudo tee -a $CONFIG >/dev/null
        fi
        is_restart_required=true
    else
        echo 'wifi already disabled...'
    fi
}

# see: https://www.raspberrypi.org/documentation/configuration/config-txt/video.md
enableCompositeVideoOutput(){
    if ! grep -q '^enable_tvout=1' $CONFIG ; then
        echo 'enabling composite video output...'

        # uncomment it and enable it if the stanza is commented out
        sudo sed $CONFIG -i -e "s/^#\?enable_tvout=.*/enable_tvout=1/"

        # create the stanza if it doesn't yet exist
        if ! grep -q '^enable_tvout=1' $CONFIG ; then
            echo 'enable_tvout=1' | sudo tee -a $CONFIG >/dev/null
        fi
        is_restart_required=true
    else
        echo 'composite video output already enabled...'
    fi
}

main
