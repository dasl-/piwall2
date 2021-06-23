import socket
import struct
import sys
import shlex
import subprocess
import os
import signal
import time

from piwall2.broadcaster import Broadcaster

class Receiver:

    __SOCKET_TIMEOUT_S = 10

    def __init__(self):
        pass

    def receive(self, crop_string):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((Broadcaster.MULTICAST_ADDRESS, Broadcaster.MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(Broadcaster.MULTICAST_ADDRESS), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        has_set_timeout = False

        cmd = f"omxplayer --crop {shlex.quote(crop_string)} -o local --no-keys --threshold 3 pipe:0"
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdin = subprocess.PIPE
        )
        while True:
            ret = sock.recv(4096)
            print(str(len(ret)), file=sys.stderr, flush = True)
            print(ret, file=sys.stderr, flush = True)
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
