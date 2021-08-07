import subprocess
import time

from piwall2.broadcaster.videobroadcaster import VideoBroadcaster
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

class VideoReceiver:

    # emit measurement stats once every 10s
    __MEASUREMENT_WINDOW_SIZE_S = 10

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def receive(self, cmd, log_uuid = None):
        if log_uuid:
            Logger.set_uuid(log_uuid)

        multicast_helper = MulticastHelper().setup_receiver_video_socket()
        socket = multicast_helper.get_receive_video_socket()
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdin = subprocess.PIPE
        )
        last_video_bytes = b''

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

            # todo: make this better. we might not have written the last few bytes if the magic bytes came as
            # part of the same receive call as some actual video bytes. (not sure if that's possible...)
            last_video_bytes += video_bytes[-len(VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if len(last_video_bytes) > len(VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES):
                last_video_bytes = last_video_bytes[-len(VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES):]
            if last_video_bytes == VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES:
                self.__logger.info(f"Received end of video magic bytes. Received {total_bytes_count} bytes...")
                # os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
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
            print('.')
            time.sleep(0.1)

        print("done!")
