import os
import shlex
import signal
import subprocess
import time

from piwall2.broadcaster.playlist import Playlist
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

# The Queue is responsible for playing the next video in the Playlist
class Queue:

    def __init__(self):
        self.__playlist = Playlist()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting queue...")
        self.__orig_log_uuid = Logger.get_uuid()
        self.__volume_controller = VolumeController()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__last_receiver_volume_set_time = 0
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False

        # house keeping
        self.__volume_controller.set_vol_pct(50)
        self.__playlist.clean_up_state()

    def run(self):
        while True:
            if self.__is_broadcast_in_progress:
                self.__maybe_skip_broadcast()
                if self.__broadcast_proc and self.__broadcast_proc.poll() is not None:
                    self.__logger.info("Ending broadcast because broadcast proc is no longer running...")
                    self.__stop_broadcast_if_broadcasting()
                self.__maybe_set_receiver_volume()
            else:
                next_item = self.__playlist.get_next_playlist_item()
                if next_item:
                    self.__play_playlist_item(next_item)
            time.sleep(0.050)

    def __play_playlist_item(self, playlist_item):
        if not self.__playlist.set_current_video(playlist_item["playlist_video_id"]):
            # Someone deleted the item from the queue in between getting the item and starting it.
            return
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SHOW_LOADING_SCREEN, {})
        self.__orig_log_uuid = Logger.get_uuid()
        log_uuid = Logger.make_uuid()
        Logger.set_uuid(log_uuid)
        self.__logger.info(f"Starting broadcast for playlist_video_id: {playlist_item['playlist_video_id']}")
        cmd = (f"{DirectoryUtils().root_dir}/bin/broadcast --url {shlex.quote(playlist_item['url'])} " +
            f"--log-uuid {shlex.quote(log_uuid)} --no-show-loading-screen")
        # Using start_new_session = False here because it is not necessary to start a new session here (though
        # it should not hurt if we were to set it to True either)
        self.__broadcast_proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = False
        )
        self.__playlist_item = playlist_item
        self.__is_broadcast_in_progress = True

    def __maybe_skip_broadcast(self):
        if not self.__is_broadcast_in_progress:
            return

        if self.__playlist.should_skip_video_id(self.__playlist_item['playlist_video_id']):
            self.__stop_broadcast_if_broadcasting()
            return True

        return False

    def __stop_broadcast_if_broadcasting(self):
        if not self.__is_broadcast_in_progress:
            return

        if self.__broadcast_proc:
            self.__logger.info("Killing broadcast proc (if it's still running)...")
            was_killed = True
            try:
                os.kill(self.__broadcast_proc.pid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                was_killed = False
            exit_status = self.__broadcast_proc.wait()
            if exit_status != 0:
                if was_killed and exit_status == signal.SIGTERM:
                    pass # We expect a specific non-zero exit code if the broadcast was killed.
                else:
                    self.__logger.error(f'Got non-zero exit_status for broadcast proc: {exit_status}')

        if self.__playlist_item:
            self.__playlist.end_video(self.__playlist_item["playlist_video_id"])

        self.__logger.info("Ended video broadcast.")
        Logger.set_uuid(self.__orig_log_uuid)
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False

    # We already set the volume in the server in response to a user setting the volume in the web UI.
    # Here we just ensure the change took effect by re-setting the volume every N seconds.
    #
    # Possible failure scenarios:
    # 1) A UDP packet was dropped, so a receiver missed a volume adjustment. This seems unlikely given that
    #   we tuned everything to minimize UDP packet loss (very important for a successful video broadcast).
    #
    # Perhaps this is not totally necessary to do -- we could simply rely on setting the volume in the
    # server in response to a user setting the volume in the web UI.
    def __maybe_set_receiver_volume(self):
        if not self.__is_broadcast_in_progress:
            return

        num_seconds_between_setting_volume = 2
        now = time.time()
        if (now - self.__last_receiver_volume_set_time) > num_seconds_between_setting_volume:
            vol_pct = self.__volume_controller.get_vol_pct()
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, vol_pct)
            self.__last_receiver_volume_set_time = now
