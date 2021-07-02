import subprocess
import time

from piwall2.broadcaster import Broadcaster
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

class Receiver:

    # emit measurement stats once every 10s
    __MEASUREMENT_WINDOW_SIZE_S = 10

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

        measurement_window_start = time.time()
        measurement_window_bytes_count = 0

        while True:
            video_bytes = multicast_helper.receive(MulticastHelper.MSG_TYPE_VIDEO_STREAM)
            measurement_window_bytes_count += len(video_bytes)

            if not has_lowered_timeout:
                # Subsequent bytes after the first packet should be received very quickly
                socket.settimeout(1)
                has_lowered_timeout = True

            last_video_bytes += video_bytes[-len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if len(last_video_bytes) > len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):
                last_video_bytes = last_video_bytes[-len(Broadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if last_video_bytes == Broadcaster.END_OF_VIDEO_MAGIC_BYTES:
                self.__logger.info("Received end of video magic bytes...")
                # os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.stdin.close()
                break

            proc.stdin.write(video_bytes)
            proc.stdin.flush()

            measurement_window_elapsed_time_s = time.time() - measurement_window_start
            if measurement_window_elapsed_time_s > self.__MEASUREMENT_WINDOW_SIZE_S:
                measurement_window_KB_per_s = measurement_window_bytes_count / measurement_window_elapsed_time_s / 1024
                self.__logger.info(f"Reading video at {round(measurement_window_KB_per_s, 2)} KB/s")
                measurement_window_start = time.time()
                measurement_window_bytes_count = 0

        while proc.poll() is None:
            print('.')
            time.sleep(0.1)

        print("done!")
