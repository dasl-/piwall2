import socket
import struct
import subprocess
from piwall2.logger import Logger

class MulticastHelper:

    ADDRESS = '239.0.1.23'

    # Messages will be sent 'raw' over the video stream port
    VIDEO_PORT = 1234

    # Message will be sent according to the control protocol over the control port.
    # E.g. volume control commands.
    CONTROL_PORT = 1236

    # 2 MB. This will be doubled to 4MB when we set it via setsockopt.
    __VIDEO_SOCKET_RECEIVE_BUFFER_SIZE_BYTES = 2097152

    # regarding socket.IP_MULTICAST_TTL
    # ---------------------------------
    # for all packets sent, after two hops on the network the packet will not
    # be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
    __TTL = 1

    # max UDP packet size is 65535 bytes
    # IP Header is 20 bytes, UDP header is 8 bytes
    # 65535 - 20 - 8 = 65507
    # Sending a message of any larger will result in: `OSError: [Errno 90] Message too long`
    __MAX_MSG_SIZE = 65507

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def setup_broadcaster_socket(self):
        self.__send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.__send_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.__TTL)
        self.__send_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
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

    def send(self, msg, port):
        if port == self.VIDEO_PORT:
            self.__logger.debug(f"Sending video stream message: {msg}")
        elif port == self.CONTROL_PORT:
            self.__logger.debug(f"Sending control message: {msg}")

        address_tuple = (self.ADDRESS, port)
        msg_remainder = msg
        bytes_sent = 0
        while msg_remainder: # Don't send more than __MAX_MSG_SIZE at a time
            msg_part = msg_remainder[:self.__MAX_MSG_SIZE]
            msg_remainder = msg_remainder[self.__MAX_MSG_SIZE:]
            bytes_sent += self.__send_socket.sendto(msg_part, address_tuple)
        if bytes_sent == 0:
            self.__logger.warn(f"Unable to send message. Address: {address_tuple}. Message: {msg}")
        elif bytes_sent != len(msg):
            # Not sure if this can ever happen... This post suggests you cannot have partial sends in UDP:
            # https://www.gamedev.net/forums/topic/504256-partial-sendto/4289205/
            self.__logger.warn(f"Partial send of message. Sent {bytes_sent} of {len(msg)} bytes. " +
                f"Address: {address_tuple}. Message: {msg}")
        return bytes_sent

    """
    UDP datagram messages cannot be split. One send corresponds to one receive. Having multiple senders
    to the same socket in multiple processes will not clobber each other. Message boundaries will be
    preserved, even when sending a message that is larger than the MTU and making use of the OS's
    UDP fragmentation. The message will be reconstructed fully in the UDP stack layer.
    See: https://stackoverflow.com/questions/8748711/udp-recv-recvfrom-multiple-senders

    Use a receive buffer of the maximum packet size. Since we may be receiving messages of unknown
    lengths, this guarantees that we will not accidentally truncate any messages by using a receiver
    buffer that was too small.
    See `MSG_TRUNC` flag: https://man7.org/linux/man-pages/man2/recv.2.html
    See: https://stackoverflow.com/a/2862176/627663
    """
    def receive(self, port):
        if port == self.VIDEO_PORT:
            return self.__receive_video_socket.recv(self.__MAX_MSG_SIZE)
        elif port == self.CONTROL_PORT:
            return self.__receive_control_socket.recv(self.__MAX_MSG_SIZE)
        else:
            raise Exception(f'Unexpected port: {port}.')

    def get_receive_video_socket(self):
        return self.__receive_video_socket

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
