from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.logger import Logger
import select
import socket

class Remote:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__logger.info("Connecting to LIRC remote socket...")
        self.__socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.__socket.settimeout(1)
        self.__socket.connect('/var/run/lirc/lircd')
        self.__logger.info("Connected!")

    def check_for_input_and_handle(self):
        is_ready_to_read, ignore1, ignore2 = select.select([self.__socket], [], [], 0)
        if not is_ready_to_read:
            return

        data = self.__socket.recv(128)
        self.__logger.info(f"Received remote data ({len(data)}): {data}")
