import subprocess
import time

from piwall2.broadcaster import Broadcaster
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

class Receiver:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def receive(self, cmd):
        multicast_helper = MulticastHelper()
        socket = multicast_helper.get_receive_video_socket()
        has_lowered_timeout = False
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdin = subprocess.PIPE
        )
        last_video_bytes = b''
        while True:
            video_bytes = multicast_helper.receive_video()

            if not has_lowered_timeout:
                # Subsequent bytes after the first packet should be received very quickly
                socket.settimeout(1)
                has_lowered_timeout = True

            last_video_bytes += video_bytes[-len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if len(last_video_bytes) > len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):
                last_video_bytes = last_video_bytes[-len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if last_video_bytes == Broadcaster.END_OF_VIDEO_MAGIC_BYTES:
                # os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.stdin.close()
                break

            proc.stdin.write(video_bytes)
            proc.stdin.flush()

        while proc.poll() is None:
            print('.')
            time.sleep(0.1)

        print("done!")
