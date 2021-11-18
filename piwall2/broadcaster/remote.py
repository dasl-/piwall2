import select
import socket
import time

from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.displaymode import DisplayMode
from piwall2.animator import Animator
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

class Remote:

    __VOLUME_INCREMENT = 1

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
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

    def check_for_input_and_handle(self):
        start_time = time.time()
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
            data += self.__socket.recv(128)
            self.__logger.debug(f"Received remote data ({len(data)}): {data}")
            data_lines = data.decode('utf-8').split('\n')
            num_lines = len(data_lines)
            line_to_use = None
            if data_lines[num_lines - 1] == '':
                """
                This means we read some data like:

                    0000000000000490 00 KEY_VOLUMEUP RM-729A\n
                    0000000000000490 01 KEY_VOLUMEUP RM-729A\n

                The lines we read ended with a newline. This means the most recent line we read was complete,
                so we can use it.
                """
                line_to_use = data_lines[num_lines - 2]
                data = b''
            else:
                """
                This means we read some data like:

                    0000000000000490 00 KEY_VOLUMEUP RM-729A\n
                    0000000000000490 01 KEY_VOLU

                The lines we read did not end with a newline. This means it was a partial read of the last line,
                so we can't use it.
                """
                if num_lines >= 2:
                    line_to_use = data_lines[num_lines - 2]

                # since the last line was a partial read, don't reset the `data` variable.
                # We'll read the remainder of the line in the next loop.

            if not line_to_use:
                continue

            try:
                ignore, sequence, key_name, remote = line_to_use.split(' ')
            except Exception as e:
                self.__logger.warning(f'Got exception parsing remote data: {e}')

            self.__handle_input(sequence, key_name, remote)

            # don't let reading remote input steal contorl from the main queue loop for too long
            if (time.time() - start_time) > 0.5:
                return

    def __handle_input(self, sequence, key_name, remote):
        if key_name == 'KEY_MUTE' and sequence == '00':
            if self.__unmute_vol_pct is None:
                # mute
                self.__unmute_vol_pct = self.__vol_controller.get_vol_pct()
                self.__vol_controller.set_vol_pct(0)
                self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, 0)
            else:
                # unmute
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
        elif key_name == 'KEY_VOLUMEUP':
            new_volume_pct = self.__vol_controller.increment_vol_pct(inc = self.__VOLUME_INCREMENT)
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, new_volume_pct)
        elif key_name == 'KEY_VOLUMEDOWN':
            new_volume_pct = self.__vol_controller.increment_vol_pct(inc = -self.__VOLUME_INCREMENT)
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, new_volume_pct)
        elif key_name == 'KEY_SCREEN':
            animation_mode = self.__animator.get_animation_mode()
            self.__logger.info(f'Got old animation mode: {animation_mode}')
            if animation_mode == Animator.ANIMATION_MODE_REPEAT:
                self.__animator.set_animation_mode(Animator.ANIMATION_MODE_TILE)
            else:
                self.__animator.set_animation_mode(Animator.ANIMATION_MODE_REPEAT)
