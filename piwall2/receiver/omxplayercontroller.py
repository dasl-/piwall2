import getpass
import math
import re
import subprocess
import time

from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

# Controls omxplayer via dbus.
# See:
# https://github.com/popcornmix/omxplayer/blob/master/dbuscontrol.sh
# https://github.com/popcornmix/omxplayer#dbus-control
#
# TODO: support dual video output. Perhaps send dbus messages in parallel to both?
class OmxplayerController:

    TV1_VIDEO_DBUS_NAME = 'piwall.tv1.video'
    TV2_VIDEO_DBUS_NAME = 'piwall.tv2.video'

    __DBUS_TIMEOUT_MS = 2000

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__user = getpass.getuser()
        self.__dbus_addr = None
        self.__dbus_pid = None
        self.__load_dbus_session_info_if_not_loaded()

    # gets a perceptual loudness %
    # returns a float in the range [0, 100]
    def get_vol_pct(self):
        if not self.__load_dbus_session_info_if_not_loaded():
            return 0

        cmd = (f"sudo -u {self.__user} DBUS_SESSION_BUS_ADDRESS={self.__dbus_addr} DBUS_SESSION_BUS_PID={self.__dbus_pid} dbus-send " +
            f"--print-reply=literal --session --reply-timeout={self.__DBUS_TIMEOUT_MS} " +
            f"--dest={self.TV1_VIDEO_DBUS_NAME} /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get " +
            "string:'org.mpris.MediaPlayer2.Player' string:'Volume'")
        vol_cmd_output = None
        try:
            vol_cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT)
                .decode("utf-8"))
        except Exception:
            return 0

        m = re.search(r"\s+double\s+(\d+(\.\d*)?)", vol_cmd_output)
        if m is None:
            return 0
        vol_pct = 100 * float(m.group(1))
        vol_pct = max(0, vol_pct)
        vol_pct = min(100, vol_pct)
        return vol_pct

    # takes a perceptual loudness %.
    # vol_pct should be a float in the range [0, 100]
    def set_vol_pct(self, vol_pct):
        if not self.__load_dbus_session_info_if_not_loaded():
            return False

        # omxplayer uses a different algorithm for computing volume percentage from the original millibels than
        # our VolumeController class uses. Convert to omxplayer's equivalent percentage for a smoother volume
        # adjustment experience.
        # See: https://github.com/popcornmix/omxplayer#volume-rw
        millibels = VolumeController.pct_to_millibels(vol_pct)
        omx_vol_pct = math.pow(10, millibels / 2000)
        omx_vol_pct = max(omx_vol_pct, 0)
        omx_vol_pct = min(omx_vol_pct, 1)

        cmd = (f"sudo -u {self.__user} DBUS_SESSION_BUS_ADDRESS={self.__dbus_addr} DBUS_SESSION_BUS_PID={self.__dbus_pid} dbus-send " +
            f"--print-reply=literal --session --reply-timeout={self.__DBUS_TIMEOUT_MS} " +
            f"--dest={self.TV1_VIDEO_DBUS_NAME} /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Set " +
            f"string:'org.mpris.MediaPlayer2.Player' string:'Volume' double:{omx_vol_pct}")
        start = time.time()
        try:
            vol_cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT))
        except Exception:
            self.__logger.debug(f"failed to set omxplayer volume with command: [{cmd}].")
            return False
        elapsed_ms = (time.time() - start) * 1000

        # this is taking a while... https://docs.google.com/spreadsheets/d/1jB3cf7_d_jQxHmjWCLvt7DCgGCIJfhZ2V6EG4J1_AsA/edit#gid=0
        # Try pydbus, maybe it's faster
        self.__logger.debug(f"set volume after {elapsed_ms}ms.")
        return True

    # crop string: "x1 y1 x2 y2"
    def set_crop(self, crop_string):
        if not self.__load_dbus_session_info_if_not_loaded():
            return False

        cmd = (f"sudo -u {self.__user} DBUS_SESSION_BUS_ADDRESS={self.__dbus_addr} DBUS_SESSION_BUS_PID={self.__dbus_pid} dbus-send " +
            f"--print-reply=literal --session --reply-timeout={self.__DBUS_TIMEOUT_MS} " +
            f"--dest={self.TV1_VIDEO_DBUS_NAME} /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.SetVideoCropPos " +
            f"objpath:/not/used string:'{crop_string}'")

        start = time.time()
        try:
            cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT))
        except Exception:
            self.__logger.debug("failed to set omxplayer crop position")
            return False
        elapsed_ms = (time.time() - start) * 1000

        self.__logger.debug(f"set crop position after {elapsed_ms}ms.")
        return True

    # Returns a boolean. True if the session was loaded or already loaded, false if we failed to load.
    def __load_dbus_session_info_if_not_loaded(self):
        if self.__dbus_addr and self.__dbus_pid:
            return True # already loaded

        dbus_addr_file_path = f"/tmp/omxplayerdbus.{self.__user}"
        dbus_pid_file_path = f"/tmp/omxplayerdbus.{self.__user}.pid"
        self.__logger.info(f"Reading dbus info from files {dbus_addr_file_path} and {dbus_pid_file_path}.")

        # Omxplayer creates these files on its first run after a reboot.
        # These files might not yet exist if omxplayer has not been started since the pi
        # was last rebooted.
        dbus_addr_file = None
        try:
            dbus_addr_file = open(dbus_addr_file_path)
        except Exception:
            self.__logger.debug(f"Unable to open {dbus_addr_file_path}")
            return False

        dbus_pid_file = None
        try:
            dbus_pid_file = open(dbus_pid_file_path)
        except Exception:
            self.__logger.debug(f"Unable to open {dbus_pid_file_path}")
            return False

        self.__dbus_addr = dbus_addr_file.read().strip()
        self.__dbus_pid = dbus_pid_file.read().strip()
        if self.__dbus_addr and self.__dbus_pid:
            return True
