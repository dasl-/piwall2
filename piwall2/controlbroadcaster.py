import time
from piwall2.logger import Logger
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.volumecontroller import VolumeController

# Broadcasts various "control" messages to the receivers:
# 1) controls volume on the receivers
class ControlBroadcaster:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__volume_controller = VolumeController()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()

    def run(self):
        while True:
            self.__set_receiver_volume()
            time.sleep(0.5)

    def __set_receiver_volume(self):
        vol_pct = self.__volume_controller.get_vol_pct()
        self.__control_message_helper.send_msg(vol_pct, ControlMessageHelper.VOLUME)
