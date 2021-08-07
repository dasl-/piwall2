from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.logger import Logger
from piwall2.omxplayercontroller import OmxplayerController

class Receiver:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__omxplayer_controller = OmxplayerController()

    def run(self):
        while True:
            control_msg = None
            try:
                control_msg = self.__control_message_helper.receive_msg()
                self.__logger.debug(f"Received control message {control_msg}.")
            except Exception:
                continue

            if control_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY] == ControlMessageHelper.TYPE_VOLUME:
                self.__omxplayer_controller.set_vol_pct(control_msg[ControlMessageHelper.CONTENT_KEY])
            else:
                raise Exception(f"Unsupported control message type: {control_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY]}.")
