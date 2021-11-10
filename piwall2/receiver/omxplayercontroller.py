import getpass
import math
import re
import shlex
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
    TV1_LOADING_SCREEN_DBUS_NAME = 'piwall.tv1.loadingscreen'
    TV2_VIDEO_DBUS_NAME = 'piwall.tv2.video'
    TV2_LOADING_SCREEN_DBUS_NAME = 'piwall.tv2.loadingscreen'

    __DBUS_TIMEOUT_MS = 2000
    __PARALLEL_DELIM = '_'
    __PARALLEL_CMD_PREFIX = (f"parallel --will-cite --delimiter {__PARALLEL_DELIM} --max-args=2 --link --max-procs 0 " +
        # Run all jobs even if one or more failed.
        # Exit status: 1-100 Some of the jobs failed. The exit status gives the number of failed jobs.
        "--halt never ")

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__user = getpass.getuser()
        self.__dbus_addr = None
        self.__dbus_pid = None
        self.__load_dbus_session_info()

    # gets a perceptual loudness %
    # returns a float in the range [0, 100]
    # TODO: update this to account for multiple dbus names
    def get_vol_pct(self):
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

    # pairs: a dict where each key is a dbus name and each value is a vol_pct.
    # vol_pct should be a float in the range [0, 100]. This is a perceptual loudness %.
    # e.g.: {'piwall.tv1.video': 99.8}
    def set_vol_pct(self, pairs):
        num_pairs = len(pairs)
        if num_pairs <= 0:
            return

        vol_template = (
            'sudo -u ' + self.__user + ' ' +
            'DBUS_SESSION_BUS_ADDRESS=' + self.__dbus_addr + ' ' +
            'DBUS_SESSION_BUS_PID=' + self.__dbus_pid + ' ' +
            'dbus-send --print-reply=literal --session --reply-timeout=' + str(self.__DBUS_TIMEOUT_MS) + ' ' +
            '--dest={0} /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Set ' +
            "string:'org.mpris.MediaPlayer2.Player' string:'Volume' double:{1}")

        if num_pairs == 1:
            dbus_name, vol_pct = list(pairs.items())[0]
            omx_vol_pct = self.__vol_pct_to_omx_vol_pct(vol_pct)
            cmd = vol_template.format(dbus_name, omx_vol_pct)
        else:
            parallel_crop_template = shlex.quote(vol_template.format('{1}', '{2}'))
            dbus_names = self.__PARALLEL_DELIM.join(pairs.keys())
            omx_vol_pcts = self.__PARALLEL_DELIM.join(
                map(
                    str,
                    map(self.__vol_pct_to_omx_vol_pct, pairs.values())
                )
            )
            cmd = f"{self.__PARALLEL_CMD_PREFIX} {parallel_crop_template} ::: {dbus_names} ::: {omx_vol_pcts}"

        start = time.time()
        try:
            vol_cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT))
        except Exception:
            self.__logger.debug(f"failed to set omxplayer volume with command: [{cmd}] for {', '.join(pairs.keys())}.")
            return False
        elapsed_ms = (time.time() - start) * 1000
        self.__logger.debug(f"set volume after {elapsed_ms}ms for {', '.join(pairs.keys())}.")
        return True

    # pairs: a dict where each key is a dbus name and each value is a crop string ("x1 y1 x2 y2")
    # e.g.: {'piwall.tv1.video': '0 0 100 100'}
    def set_crop(self, pairs):
        num_pairs = len(pairs)
        if num_pairs <= 0:
            return

        crop_template = (
            'sudo -u ' + self.__user + ' ' +
            'DBUS_SESSION_BUS_ADDRESS=' + self.__dbus_addr + ' ' +
            'DBUS_SESSION_BUS_PID=' + self.__dbus_pid + ' ' +
            'dbus-send --print-reply=literal --session --reply-timeout=' + str(self.__DBUS_TIMEOUT_MS) + ' ' +
            '--dest={0} /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.SetVideoCropPos ' +
            "objpath:/not/used string:'{1}'")

        if num_pairs == 1:
            dbus_name, crop_string = list(pairs.items())[0]
            cmd = crop_template.format(dbus_name, crop_string)
        else:
            parallel_crop_template = shlex.quote(crop_template.format('{1}', '{2}'))
            dbus_names = self.__PARALLEL_DELIM.join(pairs.keys())
            crop_strings = self.__PARALLEL_DELIM.join(pairs.values())
            cmd = f"{self.__PARALLEL_CMD_PREFIX} {parallel_crop_template} ::: {dbus_names} ::: {crop_strings}"

        start = time.time()
        try:
            cmd_output = (subprocess
                .check_output(cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT))
        except Exception:
            self.__logger.debug(f"failed to set omxplayer crop position for {', '.join(pairs.keys())}")
            return False
        elapsed_ms = (time.time() - start) * 1000

        self.__logger.debug(f"set crop position after {elapsed_ms}ms for {', '.join(pairs.keys())}.")
        return True

    # omxplayer uses a different algorithm for computing volume percentage from the original millibels than
    # our VolumeController class uses. Convert to omxplayer's equivalent percentage for a smoother volume
    # adjustment experience.
    def __vol_pct_to_omx_vol_pct(self, vol_pct):
        # See: https://github.com/popcornmix/omxplayer#volume-rw
        millibels = VolumeController.pct_to_millibels(vol_pct)
        omx_vol_pct = math.pow(10, millibels / 2000)
        omx_vol_pct = max(omx_vol_pct, 0)
        omx_vol_pct = min(omx_vol_pct, 1)
        return omx_vol_pct

    # Returns a boolean. True if the session was loaded or already loaded, false if we failed to load.
    def __load_dbus_session_info(self):
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
