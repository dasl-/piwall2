import subprocess
import time

from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.broadcaster.videobroadcaster import VideoBroadcaster

class VideoReceiver:

    # emit measurement stats once every 10s
    __MEASUREMENT_WINDOW_SIZE_S = 10

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def receive_and_play_video(self, cmd):
        multicast_helper = MulticastHelper().setup_receiver_video_socket()
        socket = multicast_helper.get_receive_video_socket()

        # Use start_new_session = False here so that every process here will get killed when
        # the parent receive_and_play_video session is killed
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = False, stdin = subprocess.PIPE
        )
        self.__logger.info(f'Started receive_and_play_video command: {cmd}')

        measurement_window_start = time.time()
        measurement_window_bytes_count = 0
        total_bytes_count = 0

        while True:
            video_bytes = multicast_helper.receive(MulticastHelper.VIDEO_PORT)
            if total_bytes_count == 0:
                # Subsequent bytes after the first packet should be received more quickly
                socket.settimeout(10)
                self.__logger.info("Received first bytes of video...")

            len_video_bytes = len(video_bytes)
            measurement_window_bytes_count += len_video_bytes
            total_bytes_count += len_video_bytes

            if video_bytes == VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES:
                self.__logger.info(f"Received end of video magic bytes. Received {total_bytes_count} bytes. " +
                    "Waiting for video to finish playing...")
                proc.stdin.close()
                break

            proc.stdin.write(video_bytes)

            measurement_window_elapsed_time_s = time.time() - measurement_window_start
            if measurement_window_elapsed_time_s > self.__MEASUREMENT_WINDOW_SIZE_S:
                measurement_window_KB_per_s = measurement_window_bytes_count / measurement_window_elapsed_time_s / 1024
                self.__logger.info(f"Reading video at {round(measurement_window_KB_per_s, 2)} KB/s")
                measurement_window_start = time.time()
                measurement_window_bytes_count = 0

        while proc.poll() is None:
            time.sleep(0.1)

        self.__logger.info("Video is done playing!")
