#!/usr/bin/env bash

set -eou pipefail

CONFIG=/boot/config.txt
is_restart_required=false

main(){
    updateAndInstallPackages
    disableWifi
    setGpuMem

    if [ "$is_restart_required" = true ] ; then
        echo "Restarting..."
        sudo shutdown -r now
    fi
}

updateAndInstallPackages(){
    echo -e "\\nUpdating and installing packages..."
    sudo apt update
    sudo apt -y install ffmpeg vlc omxplayer python3-pip fbi parallel dsh sshpass mbuffer
    sudo apt -y full-upgrade
    sudo pip3 install --upgrade youtube_dl yt-dlp toml pytz
}

# We disable wifi because multicast doesn't work well over wifi. Since the TV wall
# transmits the video from the broadcaster to the receivers over multicast, we want to
# ensure we are using the ethernet connection.
#
# See: https://tools.ietf.org/id/draft-mcbride-mboned-wifi-mcast-problem-statement-01.html
# See: https://raspberrypi.stackexchange.com/a/62522
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

# See: https://www.raspberrypi.org/documentation/configuration/config-txt/memory.md
#      https://github.com/dasl-/piwall2/blob/main/docs/configuring_omxplayer.adoc#gpu_mem
setGpuMem(){
    gpu_mem=$(vcgencmd get_mem gpu | sed -n 's/gpu=\(.*\)M/\1/p')
    if (( gpu_mem < 128 )); then
        echo 'Increasing gpu_mem to 128 megabytes...'

        # comment out existing gpu_mem.* lines in config
        sudo sed $CONFIG -i -e "s/^\(gpu_mem.*\)/#\1/"

        # create the new stanza
        echo 'gpu_mem=128' | sudo tee -a $CONFIG >/dev/null

        is_restart_required=true
    else
        echo "gpu_mem was large enough already: $gpu_mem megabytes..."
    fi
}

main
