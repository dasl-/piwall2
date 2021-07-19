import getpass
import re
import subprocess
from piwall2.logger import Logger

# Controls omxplayer via dbus.
# See:
# https://github.com/popcornmix/omxplayer/blob/master/dbuscontrol.sh
# https://github.com/popcornmix/omxplayer#dbus-control
class OmxplayerController:

    __DBUS_TIMEOUT_MS = 1500

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

        cmd = (f"DBUS_SESSION_BUS_ADDRESS={self.__dbus_addr} DBUS_SESSION_BUS_PID={self.__dbus_pid} dbus-send " +
            f"--print-reply=literal --session --reply-timeout={self.__DBUS_TIMEOUT_MS} " +
            "--dest=org.mpris.MediaPlayer2.omxplayer /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get " +
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

        vol_pct = vol_pct / 100
        vol_pct = max(0, vol_pct)
        vol_pct = min(1, vol_pct)
        cmd = (f"DBUS_SESSION_BUS_ADDRESS={self.__dbus_addr} DBUS_SESSION_BUS_PID={self.__dbus_pid} dbus-send " +
            f"--print-reply=literal --session --reply-timeout={self.__DBUS_TIMEOUT_MS} " +
            "--dest=org.mpris.MediaPlayer2.omxplayer /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Set " +
            f"string:'org.mpris.MediaPlayer2.Player' string:'Volume' double:{vol_pct}")
        try:
            vol_cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT))
        except Exception:
            return False
        return True

    # Returns a boolean. True if the session was loaded or already loaded, false if we failed to load.
    def __load_dbus_session_info_if_not_loaded(self):
        if self.__dbus_addr and self.__dbus_pid:
            return True # already loaded

        dbus_addr_file_path = f"/tmp/omxplayerdbus.{self.__user}"
        dbus_pid_file_path = f"/tmp/omxplayerdbus.{self.__user}.pid"

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

        self.__dbus_addr = dbus_addr_file.read()
        self.__dbus_pid = dbus_pid_file.read()
        if self.__dbus_addr and self.__dbus_pid:
            return True
