import getpass
import math
import re
import shlex
import subprocess

from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

# Controls omxplayer via dbus.
# See:
# https://github.com/popcornmix/omxplayer/blob/master/dbuscontrol.sh
# https://github.com/popcornmix/omxplayer#dbus-control
class OmxplayerController:

    TV1_VIDEO_DBUS_NAME = 'piwall.tv1.video'
    TV1_LOADING_SCREEN_DBUS_NAME = 'piwall.tv1.loadingscreen'
    TV2_VIDEO_DBUS_NAME = 'piwall.tv2.video'
    TV2_LOADING_SCREEN_DBUS_NAME = 'piwall.tv2.loadingscreen'

    __DBUS_TIMEOUT_MS = 2000
    __PARALLEL_CMD_TEMPLATE_PREFIX = (
        f"parallel --will-cite --link --max-procs 0 " +
        # Run all jobs even if one or more failed.
        # Exit status: 1-100 Some of the jobs failed. The exit status gives the number of failed jobs.
        "--halt never ")

    # Ensure we don't have too many processes in flight that could overload CPU.
    # Need to track the limits separately because in Queue.__maybe_set_receiver_state,
    # we set volume and display_mode in quick succession. If we had a global limit of 1,
    # we'd risk that the display_mode never gets set due to throttling.
    __MAX_IN_FLIGHT_VOL_PROCS = 1
    __MAX_IN_FLIGHT_CROP_PROCS = 1

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__user = getpass.getuser()
        self.__dbus_addr = None
        self.__dbus_pid = None
        self.__load_dbus_session_info()
        self.__in_flight_vol_procs = []
        self.__in_flight_crop_procs = []

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

        if self.__are_too_many_procs_in_flight(self.__in_flight_vol_procs, self.__MAX_IN_FLIGHT_VOL_PROCS):
            self.__logger.warning("Too many in-flight dbus processes; bailing without setting volume.")
            return

        vol_template = (self.__get_dbus_cmd_template_prefix() +
            "org.freedesktop.DBus.Properties.Set string:'org.mpris.MediaPlayer2.Player' " +
            "string:'Volume' double:{1} >/dev/null 2>&1")

        if num_pairs == 1:
            dbus_name, vol_pct = list(pairs.items())[0]
            omx_vol_pct = self.__vol_pct_to_omx_vol_pct(vol_pct)
            cmd = vol_template.format(dbus_name, omx_vol_pct)
        else:
            parallel_vol_template = shlex.quote(vol_template.format('{1}', '{2}'))
            dbus_names = ''
            omx_vol_pcts = ''
            for dbus_name, vol_pct in pairs.items():
                dbus_names += dbus_name + ' '
                omx_vol_pcts += str(self.__vol_pct_to_omx_vol_pct(vol_pct)) + ' '
            dbus_names = dbus_names.strip()
            omx_vol_pcts = omx_vol_pcts.strip()
            cmd = (f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX} {parallel_vol_template} ::: {dbus_names} " +
                f"::: {omx_vol_pcts}")

        self.__logger.debug(f"dbus_cmd vol_cmd: {cmd}")

        # Send dbus commands in non-blocking fashion so that the receiver process is free to handle other input.
        # Dbus can sometimes take a while to execute. Starting the subprocess takes about 3-20ms
        proc = subprocess.Popen(cmd, shell = True, executable = '/usr/bin/bash')
        self.__in_flight_vol_procs.append(proc)

    # pairs: a dict where each key is a dbus name and each value is a list of crop coordinates
    # e.g.: {'piwall.tv1.video': (0, 0, 100, 100)}
    def set_crop(self, pairs):
        num_pairs = len(pairs)
        if num_pairs <= 0:
            return

        if self.__are_too_many_procs_in_flight(self.__in_flight_crop_procs, self.__MAX_IN_FLIGHT_CROP_PROCS):
            self.__logger.warning("Too many in-flight dbus processes; bailing without setting crop.")
            return

        crop_template = (self.__get_dbus_cmd_template_prefix() +
            "org.mpris.MediaPlayer2.Player.SetVideoCropPos objpath:/not/used string:'{1}' >/dev/null 2>&1")

        if num_pairs == 1:
            dbus_name, crop_coords = list(pairs.items())[0]
            cmd = crop_template.format(
                dbus_name,
                OmxplayerController.crop_coordinate_list_to_string(crop_coords)
            )
        else:
            parallel_crop_template = shlex.quote(crop_template.format('{1}', '{2} {3} {4} {5}'))
            dbus_names = ''
            crop_x1s = crop_y1s = crop_x2s = crop_y2s = ''
            for dbus_name, crop_coords in pairs.items():
                dbus_names += dbus_name + ' '
                x1, y1, x2, y2 = crop_coords
                crop_x1s += f'{x1} '
                crop_y1s += f'{y1} '
                crop_x2s += f'{x2} '
                crop_y2s += f'{y2} '
            dbus_names = dbus_names.strip()
            crop_x1s = crop_x1s.strip()
            crop_y1s = crop_y1s.strip()
            crop_x2s = crop_x2s.strip()
            crop_y2s = crop_y2s.strip()
            cmd = (f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX} {parallel_crop_template} ::: {dbus_names} " +
                f"::: {crop_x1s} ::: {crop_y1s} ::: {crop_x2s} ::: {crop_y2s}")

        self.__logger.debug(f"dbus_cmd crop_cmd: {cmd}")

        # Send dbus commands in non-blocking fashion so that the receiver process is free to handle other input.
        # Dbus can sometimes take a while to execute. Starting the subprocess takes about 3-20ms
        proc = subprocess.Popen(cmd, shell = True, executable = '/usr/bin/bash')
        self.__in_flight_crop_procs.append(proc)

    @staticmethod
    def crop_coordinate_list_to_string(crop_coord_list):
        if not crop_coord_list:
            return ''
        return ' '.join([str(e) for e in crop_coord_list])

    # start playback / unpause the video
    def play(self, dbus_names):
        num_dbus_names = len(dbus_names)
        if num_dbus_names <= 0:
            return

        # Don't check if too many procs are in flight, because we never want to ignore a play command.
        # This is used to start the video playback in sync across all the TVs.

        play_template = (self.__get_dbus_cmd_template_prefix() +
            "org.mpris.MediaPlayer2.Player.Play >/dev/null 2>&1")
        if num_dbus_names == 1:
            cmd = play_template.format(dbus_names[0])
        else:
            parallel_play_template = shlex.quote(play_template.format('{1}'))
            dbus_names_str = ' '.join(dbus_names.keys())
            cmd = f"{self.__PARALLEL_CMD_TEMPLATE_PREFIX} {parallel_play_template} ::: {dbus_names_str} "

        self.__logger.debug(f"dbus_cmd play_cmd: {cmd}")

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
        return round(omx_vol_pct, 2)

    def __are_too_many_procs_in_flight(self, in_flight_procs, max_procs):
        updated_in_flight_procs = []
        for proc in in_flight_procs:
            if proc.poll() is None:
                updated_in_flight_procs.append(proc)

        # modify in_flight_procs in place so that all references are updated
        in_flight_procs.clear()
        in_flight_procs.extend(updated_in_flight_procs)
        if len(in_flight_procs) >= max_procs:
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
