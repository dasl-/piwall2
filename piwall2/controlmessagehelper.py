import json
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

# Helper for sending "control messages". Control messages are sent from the broadcaster via
# UDP multicast to control various aspects of the receivers:
# 1) controls volume on the receivers
# 2) signalling for starting video playback
# 3) signalling for skipping a video
# 4) signalling when to apply video effects, like adjusting the video tiling mode
# 5) etc
class ControlMessageHelper:

    # Control message types
    TYPE_VOLUME = 'volume'
    TYPE_INIT_VIDEO = 'init_video'
    TYPE_PLAY_VIDEO = 'play_video'
    TYPE_SKIP_VIDEO = 'skip_video'
    TYPE_DISPLAY_MODE = 'display_mode'
    TYPE_SHOW_LOADING_SCREEN = 'type_show_loading_screen'
    TYPE_END_LOADING_SCREEN = 'type_end_loading_screen'

    CTRL_MSG_TYPE_KEY = 'msg_type'
    CONTENT_KEY = 'content'

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def setup_for_broadcaster(self):
        self.__multicast_helper = MulticastHelper().setup_broadcaster_socket()
        return self

    def setup_for_receiver(self):
        self.__multicast_helper = MulticastHelper().setup_receiver_control_socket()
        return self

    def send_msg(self, ctrl_msg_type, content):
        msg = json.dumps({
            self.CTRL_MSG_TYPE_KEY: ctrl_msg_type,
            self.CONTENT_KEY: content
        })
        self.__multicast_helper.send(msg.encode(), MulticastHelper.CONTROL_PORT)

    """
    Returns a dictionary representing the message. The dictionary has two keys:
    1) self.CTRL_MSG_TYPE_KEY
    2) self.CONTENT_KEY
    """
    def receive_msg(self):
        msg_bytes = self.__multicast_helper.receive(MulticastHelper.CONTROL_PORT)
        try:
            msg = json.loads(msg_bytes)
        except Exception as e:
            self.__logger.error(f"Unable to load control message json: {msg_bytes}.")
            raise e

        return msg
