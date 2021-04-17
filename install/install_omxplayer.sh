#!/usr/bin/env bash
set -eou pipefail

cd /home/pi
git clone https://github.com/popcornmix/omxplayer.git
cd omxplayer
./prepare-native-raspbian.sh
sudo apt-get update && sudo apt install -y git libasound2-dev libva2 libpcre3-dev libidn11-dev libboost-dev libdbus-1-dev libssh-dev libssl-dev libsmbclient-dev libavutil-dev libavcodec-dev libavformat-dev libswscale-dev

# see https://github.com/popcornmix/omxplayer/issues/731
sed -i -e 's/--enable-libsmbclient/--disable-libsmbclient/g' Makefile.ffmpeg
make ffmpeg

# see https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e
# https://www.raspberrypi.org/forums/viewtopic.php?t=258647
git apply <(curl https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e.patch)

make -j$(nproc)
make dist
sudo make install
# wtf it still doesnt work on hdmi1. No error message, but no sound either
