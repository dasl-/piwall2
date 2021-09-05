#!/usr/bin/env bash

set -eou pipefail

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"
RESTART_REQUIRED_FILE='/tmp/piwall2_install_restart_required'
CONFIG=/boot/config.txt
is_restart_required=false
installation_type=false
enable_composite_video_output=false
disable_wifi=true

main(){
    parseOpts "$@"

    setTimezone
    setupLogging
    setupSystemdServices
    setupYoutubeDlUpdateCron

    # Do broadcaster stuff
    if [[ "$installation_type" != 'receiver' ]]; then
        updateDbSchema
        buildWebApp
    fi

    # Do receiver stuff
    if [[ "$installation_type" != 'broadcaster' ]]; then
        if [ $enable_composite_video_output = true ]; then
            enableCompositeVideoOutput
        fi
    fi

    if [ $disable_wifi = true ]; then
        disableWifi
    fi

    setGpuMem

    if [ $is_restart_required = true ] ; then
        echo "Please restart to complete installation!"
        touch "$RESTART_REQUIRED_FILE"
    fi
}

usage() {
    local exit_code=$1
    echo "usage: $0 -t INSTALLATION_TYPE [-c] [-w]"
    echo "    -h  display this help message"
    echo "    -t  Installation type: either 'broadcaster', 'receiver', or 'all'"
    echo "    -c  enable composite video output. This will detrimentally affect performance to a small degree."
    echo "    -w  Don't disable wifi. Only specify this option if you know what you're doing."
    exit "$exit_code"
}

parseOpts(){
    while getopts ":ht:cw" opt; do
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
            c) enable_composite_video_output=true ;;
            w) disable_wifi=false ;;
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

setTimezone(){
    echo "Setting timezone to UTC..."
    sudo timedatectl set-timezone UTC
}

setupLogging(){
    echo "Setting up logging..."

    # syslog
    sudo mkdir -p /var/log/piwall2
    if [[ "$installation_type" == 'broadcaster' || "$installation_type" == 'all' ]]; then
        sudo touch /var/log/piwall2/server.log /var/log/piwall2/queue.log
        sudo cp "$BASE_DIR"/install/piwall2_{queue,server}_syslog.conf /etc/rsyslog.d
    fi
    if [[ "$installation_type" == 'receiver' || "$installation_type" == 'all' ]]; then
        sudo touch /var/log/piwall2/receiver.log
        sudo cp "$BASE_DIR"/install/piwall2_receiver_syslog.conf /etc/rsyslog.d
    fi
    sudo touch /var/log/piwall2/update_youtube-dl.log
    sudo systemctl restart rsyslog

    # logrotate
    sudo cp "$BASE_DIR"/install/piwall2_logrotate /etc/logrotate.d
    sudo chown root:root /etc/logrotate.d/piwall2_logrotate
    sudo chmod 644 /etc/logrotate.d/piwall2_logrotate
}

setupSystemdServices(){
    echo "Setting up systemd services..."
    if [[ "$installation_type" == 'broadcaster' || "$installation_type" == 'all' ]]; then
        sudo "$BASE_DIR/install/piwall2_queue_service.sh"
        sudo "$BASE_DIR/install/piwall2_server_service.sh"
    fi
    if [[ "$installation_type" == 'receiver' || "$installation_type" == 'all' ]]; then
        sudo "$BASE_DIR/install/piwall2_receiver_service.sh"
    fi
    sudo chown root:root /etc/systemd/system/piwall2_*.service
    sudo chmod 644 /etc/systemd/system/piwall2_*.service

    # stop and disable units in case we are changing which host is the broadcaster / receiver
    # and unit files already existed...
    local piwall2_units
    piwall2_units=$(systemctl --all --no-legend list-units 'piwall2_*' | awk '{ print $1; }' | paste -sd ' ')
    if [ -n "${piwall2_units}" ]; then
        # shellcheck disable=SC2086
        sudo systemctl disable $piwall2_units || true
        # shellcheck disable=SC2086
        sudo systemctl stop $piwall2_units || true
    fi

    if [[ "$installation_type" == 'broadcaster' || "$installation_type" == 'all' ]]; then
        echo "TODO..."
        # sudo systemctl enable piwall2_queue.service piwall2_server.service
        # sudo systemctl daemon-reload
        # sudo systemctl restart piwall2_queue.service piwall2_server.service
    fi
    if [[ "$installation_type" == 'receiver' || "$installation_type" == 'all' ]]; then
        sudo systemctl enable piwall2_receiver.service
        sudo systemctl daemon-reload
        sudo systemctl restart piwall2_receiver.service
    fi
}

setupYoutubeDlUpdateCron(){
    echo "Setting up youtube-dl update cron..."
    sudo "$BASE_DIR/install/piwall2_cron.sh"
    sudo chown root:root /etc/cron.d/piwall2
    sudo chmod 644 /etc/cron.d/piwall2
}

updateDbSchema(){
    echo "Updating DB schema (if necessary)..."
    echo "TODO"
    # sudo "$BASE_DIR"/utils/make_db
}

buildWebApp(){
    echo "Building web app..."
    echo "TODO"
    # npm run build --prefix "$BASE_DIR"/app
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

# see: https://www.raspberrypi.org/documentation/computers/config_txt.html#enable_tvout-raspberry-pi-4-model-b-only
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

# See: https://www.raspberrypi.org/documentation/computers/config_txt.html#gpu_mem
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

main "$@"
