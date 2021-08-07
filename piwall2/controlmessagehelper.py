import json
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

# Helper for sending "control messages". Control messages are sent from the broadcaster via
# UDP multicast to control various aspects of the receivers:
# 1) controls volume on the receivers
# 2)
class ControlMessageHelper:

    # Control message types
    TYPE_VOLUME = 'volume'
    TYPE_PLAY_VIDEO = 'play_video'

    CTRL_MSG_TYPE_KEY = 'msg_type'
    CONTENT_KEY = 'content'

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def setup_for_broadcaster(self):
        self.__multicast_helper = MulticastHelper().setup_broadcaster_socket()
        return self

    def setup_for_receiver(self):
        self.__multicast_helper = MulticastHelper().setup_receiver_control_sockets()
        return self

    def send_msg(self, ctrl_msg_type, content):
        if ctrl_msg_type not in [self.TYPE_VOLUME, self.TYPE_PLAY_VIDEO]:
            raise Exception(f"Invalid control message type: {ctrl_msg_type}.")

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
