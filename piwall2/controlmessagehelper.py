import json
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

# Helper for sending "control messages". Sent from the broadcaster to control various aspects of
# the receivers:
# 1) controls volume on the receivers
# 2)
class ControlMessageHelper:

    # Control message types
    VOLUME = 'volume'

    MSG_TYPE_KEY = 'msg_type'
    CONTENT_KEY = 'content'

    __MSG_PREFIX_MAGIC_BYTES = b'control_message_magic_prefix'
    __MSG_SUFFIX_MAGIC_BYTES = b'control_message_magic_suffix'

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def setup_for_broadcaster(self):
        self.__multicast_helper = MulticastHelper().setup_broadcaster_socket()
        return self

    def setup_for_receiver(self):
        self.__multicast_helper = MulticastHelper().setup_receiver_control_socket()
        self.__receive_remainder = b''
        return self

    def send_msg(self, content, control_msg_type):
        if control_msg_type != self.VOLUME:
            raise Exception(f"Invalid control message type: {control_msg_type}.")

        msg = json.dumps({
            self.MSG_TYPE_KEY: control_msg_type,
            self.CONTENT_KEY: content
        })
        msg = self.__MSG_PREFIX_MAGIC_BYTES + msg.encode() + self.__MSG_SUFFIX_MAGIC_BYTES
        self.__multicast_helper.send(msg, MulticastHelper.MSG_TYPE_CONTROL)

    """
    Guard against various edge cases in receiving messages over UDP. I am not sure how likely any
    of the following scenarios are, or if they are even possible.

    1) A message may be sent across more than one packet, i.e. it may take more than one socket.recv()
       call to receive the full message
    2) A single socket.recv() call may contain parts of more than one message. For instance, it may
       contain two full messages, the end of one message and the beginning of the next, etc.
    3) UDP packet loss may cause us to miss parts of some messages.

    We use a "magic" message prefix and suffix to determine the boundaries of a message rather than
    a fixed length encoding scheme because with packet loss, if we used a fixed length encoding
    scheme, if we lose a packet we may never correctly resync the message boundaries. For instance,
    if our fixed message length were 100 bytes and we missed the last 25 bytes of a message due to
    packet loss, we would forever have "off by 25" errors in receiving / decoding messages. With the
    message prefix and suffix scheme, even if we miss a packet, we can still eventually recover when
    the next message starts.

    Returns a dictionary representing the message. The dictionary has two keys:
    1) self.MSG_TYPE_KEY
    2) self.CONTENT_KEY
    """
    def receive_msg(self):
        prefix_start_index = -1
        suffix_start_index = -1
        msg = None
        data = self.__receive_remainder
        while True:
            if prefix_start_index == -1:
                prefix_start_index = data.find(self.__MSG_PREFIX_MAGIC_BYTES)
            if prefix_start_index != -1:
                suffix_start_index = data.find(self.__MSG_SUFFIX_MAGIC_BYTES, prefix_start_index)
            if suffix_start_index != -1:
                msg_start_index = prefix_start_index + len(self.__MSG_PREFIX_MAGIC_BYTES)
                msg_end_index = suffix_start_index
                msg = data[msg_start_index:msg_end_index]
                self.__receive_remainder = data[msg_end_index:]
                break
            data += self.__multicast_helper.receive(MulticastHelper.MSG_TYPE_CONTROL)

        try:
            msg = json.loads(msg)
        except Exception as e:
            self.__logger.error(f"Unable to load control message json: {msg}.")
            raise e

        return msg
