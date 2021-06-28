import socket
import struct
import subprocess
import time

from piwall2.broadcaster import Broadcaster
from piwall2.logger import Logger

class Receiver:

    __SOCKET_TIMEOUT_S = 10
    __logger = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def receive(self, cmd):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((Broadcaster.MULTICAST_ADDRESS, Broadcaster.MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(Broadcaster.MULTICAST_ADDRESS), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        has_set_timeout = False

        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdin = subprocess.PIPE
        )
        while True:
            ret = sock.recv(4096)

            self.__logger.debug(f"Received {len(ret)} bytes")
            if not has_set_timeout:
                sock.settimeout(self.__SOCKET_TIMEOUT_S)

            # todo: guard against magic bytes being sent in more than one packet
            if ret == Broadcaster.END_OF_VIDEO_MAGIC_BYTES:
                # os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.stdin.close()
                break

            proc.stdin.write(ret)
            proc.stdin.flush()

        while proc.poll() is None:
            print('.')
            time.sleep(0.1)

        print("done!")
