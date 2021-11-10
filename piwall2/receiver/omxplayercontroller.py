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
    __PARALLEL_CMD_TEMPLATE_PREFIX = (
        f"parallel --will-cite --delimiter {__PARALLEL_DELIM} --max-args={{0}} --link --max-procs 0 " +
        # Run all jobs even if one or more failed.
        # Exit status: 1-100 Some of the jobs failed. The exit status gives the number of failed jobs.
        "--halt never ")

    # Ensure we don't have too many processes in flight that could overload CPU
    __MAX_IN_FLIGHT_PROCS = 3

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__user = getpass.getuser()
        self.__dbus_addr = None
        self.__dbus_pid = None
        self.__load_dbus_session_info()
        self.__in_flight_procs = []

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

        if self.__are_too_many_procs_in_flight():
            self.__logger.warning("Too many in-flight dbus processes; bailing without setting volume.")
            return

        vol_template = (self.__get_dbus_cmd_template_prefix() +
            "org.freedesktop.DBus.Properties.Set string:'org.mpris.MediaPlayer2.Player' " +
            "string:'Volume' double:{1} >/dev/null")

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
            cmd = (f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX.format('2')} {parallel_crop_template} ::: {dbus_names} " +
                f"::: {omx_vol_pcts}")

        # Send dbus commands in non-blocking fashion so that the receiver process is free to handle other input.
        # Dbus can sometimes take a while to execute. Starting the subprocess takes about 3-20ms
        proc = subprocess.Popen(cmd, shell = True, executable = '/usr/bin/bash')
        self.__in_flight_procs.append(proc)

    # pairs: a dict where each key is a dbus name and each value is a crop string ("x1 y1 x2 y2")
    # e.g.: {'piwall.tv1.video': '0 0 100 100'}
    def set_crop(self, pairs):
        num_pairs = len(pairs)
        if num_pairs <= 0:
            return

        if self.__are_too_many_procs_in_flight():
            self.__logger.warning("Too many in-flight dbus processes; bailing without setting crop.")
            return

        crop_template = (self.__get_dbus_cmd_template_prefix() +
            "org.mpris.MediaPlayer2.Player.SetVideoCropPos objpath:/not/used string:'{1}' >/dev/null")

        if num_pairs == 1:
            dbus_name, crop_string = list(pairs.items())[0]
            cmd = crop_template.format(dbus_name, crop_string)
        else:
            parallel_crop_template = shlex.quote(crop_template.format('{1}', '{2}'))
            dbus_names = self.__PARALLEL_DELIM.join(pairs.keys())
            crop_strings = self.__PARALLEL_DELIM.join(pairs.values())
            cmd = (f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX.format('2')} {parallel_crop_template} ::: {dbus_names} " +
                f"::: {crop_strings}")

        # Send dbus commands in non-blocking fashion so that the receiver process is free to handle other input.
        # Dbus can sometimes take a while to execute. Starting the subprocess takes about 3-20ms
        proc = subprocess.Popen(cmd, shell = True, executable = '/usr/bin/bash')
        self.__in_flight_procs.append(proc)

    def unpause(self, dbus_names):
        num_dbus_names = len(dbus_names)
        if num_dbus_names <= 0:
            return

        # Don't check if too many procs are in flight, because we never want to ignore an unpause command.
        # This is used to start the video playback in sync across all the TVs.

        play_template = (self.__get_dbus_cmd_template_prefix() +
            "org.mpris.MediaPlayer2.Player.Play >/dev/null")
        if num_dbus_names == 1:
            cmd = play_template.format(dbus_names[0])
        else:
            parallel_play_template = shlex.quote(play_template.format('{1}'))
            dbus_names_str = self.__PARALLEL_DELIM.join(dbus_names.keys())
            cmd = f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX.format('1')} {parallel_play_template} ::: {dbus_names_str} "

        # Send dbus commands in non-blocking fashion so that the receiver process is free to handle other input.
        # Dbus can sometimes take a while to execute. Starting the subprocess takes about 3-20ms
        proc = subprocess.Popen(cmd, shell = True, executable = '/usr/bin/bash')

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

    def __are_too_many_procs_in_flight(self):
        updated_in_flight_procs = []
        for proc in self.__in_flight_procs:
            if proc.poll() is None:
                updated_in_flight_procs.append(proc)
        self.__in_flight_procs = updated_in_flight_procs
        if len(self.__in_flight_procs) >= self.__MAX_IN_FLIGHT_PROCS:
            return True
        return False

    def __get_dbus_cmd_template_prefix(self):
        dbus_timeout_s = self.__DBUS_TIMEOUT_MS / 1000 + 0.1
        dbus_kill_after_timeout_s = dbus_timeout_s + 0.1
        dbus_prefix = (
            f'sudo timeout --kill-after={dbus_kill_after_timeout_s} {dbus_timeout_s} '
            'sudo -u ' + self.__user + ' ' +
            'DBUS_SESSION_BUS_ADDRESS=' + self.__dbus_addr + ' ' +
            'DBUS_SESSION_BUS_PID=' + self.__dbus_pid + ' ' +
            'dbus-send --print-reply=literal --session --reply-timeout=' + str(self.__DBUS_TIMEOUT_MS) + ' ' +
            '--dest={0} /org/mpris/MediaPlayer2 ')
        return dbus_prefix

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
