from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

class Receiver:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper()
        self.__volume_controller = VolumeController()

    def run(self, cmd):
        while True:
            control_msg = self.__control_message_helper.receive_msg()
            if control_msg is None:
                continue
            if control_msg[ControlMessageHelper.MSG_TYPE_KEY] == ControlMessageHelper.VOLUME:
                self.__volume_controller.set_vol_pct(control_msg[ControlMessageHelper.CONTENT_KEY])
            else:
                raise Exception(f"Unsupported control message type: {control_msg[ControlMessageHelper.MSG_TYPE_KEY]}.")
