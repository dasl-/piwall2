import os
import signal
import socket
import subprocess
import time
import traceback

from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.receiver.omxplayercontroller import OmxplayerController
from piwall2.receiver.receivercommandbuilder import ReceiverCommandBuilder
from piwall2.volumecontroller import VolumeController

class Receiver:

    VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES = 1024 * 1024 * 400 # 400 MB

    # Tile mode is like this: https://i.imgur.com/BBrA1Cr.png
    # Repeat mode is like this: https://i.imgur.com/cpS61s8.png
    DISPLAY_MODE_TILE = 'DISPLAY_MODE_TILE'
    DISPLAY_MODE_REPEAT = 'DISPLAY_MODE_REPEAT'

    __DEFAULT_CROP_ARGS = {
        DISPLAY_MODE_TILE: None,
        DISPLAY_MODE_REPEAT: None,
    }

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Started receiver!")

        self.__hostname = socket.gethostname() + ".local"
        self.__local_ip_address = self.__get_local_ip()

        # The current crop modes for up to two TVs that may be hooked up to this receiver
        self.__display_mode = self.DISPLAY_MODE_TILE
        self.__display_mode2 = self.DISPLAY_MODE_TILE

        # Crop arguments to send to omxplayer for the currently playing video if the display mode changes.
        # These change per video, thus we just initialize them to dummy values in the constructor.
        self.__crop_args = self.__DEFAULT_CROP_ARGS
        self.__crop_args2 = self.__DEFAULT_CROP_ARGS

        self.__config_loader = ConfigLoader()
        self.__receiver_command_builder = ReceiverCommandBuilder(
            self.__config_loader, self.__hostname, self.__local_ip_address
        )
        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__orig_log_uuid = Logger.get_uuid()
        self.__is_video_playback_in_progress = False
        self.__receive_and_play_video_proc = None
        # Store the PGID separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__receive_and_play_video_proc_pgid = None

        # house keeping
        # Set the video player volume to 50%, but set the hardware volume to 100%.
        self.__video_player_volume_pct = 50
        (VolumeController()).set_vol_pct(100)
        self.__play_warmup_video()

        # This must come after the warmup video. When run as a systemd service, omxplayer wants to
        # start new dbus sessions / processes every time the service is restarted. This means it will
        # create new dbus files in /tmp when the first video is played after the service is restarted
        # But the old files will still be in /tmp. So if we initialize the OmxplayerController before
        # the new dbus files are created by playing the first video since restarting the service, we
        # will be reading stale dbus info from the files in /tmp.
        self.__omxplayer_controller = OmxplayerController()

    def run(self):
        while True:
            try:
                self.__run_internal()
            except Exception:
                self.__logger.error('Caught exception: {}'.format(traceback.format_exc()))

    def __run_internal(self):
        ctrl_msg = None
        ctrl_msg = self.__control_message_helper.receive_msg() # This blocks until a message is received!
        self.__logger.debug(f"Received control message {ctrl_msg}. " +
            f"self.__is_video_playback_in_progress: {self.__is_video_playback_in_progress}.")

        if self.__is_video_playback_in_progress:
            if self.__receive_and_play_video_proc and self.__receive_and_play_video_proc.poll() is not None:
                self.__logger.info("Ending video playback because receive_and_play_video_proc is no longer running...")
                self.__stop_video_playback_if_playing()

        msg_type = ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY]
        if msg_type == ControlMessageHelper.TYPE_PLAY_VIDEO:
            self.__stop_video_playback_if_playing()
            self.__receive_and_play_video_proc = self.__receive_and_play_video(ctrl_msg)
            self.__receive_and_play_video_proc_pgid = os.getpgid(self.__receive_and_play_video_proc.pid)
        elif msg_type == ControlMessageHelper.TYPE_SKIP_VIDEO:
            if self.__is_video_playback_in_progress:
                self.__stop_video_playback_if_playing()
        elif msg_type == ControlMessageHelper.TYPE_VOLUME:
            self.__video_player_volume_pct = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
            if self.__is_video_playback_in_progress:
                self.__omxplayer_controller.set_vol_pct(self.__video_player_volume_pct)
        elif msg_type == ControlMessageHelper.TYPE_DISPLAY_MODE:
            display_mode = ctrl_msg[ControlMessageHelper.CONTENT_KEY]['display_mode']
            tvs_to_set_display_mode_on = ctrl_msg[ControlMessageHelper.CONTENT_KEY]['tvs']
            should_set_display_mode_on_this_receiver = False
            for tv in tvs_to_set_display_mode_on:
                if self.__is_hostname_this_receiver(tv['hostname']):
                    should_set_display_mode_on_this_receiver = True
                    if tv['tv_id'] == 1:
                        self.__display_mode = display_mode
                    elif tv['tv_id'] == 2:
                        self.__display_mode2 = display_mode
            if self.__is_video_playback_in_progress and should_set_display_mode_on_this_receiver:
                if display_mode == self.DISPLAY_MODE_REPEAT:
                    self.__omxplayer_controller.set_crop(self.__crop_args[self.DISPLAY_MODE_REPEAT])
                else:
                    self.__omxplayer_controller.set_crop(self.__crop_args[self.DISPLAY_MODE_TILE])

    def __receive_and_play_video(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        self.__orig_log_uuid = Logger.get_uuid()
        Logger.set_uuid(ctrl_msg_content['log_uuid'])
        cmd, self.__crop_args, self.__crop_args2 = (
            self.__receiver_command_builder.build_receive_and_play_video_command_and_get_crop_args(
                ctrl_msg_content['log_uuid'], ctrl_msg_content['video_width'],
                ctrl_msg_content['video_height'], self.__video_player_volume_pct,
                self.__display_mode, self.__display_mode2
            )
        )
        self.__logger.info(f"Running receive_and_play_video command: {cmd}")
        self.__is_video_playback_in_progress = True
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )
        return proc

    def __stop_video_playback_if_playing(self):
        if not self.__is_video_playback_in_progress:
            return
        if self.__receive_and_play_video_proc_pgid:
            self.__logger.info("Killing receive_and_play_video proc (if it's still running)...")
            try:
                os.killpg(self.__receive_and_play_video_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        Logger.set_uuid(self.__orig_log_uuid)
        self.__is_video_playback_in_progress = False

    # The first video that is played after a system restart appears to have a lag in starting,
    # which can affect video synchronization across the receivers. Ensure we have played at
    # least one video since system startup. This is a short, one-second video.
    #
    # Perhaps one thing this warmup video does is start the various dbus processes for the first
    # time, which can involve some sleeps:
    # https://github.com/popcornmix/omxplayer/blob/1f1d0ccd65d3a1caa86dc79d2863a8f067c8e3f8/omxplayer#L50-L59
    #
    # When the receiver is run as as a systemd service, the first time a video is played after the service
    # is restarted, it seems that omxplayer must initialize dbus. Thus, it is important to run the warmup
    # video whenever the service is restarted.
    #
    # This is as opposed to when running the service as a regular user / process -- the dbus stuff stays
    # initialized until the pi is rebooted.
    def __play_warmup_video(self):
        self.__logger.info("Playing receiver warmup video...")
        warmup_cmd = f'omxplayer --vol 0 {DirectoryUtils().root_dir}/utils/short_black_screen.ts'
        proc = subprocess.Popen(
            warmup_cmd, shell = True, executable = '/usr/bin/bash'
        )
        while proc.poll() is None:
            time.sleep(0.1)
        if proc.returncode != 0:
            raise Exception(f"The process for cmd: [{warmup_cmd}] exited non-zero: " +
                f"{proc.returncode}.")

    def __is_hostname_this_receiver(self, hostname):
        if self.__hostname == hostname or self.__local_ip_address == hostname:
            return True
        return False

    def __get_local_ip(self):
        return (subprocess
            .check_output(
                'set -o pipefail && sudo ifconfig | grep -Eo \'inet (addr:)?([0-9]*\.){3}[0-9]*\' | ' +
                'grep -Eo \'([0-9]*\.){3}[0-9]*\' | grep -v \'127.0.0.1\'',
                stderr = subprocess.STDOUT, shell = True, executable = '/bin/bash'
            )
            .decode("utf-8")
            .strip()
        )
