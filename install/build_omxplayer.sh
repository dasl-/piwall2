#!/usr/bin/env bash
# See: https://github.com/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#with-native-hdmi-sound
set -eou pipefail

cd /home/pi
git clone https://github.com/popcornmix/omxplayer.git
cd omxplayer

sudo apt-get update && sudo apt install -y git libasound2-dev libva2 libpcre3-dev libidn11-dev libboost-dev libdbus-1-dev libssh-dev libsmbclient-dev libssl-dev

# see https://github.com/popcornmix/omxplayer/issues/731
sed -i -e 's/git-core/git/g' prepare-native-raspbian.sh
sed -i -e 's/libva1/libva2/g' prepare-native-raspbian.sh
sed -i -e 's/libssl1.0-dev/libssl-dev/g' prepare-native-raspbian.sh
sed -i -e 's/--enable-libsmbclient/--disable-libsmbclient/g' Makefile.ffmpeg

./prepare-native-raspbian.sh
make ffmpeg

# see https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e
# https://www.raspberrypi.org/forums/viewtopic.php?t=258647
git apply <(curl https://github.com/popcornmix/omxplayer/commit/6d186be9d15c3d2ee8a4256afd26cddebbd8251e.patch)

make -j$(nproc)
make dist
sudo make install
