import os
import random
import shlex
import signal
import subprocess
import time

from piwall2.animator import Animator
from piwall2.broadcaster.loadingscreenhelper import LoadingScreenHelper
from piwall2.broadcaster.playlist import Playlist
from piwall2.broadcaster.remote import Remote
from piwall2.broadcaster.screensaverhelper import ScreensaverHelper
from piwall2.config import Config
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

# The Queue is responsible for playing the next video in the Playlist
class Queue:

    __TICKS_PER_SECOND = 10
    __RECEIVER_VOLUME_SETS_PER_SECOND = 0.5

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting queue...")
        self.__config_loader = ConfigLoader()
        self.__playlist = Playlist()
        self.__volume_controller = VolumeController()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__last_tick_time = 0
        self.__last_set_receiver_vol_time = 0
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False
        self.__animator = Animator(self.__TICKS_PER_SECOND)
        self.__remote = Remote(self.__TICKS_PER_SECOND)
        self.__loading_screen_helper = LoadingScreenHelper()

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
            else:
                next_item = self.__playlist.get_next_playlist_item()
                if next_item:
                    self.__play_playlist_item(next_item)
                else:
                    self.__play_screensaver()
            self.__tick_animation_and_set_receiver_state()
            self.__remote.check_for_input_and_handle(self.__playlist_item)

            time.sleep(0.050)

    def __play_playlist_item(self, playlist_item):
        if not self.__playlist.set_current_video(playlist_item["playlist_video_id"]):
            # Someone deleted the item from the queue in between getting the item and starting it.
            return
        log_uuid = Logger.make_uuid()
        Logger.set_uuid(log_uuid)
        self.__logger.info(f"Starting broadcast for playlist_video_id: {playlist_item['playlist_video_id']}")
        self.__loading_screen_helper.send_loading_screen_signal(log_uuid)
        self.__do_broadcast(playlist_item['url'], log_uuid)
        self.__playlist_item = playlist_item

    def __play_screensaver(self):
        use_channel_videos_as_screensavers = Config.get('use_channel_videos_as_screensavers', False)
        use_screensavers = Config.get('use_screensavers', True)

        if not use_channel_videos_as_screensavers and not use_screensavers:
            return

        log_uuid = 'SCREENSAVER__' + Logger.make_uuid()
        Logger.set_uuid(log_uuid)

        if use_channel_videos_as_screensavers:
            self.__remote.increment_channel()
            screensaver_video_path = self.__remote.get_video_path_for_current_channel()
            if screensaver_video_path is None:
                self.__logger.info("No screensavers found in channel video config.")
                Logger.set_uuid('')
                return
        else: # use_screensavers
            screensaver_data = ScreensaverHelper().choose_random_screensaver()
            if screensaver_data is None:
                self.__logger.info("No screensavers found in config.")
                Logger.set_uuid('')
                return
            screensaver_video_path = screensaver_data['video_path']

        self.__logger.info("Starting broadcast of screensaver...")
        self.__do_broadcast(screensaver_video_path, log_uuid)

    def __do_broadcast(self, url, log_uuid):
        cmd = (f"{DirectoryUtils().root_dir}/bin/broadcast --url {shlex.quote(url)} " +
            f"--log-uuid {shlex.quote(log_uuid)} --no-show-loading-screen")
        # Using start_new_session = False here because it is not necessary to start a new session here (though
        # it should not hurt if we were to set it to True either)
        self.__broadcast_proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = False
        )
        self.__is_broadcast_in_progress = True

    def __maybe_skip_broadcast(self):
        if not self.__is_broadcast_in_progress:
            return

        should_skip = False
        if self.__playlist_item:
            try:
                # Might result in: `sqlite3.OperationalError: database is locked`, when DB is under load
                should_skip = self.__playlist.should_skip_video_id(self.__playlist_item['playlist_video_id'])
            except Exception as e:
                self.__logger.info(f"Caught exception: {e}.")
        elif self.__is_screensaver_broadcast_in_progress():
            should_skip = self.__playlist.get_next_playlist_item() is not None

        if should_skip:
            self.__stop_broadcast_if_broadcasting(was_skipped = True)
            return True

        return False

    def __is_screensaver_broadcast_in_progress(self):
        return self.__is_broadcast_in_progress and self.__playlist_item is None

    def __stop_broadcast_if_broadcasting(self, was_skipped = False):
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
                if was_killed and abs(exit_status) == signal.SIGTERM:
                    pass # We expect a specific non-zero exit code if the broadcast was killed.
                else:
                    self.__logger.error(f'Got non-zero exit_status for broadcast proc: {exit_status}')

        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SKIP_VIDEO, {})

        if self.__playlist_item:
            if self.__should_reenqueue_current_playlist_item(was_skipped):
                self.__playlist.reenqueue(self.__playlist_item["playlist_video_id"])
            else:
                self.__playlist.end_video(self.__playlist_item["playlist_video_id"])

        self.__logger.info("Ended video broadcast.")
        Logger.set_uuid('')
        self.__broadcast_proc = None
        self.__playlist_item = None
        self.__is_broadcast_in_progress = False

    """
    Starting a channel video causes the currently playing video to immediately be skipped. Playing a lot of channel
    videos in quick succession could therefore cause the playlist queue to become depleted without the videos even
    having had a chance to play.

    Thus, when we are skipping a video, we check if a channel video is the next item in the queue. If so, we
    reenqueue the video so as not to deplete the queue when a lot of channel videos are being played.
    """
    def __should_reenqueue_current_playlist_item(self, was_current_playlist_item_skipped):
        if self.__playlist_item["type"] != Playlist.TYPE_VIDEO:
            return False

        if not was_current_playlist_item_skipped:
            return False

        next_playlist_item = self.__playlist.get_next_playlist_item()
        if next_playlist_item and next_playlist_item["type"] == Playlist.TYPE_CHANNEL_VIDEO:
            return True

        return False

    # Set all receiver state on an interval to ensure eventual consistency.
    # We already set all state from the server in response to user UI actions (adjusting volume, toggling display mode)
    #
    # Possible failure scenarios:
    # 1) A UDP packet was dropped, so a receiver missed setting some state adjustment. This seems unlikely given that
    #   we tuned everything to minimize UDP packet loss (very important for a successful video broadcast).
    # 2) We ignored setting state the first time due to throttling to avoid being overwhelmed with user state modification.
    #   See: OmxplayerController.__MAX_IN_FLIGHT_PROCS
    # 3) A receiver process was restarted and thus lost its state.
    def __tick_animation_and_set_receiver_state(self):
        now = time.time()
        if (now - self.__last_tick_time) > (1 / self.__TICKS_PER_SECOND):
            # sets the display_mode of the TVs
            self.__animator.tick()
            self.__last_tick_time = now

        # maybe set volume
        if (now - self.__last_set_receiver_vol_time) > (1 / self.__RECEIVER_VOLUME_SETS_PER_SECOND):
            vol_pct = self.__volume_controller.get_vol_pct()
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, vol_pct)
            self.__last_set_receiver_vol_time = now
