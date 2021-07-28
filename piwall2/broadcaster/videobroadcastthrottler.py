import sys
import time

from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.broadcaster.videobroadcaster import VideoBroadcaster

class VideoBroadcastThrottler:

    # Stop burst (slow down) after sending this much video data
    __BURST_AMOUNT_BYTES = VideoBroadcaster.RECEIVER_MBUFFER_SIZE / 2

    def __init__(self, video_size_bytes, video_duration_s, log_uuid = None):
        log_level = Logger.get_level()
        if log_level is None or log_level <= Logger.DEBUG:
            # Prevent MulticastHelper.__send_video_stream_msg debug logs from being too spammy
            Logger.set_level(Logger.INFO)

        if log_uuid:
            Logger.set_uuid(log_uuid)

        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__target_byte_rate = video_size_bytes / video_duration_s
        self.__multicast_helper = MulticastHelper().setup_broadcaster_socket()
        self.__logger.info(f"Starting {self.__class__.__name__} with target_byte_rate: {self.__target_byte_rate} bytes/s.")

    def throttle_broadcast(self):
        bytes_sent = 0
        bytes_sent_since_burst = 0
        time_since_burst = 0
        burst_end_time = 0

        self.__logger.info(f"Starting burst of at most {self.__BURST_AMOUNT_BYTES / 1024 / 1024} MB...")
        while True:
            data = sys.stdin.buffer.read(4096)
            if not data:
                break

            if bytes_sent > self.__BURST_AMOUNT_BYTES: # throttle
                if burst_end_time == 0:
                    self.__logger.info("Burst finished. Starting throttled send...")
                    burst_end_time = time.time()
                time_since_burst = time.time() - burst_end_time
                byte_rate = bytes_sent_since_burst / time_since_burst
                while byte_rate > self.__target_byte_rate:
                    time.sleep(0.5)
                    time_since_burst = time.time() - burst_end_time
                    byte_rate = bytes_sent_since_burst / time_since_burst
                this_bytes_sent = self.__send_data(data)
                bytes_sent += this_bytes_sent
                bytes_sent_since_burst += this_bytes_sent
            else: # burst
                bytes_sent += self.__send_data(data)

        self.__logger.info("throttle_broadcast finished")

    def __send_data(self, data):
        i = 0
        while True:
            chunk = data[i:(i + 1472)]
            i += 1472
            if chunk:
                self.__multicast_helper.send(chunk, MulticastHelper.MSG_TYPE_VIDEO_STREAM)
            else:
                return len(data)
