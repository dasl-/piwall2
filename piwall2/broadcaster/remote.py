import select
import socket
import time

from piwall2.animator import Animator
from piwall2.broadcaster.playlist import Playlist
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.displaymode import DisplayMode
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

class Remote:

    __VOLUME_INCREMENT = 1
    __CHANNEL_VIDEOS = None

    # This defines the order in which we will cycle through the animation modes by pressing
    # the KEY_BRIGHTNESSUP / KEY_BRIGHTNESSDOWN buttons
    __ANIMATION_MODES = (
        Animator.ANIMATION_MODE_TILE,
        Animator.ANIMATION_MODE_REPEAT,
        Animator.ANIMATION_MODE_TILE_REPEAT,
        Animator.ANIMATION_MODE_SPIRAL,
    )

    def __init__(self, ticks_per_second):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__ticks_per_second = ticks_per_second
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__display_mode = DisplayMode()
        self.__animator = Animator()
        self.__vol_controller = VolumeController()
        self.__unmute_vol_pct = None
        self.__config_loader = ConfigLoader()
        self.__logger.info("Connecting to LIRC remote socket...")
        self.__socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.__socket.settimeout(1)
        self.__socket.connect('/var/run/lirc/lircd')
        self.__logger.info("Connected!")

        self.__channel = None
        self.__playlist = Playlist()
        self.__currently_playing_item = None
        if Remote.__CHANNEL_VIDEOS is None:
            Remote.__CHANNEL_VIDEOS = list(self.__config_loader.get_raw_config().get('channel_videos', {}).values())

    def check_for_input_and_handle(self, currently_playing_item):
        start_time = time.time()
        self.__currently_playing_item = currently_playing_item
        data = b''
        while True:
            is_ready_to_read, ignore1, ignore2 = select.select([self.__socket], [], [], 0)
            if not is_ready_to_read:
                return

            # The raw data will look something like (this is from holding down the volume button):
            #   b'0000000000000490 00 KEY_VOLUMEUP RM-729A\n'
            #   b'0000000000000490 01 KEY_VOLUMEUP RM-729A\n'
            #   etc...
            #
            # Socket data for multiple button presses can be received in a single recv call. Unfortunately
            # a fixed width protocol is not used, so we have to check for the presence of the expected line
            # ending character (newline).
            raw_data = self.__socket.recv(128)
            data += raw_data
            self.__logger.debug(f"Received remote data ({len(raw_data)}): {raw_data}")
            if raw_data != data:
                self.__logger.debug(f"Using remote data ({len(data)}): {data}")
            data_lines = data.decode('utf-8').split('\n')
            num_lines = len(data_lines)
            full_lines = data_lines[:num_lines - 1]

            # If we had a "partial read" of the remote data, ensure we read the rest of the data in the
            # next iteration.
            if data_lines[num_lines - 1] == '':
                """
                This means we read some data like:

                    0000000000000490 00 KEY_VOLUMEUP RM-729A\n
                    0000000000000490 01 KEY_VOLUMEUP RM-729A\n

                The lines we read ended with a newline. This means the most recent line we read was complete,
                so we can use it.
                """
                data = b''
            else:
                """
                This means we read some data like:

                    0000000000000490 00 KEY_VOLUMEUP RM-729A\n
                    0000000000000490 01 KEY_VOLU

                The lines we read did not end with a newline. This means it was a partial read of the last line,
                so we can't use it.

                Since the last line was a partial read, don't reset the `data` variable.
                We'll read the remainder of the line in the next loop.
                """
                data = data_lines[num_lines - 1].encode()

            # If we read data for multiple button presses in this iteration, only "use" one of those button
            # presses. Here we have logic to determine which one to use. `sequence` is a hex digit that increments
            # when you hold a button down on the remote. Use the 'first' button press (sequence == '00') whenever
            # possible -- for most buttons we don't do anything special when you hold the button down, aside from
            # the volume button. If there is no line with a sequence of '00', then use the last line.
            sequence = key_name = remote = None
            for line in full_lines:
                try:
                    ignore, sequence, key_name, remote = line.split(' ')
                except Exception as e:
                    self.__logger.warning(f'Got exception parsing remote data: {e}')
                if sequence == '00':
                    break

            if not sequence:
                continue

            self.__handle_input(sequence, key_name, remote)

            # don't let reading remote input steal control from the main queue loop for too long
            if (time.time() - start_time) > ((1 / self.__ticks_per_second) / 2):
                return

    def __handle_input(self, sequence, key_name, remote):
        if key_name == 'KEY_MUTE' and sequence == '00':
            current_vol_pct = self.__vol_controller.get_vol_pct()
            if current_vol_pct > 0:
                # mute
                self.__unmute_vol_pct = current_vol_pct
                self.__vol_controller.set_vol_pct(0)
                self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, 0)
            else:
                # unmute
                if not self.__unmute_vol_pct:
                    # handle case where someone manually adjusted the volume to zero.
                    self.__unmute_vol_pct = 50
                self.__vol_controller.set_vol_pct(self.__unmute_vol_pct)
                self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, self.__unmute_vol_pct)
                self.__unmute_vol_pct = None
        elif (
            key_name in (
                'KEY_1', 'KEY_2', 'KEY_3', 'KEY_4', 'KEY_5', 'KEY_6', 'KEY_7', 'KEY_8', 'KEY_9', 'KEY_0'
            ) and sequence == '00'
        ):
            key_num = int(key_name.split('_')[1])
            tv_ids = self.__config_loader.get_tv_ids_list()
            tv_id = tv_ids[key_num % len(tv_ids)]
            self.__logger.info(f'toggle_display_mode {tv_id}')
            self.__display_mode.toggle_display_mode((tv_id,))
        elif key_name == 'KEY_SCREEN' and sequence == '00':
            animation_mode = self.__animator.get_animation_mode()
            if animation_mode == Animator.ANIMATION_MODE_REPEAT:
                self.__animator.set_animation_mode(Animator.ANIMATION_MODE_TILE)
            else:
                self.__animator.set_animation_mode(Animator.ANIMATION_MODE_REPEAT)
        elif key_name == 'KEY_ENTER' and sequence == '00':
            if self.__currently_playing_item:
                self.__playlist.skip(self.__currently_playing_item['playlist_video_id'])
        elif key_name == 'KEY_VOLUMEUP':
            new_volume_pct = self.__vol_controller.increment_vol_pct(inc = self.__VOLUME_INCREMENT)
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, new_volume_pct)
        elif key_name == 'KEY_VOLUMEDOWN':
            new_volume_pct = self.__vol_controller.increment_vol_pct(inc = -self.__VOLUME_INCREMENT)
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, new_volume_pct)
        elif (key_name == 'KEY_CHANNELUP' or key_name == 'KEY_CHANNELDOWN') and sequence == '00':
            if len(Remote.__CHANNEL_VIDEOS) <= 0:
                return

            if self.__channel is None:
                if key_name == 'KEY_CHANNELUP':
                    self.__channel = 0
                else:
                    self.__channel = len(Remote.__CHANNEL_VIDEOS) - 1
            else:
                if key_name == 'KEY_CHANNELUP':
                    self.__channel = (self.__channel + 1) % len(Remote.__CHANNEL_VIDEOS)
                else:
                    self.__channel = (self.__channel - 1) % len(Remote.__CHANNEL_VIDEOS)

            self.__play_video_for_channel()
        elif (key_name == 'KEY_BRIGHTNESSUP' or key_name == 'KEY_BRIGHTNESSDOWN') and sequence == '00':
            old_animation_mode = self.__animator.get_animation_mode()
            try:
                old_animation_index = self.__ANIMATION_MODES.index(old_animation_mode)
            except Exception:
                # unknown animation mode, or could also be ANIMATION_MODE_NONE
                old_animation_index = None

            if old_animation_index is None:
                new_animation_index = 0
            else:
                increment = 1
                if key_name == 'KEY_BRIGHTNESSDOWN':
                    increment = -1
                new_animation_index = (old_animation_index + increment) % len(self.__ANIMATION_MODES)
            self.__animator.set_animation_mode(self.__ANIMATION_MODES[new_animation_index])

    def __play_video_for_channel(self):
        channel_data = Remote.__CHANNEL_VIDEOS[self.__channel]
        video_path = DirectoryUtils().root_dir + '/' + channel_data['video_path']
        thumbnail_path = '/' + channel_data['thumbnail_path']

        """
        Why is this necessary? One might think the `skip` call below would be sufficient.

        We could be reading multiple channel up / down button presses in here before returning
        control back to the queue. If we didn't remove all videos with TYPE_CHANNEL_VIDEO, we'd be marking only the
        currently playing video as skipped. That is, for each additional channel up / down button press we handled
        before returning control back to the queue, we wouldn't remove / skip those.
        """
        self.__playlist.remove_videos_of_type(Playlist.TYPE_CHANNEL_VIDEO)

        if self.__currently_playing_item:
            self.__playlist.skip(self.__currently_playing_item['playlist_video_id'])

        self.__playlist.enqueue(
            video_path, thumbnail_path, channel_data['title'], channel_data['duration'], '',
            Playlist.TYPE_CHANNEL_VIDEO
        )
