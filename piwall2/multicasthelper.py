import socket
import struct
import subprocess
from piwall2.logger import Logger

class MulticastHelper:

    ADDRESS = '239.0.1.23'
    VIDEO_PORT = 1234
    CONTROL_PORT = 1235

    # Message will be sent according to the control protocol over the control port.
    # E.g. volume control commands.
    MSG_TYPE_CONTROL = 'msg_type_control'

    # Message will be sent 'raw' over the video stream port
    MSG_TYPE_VIDEO_STREAM = 'msg_type_video_stream'

    __MSG_PREFIX = 'piwall2_multicast_msg_start'
    __MSG_SUFFIX = 'piwall2_multicast_msg_end'

    # 2 MB. This will be doubled to 4MB when we set it via setsockopt.
    __VIDEO_SOCKET_RECEIVE_BUFFER_SIZE_BYTES = 2097152

    # regarding socket.IP_MULTICAST_TTL
    # ---------------------------------
    # for all packets sent, after two hops on the network the packet will not
    # be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
    __TTL = 2

    # Maximum transmission unit
    __MTU = 1472

    def __init__(self, is_broadcaster = False, is_receiver = False):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def setup_broadcaster_socket(self):
        self.__send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.__send_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.__TTL)
        return self

    def setup_receiver_video_socket(self):
        self.__setup_socket_receive_buffer_configuration()

        self.__receive_video_socket = self.__make_receive_socket(self.ADDRESS, self.VIDEO_PORT)

        # set a higher timeout while we wait for the first packet of the video to be sent
        self.__receive_video_socket.settimeout(60)

        # set a higher receive buffer size to avoid UDP packet loss.
        # see: https://github.com/dasl-/piwall2/blob/main/docs/issues_weve_seen_before.adoc#udp-packet-loss
        self.__receive_video_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_RCVBUF, self.__VIDEO_SOCKET_RECEIVE_BUFFER_SIZE_BYTES
        )

        self.__logger.debug("Using receive buffer size of " +
            str(self.__receive_video_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)) +
            " bytes on receiver video socket.")
        return self

    def setup_receiver_control_socket(self):
        self.__setup_socket_receive_buffer_configuration()
        self.__receive_control_socket = self.__make_receive_socket(self.ADDRESS, self.CONTROL_PORT)
        return self

    def send(self, msg, msg_type):
        if msg_type == self.MSG_TYPE_VIDEO_STREAM:
            self.__send_video_stream_msg(msg)
        elif msg_type == self.MSG_TYPE_CONTROL:
            self.__send_control_msg(msg)

    def receive(self, msg_type):
        if msg_type == self.MSG_TYPE_VIDEO_STREAM:
            return self.__receive_video_socket.recv(4096)
        elif msg_type == self.MSG_TYPE_CONTROL:
            return self.__receive_control_socket.recv(4096)

    def get_receive_video_socket(self):
        return self.__receive_video_socket

    def __send_video_stream_msg(self, msg):
        self.__logger.debug(f"Sending video stream message: {msg}")
        self.__send_msg_to(msg, (self.ADDRESS, self.VIDEO_PORT))

    def __send_control_msg(self, msg):
        self.__logger.debug(f"Sending control message: {msg}")
        self.__send_msg_to(msg, (self.ADDRESS, self.CONTROL_PORT))

    def __send_msg_to(self, msg, address_tuple):
        i = 0
        while True:
            chunk = msg[i:(i + self.__MTU)]
            i += self.__MTU
            if chunk:
                j = 0
                max_attempts = 10
                while True:
                    bytes_sent = self.__send_socket.sendto(chunk, address_tuple)
                    if bytes_sent < len(chunk): # not sure if this can ever happen...
                        chunk = chunk[bytes_sent:]
                    else:
                        break

                    j += 1
                    if j > max_attempts:
                        self.__logger.warn(f"Unable to send full message chunk ({chunk}) after {j} attempts.")
                        break
            else:
                break

    def __make_receive_socket(self, address, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((address, port))
        mreq = struct.pack("4sl", socket.inet_aton(address), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        return sock

    # allow a higher receive buffer size to avoid UDP packet loss.
    # see: https://github.com/dasl-/piwall2/blob/main/docs/issues_weve_seen_before.adoc#udp-packet-loss
    def __setup_socket_receive_buffer_configuration(self):
        max_socket_receive_buffer_size = (subprocess
            .check_output(
                "sudo sysctl --values net.core.rmem_max",
                shell = True,
                executable = '/usr/bin/bash',
                stderr = subprocess.STDOUT
            )
        )
        max_socket_receive_buffer_size = int(max_socket_receive_buffer_size.decode().strip())
        if max_socket_receive_buffer_size < self.__VIDEO_SOCKET_RECEIVE_BUFFER_SIZE_BYTES:
            output = (subprocess
                .check_output(
                    f"sudo sysctl --write net.core.rmem_max={self.__VIDEO_SOCKET_RECEIVE_BUFFER_SIZE_BYTES}",
                    shell = True,
                    executable = '/usr/bin/bash',
                    stderr = subprocess.STDOUT
                ).decode().strip()
            )
