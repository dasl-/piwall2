import atexit
import os
import signal
import socket
import subprocess
import time
import traceback

from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.displaymode import DisplayMode
from piwall2.logger import Logger
from piwall2.receiver.omxplayercontroller import OmxplayerController
from piwall2.receiver.receivercommandbuilder import ReceiverCommandBuilder
from piwall2.tv import Tv
from piwall2.volumecontroller import VolumeController

class Receiver:

    VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES = 1024 * 1024 * 400 # 400 MB

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Started receiver!")

        self.__hostname = socket.gethostname() + ".local"

        # The current crop modes for up to two TVs that may be hooked up to this receiver
        self.__display_mode = DisplayMode.DISPLAY_MODE_TILE
        self.__display_mode2 = DisplayMode.DISPLAY_MODE_TILE

        self.__video_crop_args = None
        self.__video_crop_args2 = None
        self.__loading_screen_crop_args = None
        self.__loading_screen_crop_args2 = None

        config_loader = ConfigLoader()
        self.__receiver_config_stanza = config_loader.get_own_receiver_config_stanza()
        self.__receiver_command_builder = ReceiverCommandBuilder(config_loader, self.__receiver_config_stanza)
        self.__tv_ids = self.__get_tv_ids_by_tv_num()

        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()

        # Store the PGIDs separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__is_video_playback_in_progress = False
        self.__receive_and_play_video_proc = None
        self.__receive_and_play_video_proc_pgid = None

        self.__is_loading_screen_playback_in_progress = False
        self.__loading_screen_proc = None
        self.__loading_screen_pgid = None

        # house keeping
        # Set the video player volume to 50%, but set the hardware volume to 100%.
        self.__video_player_volume_pct = 50
        (VolumeController()).set_vol_pct(100)
        self.__disable_terminal_output()
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
        self.__logger.debug(f"Received control message {ctrl_msg}.")

        if self.__is_video_playback_in_progress:
            if self.__receive_and_play_video_proc and self.__receive_and_play_video_proc.poll() is not None:
                self.__logger.info("Ending video playback because receive_and_play_video_proc is no longer running...")
                self.__stop_video_playback_if_playing(stop_loading_screen_playback = True)

        if self.__is_loading_screen_playback_in_progress:
            if self.__loading_screen_proc and self.__loading_screen_proc.poll() is not None:
                self.__logger.info("Ending loading screen playback because loading_screen_proc is no longer running...")
                self.__stop_loading_screen_playback_if_playing(reset_log_uuid = False)

        msg_type = ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY]
        if msg_type == ControlMessageHelper.TYPE_INIT_VIDEO:
            self.__stop_video_playback_if_playing(stop_loading_screen_playback = False)
            self.__receive_and_play_video_proc = self.__receive_and_play_video(ctrl_msg)
            self.__receive_and_play_video_proc_pgid = os.getpgid(self.__receive_and_play_video_proc.pid)
        if msg_type == ControlMessageHelper.TYPE_PLAY_VIDEO:
            if self.__is_video_playback_in_progress:
                if self.__receiver_config_stanza['is_dual_video_output']:
                    dbus_names = [OmxplayerController.TV1_VIDEO_DBUS_NAME, OmxplayerController.TV2_VIDEO_DBUS_NAME]
                else:
                    dbus_names = [OmxplayerController.TV1_VIDEO_DBUS_NAME]
                self.__omxplayer_controller.play(dbus_names)
        elif msg_type == ControlMessageHelper.TYPE_SKIP_VIDEO:
            self.__stop_video_playback_if_playing(stop_loading_screen_playback = True)
        elif msg_type == ControlMessageHelper.TYPE_VOLUME:
            self.__video_player_volume_pct = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
            vol_pairs = {}
            if self.__is_video_playback_in_progress:
                vol_pairs[OmxplayerController.TV1_VIDEO_DBUS_NAME] = self.__video_player_volume_pct
                if self.__receiver_config_stanza['is_dual_video_output']:
                    vol_pairs[OmxplayerController.TV2_VIDEO_DBUS_NAME] = self.__video_player_volume_pct
            if self.__is_loading_screen_playback_in_progress:
                vol_pairs[OmxplayerController.TV1_LOADING_SCREEN_DBUS_NAME] = self.__video_player_volume_pct
                if self.__receiver_config_stanza['is_dual_video_output']:
                    vol_pairs[OmxplayerController.TV2_LOADING_SCREEN_DBUS_NAME] = self.__video_player_volume_pct
            self.__omxplayer_controller.set_vol_pct(vol_pairs)
        elif msg_type == ControlMessageHelper.TYPE_DISPLAY_MODE:
            display_mode_by_tv_id = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
            for tv_num, tv_id in self.__tv_ids.items():
                if tv_id in display_mode_by_tv_id:
                    display_mode_to_set = display_mode_by_tv_id[tv_id]
                    if display_mode_to_set not in DisplayMode.DISPLAY_MODES:
                        display_mode_to_set = DisplayMode.DISPLAY_MODE_TILE
                    if tv_num == 1:
                        self.__display_mode = display_mode_to_set
                    else:
                        self.__display_mode2 = display_mode_to_set

            crop_pairs = {}
            if self.__is_video_playback_in_progress:
                if self.__video_crop_args:
                    crop_pairs[OmxplayerController.TV1_VIDEO_DBUS_NAME] = self.__video_crop_args[self.__display_mode]
                if (
                    self.__receiver_config_stanza['is_dual_video_output'] and self.__video_crop_args2
                ):
                    crop_pairs[OmxplayerController.TV2_VIDEO_DBUS_NAME] = self.__video_crop_args2[self.__display_mode2]
            if self.__is_loading_screen_playback_in_progress:
                if self.__loading_screen_crop_args:
                    crop_pairs[OmxplayerController.TV1_LOADING_SCREEN_DBUS_NAME] = self.__loading_screen_crop_args[self.__display_mode]
                if (
                    self.__receiver_config_stanza['is_dual_video_output'] and self.__loading_screen_crop_args2
                ):
                    crop_pairs[OmxplayerController.TV2_LOADING_SCREEN_DBUS_NAME] = self.__loading_screen_crop_args2[self.__display_mode2]
            self.__omxplayer_controller.set_crop(crop_pairs)
        elif msg_type == ControlMessageHelper.TYPE_SHOW_LOADING_SCREEN:
            self.__loading_screen_proc = self.__show_loading_screen(ctrl_msg)
            self.__loading_screen_pgid = os.getpgid(self.__loading_screen_proc.pid)
        elif msg_type == ControlMessageHelper.TYPE_END_LOADING_SCREEN:
            self.__stop_loading_screen_playback_if_playing(reset_log_uuid = False)

    def __receive_and_play_video(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        Logger.set_uuid(ctrl_msg_content['log_uuid'])
        cmd, self.__video_crop_args, self.__video_crop_args2 = (
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

    def __show_loading_screen(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        Logger.set_uuid(ctrl_msg_content['log_uuid'])
        cmd, self.__loading_screen_crop_args, self.__loading_screen_crop_args2 = (
            self.__receiver_command_builder.build_loading_screen_command_and_get_crop_args(
                self.__video_player_volume_pct, self.__display_mode, self.__display_mode2,
                ctrl_msg_content['loading_screen_data']
            )
        )
        self.__logger.info(f"Showing loading screen with command: {cmd}")
        self.__is_loading_screen_playback_in_progress = True
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )
        return proc

    def __stop_video_playback_if_playing(self, stop_loading_screen_playback):
        if stop_loading_screen_playback:
            self.__stop_loading_screen_playback_if_playing(reset_log_uuid = False)
        if not self.__is_video_playback_in_progress:
            if stop_loading_screen_playback:
                Logger.set_uuid('')
            return
        if self.__receive_and_play_video_proc_pgid:
            self.__logger.info("Killing receive_and_play_video proc (if it's still running)...")
            try:
                os.killpg(self.__receive_and_play_video_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        Logger.set_uuid('')
        self.__is_video_playback_in_progress = False
        self.__video_crop_args = None
        self.__video_crop_args2 = None

    def __stop_loading_screen_playback_if_playing(self, reset_log_uuid):
        if not self.__is_loading_screen_playback_in_progress:
            return
        if self.__loading_screen_pgid:
            self.__logger.info("Killing loading_screen proc (if it's still running)...")
            try:
                os.killpg(self.__loading_screen_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        if reset_log_uuid:
            Logger.set_uuid('')
        self.__is_loading_screen_playback_in_progress = False
        self.__loading_screen_crop_args = None
        self.__loading_screen_crop_args2 = None

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

    # Display a black image so that terminal text output doesn't show up on the TVs in between videos.
    # Basically this black image will be on display all the time "underneath" any videos that are playing.
    def __disable_terminal_output(self):
        subprocess.check_output(
            f"sudo fbi -T 1 --noverbose --autozoom {DirectoryUtils().root_dir}/assets/black_screen.jpg",
            shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT
        )
        atexit.register(self.__enable_terminal_output)

    def __enable_terminal_output(self):
        try:
            subprocess.check_output(
                "sudo pkill fbi", shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT
            )
        except Exception:
            pass

    # Get the tv_ids for this receiver
    def __get_tv_ids_by_tv_num(self):
        tv_ids = {
            1: Tv(self.__hostname, 1).tv_id
        }
        if self.__receiver_config_stanza['is_dual_video_output']:
            tv_ids[2] = Tv(self.__hostname, 2).tv_id
        return tv_ids
