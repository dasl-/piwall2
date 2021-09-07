import os
import shlex
import signal
import subprocess
import time

from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.playlist import Playlist
from piwall2.volumecontroller import VolumeController

# The Queue is responsible for playing the next video in the Playlist
class Queue:

    def __init__(self):
        self.__playlist = Playlist()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__orig_log_uuid = Logger.get_uuid()
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False

        # house keeping
        (VolumeController()).set_vol_pct(100)
        self.__playlist.clean_up_state()

    def run(self):
        # TODO: check for video skips here (rather than in the broadcaster process (which is the pifi model))
        while True:
            if self.__is_broadcast_in_progress:
                self.__maybe_skip_broadcast()
                if self.__broadcast_proc and self.__broadcast_proc.poll() is not None:
                    self.__logger.info("Ending broadcast because broadcast proc is no longer running...")
                    self.__stop_broadcast_if_broadcasting()

            next_item = self.__playlist.get_next_playlist_item()
            if next_item:
                self.__play_playlist_item(next_item)
            time.sleep(0.050)

    def __play_playlist_item(self, playlist_item):
        if playlist_item["type"] == Playlist.TYPE_VIDEO:
            if not self.__playlist.set_current_video(playlist_item["playlist_video_id"]):
                # Someone deleted the item from the queue in between getting the item and starting it.
                return
        self.__orig_log_uuid = Logger.get_uuid()
        log_uuid = Logger.make_uuid()
        Logger.set_uuid(log_uuid)
        cmd = (f"{DirectoryUtils().root_dir}/bin/broadcast --url {shlex.quote(playlist_item['url'])} " +
            f"--log-uuid {shlex.quote(log_uuid)}")
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
                if was_killed and exit_status == -signal.SIGTERM:
                    pass # We expect a specific non-zero exit code if the broadcast was killed.
                else:
                    self.__logger.error(f'Got non-zero exit_status for broadcast proc: {exit_status}')

        if self.__playlist_item:
            self.__playlist.end_video(self.__playlist_item["playlist_video_id"])

        Logger.set_uuid(self.__orig_log_uuid)
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False
