import shlex
import subprocess
import time

import piwall2.broadcaster.videobroadcaster
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper

class VideoReceiver:

    MBUFFER_SIZE_BYTES = 1024 * 1024 * 400 # 400 MB

    # emit measurement stats once every 10s
    __MEASUREMENT_WINDOW_SIZE_S = 10

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def receive_and_play_video(self, params_list):
        cmd = self.__build_command(params_list)

        multicast_helper = MulticastHelper().setup_receiver_video_socket()
        socket = multicast_helper.get_receive_video_socket()
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdin = subprocess.PIPE
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

            if video_bytes == piwall2.broadcaster.videobroadcaster.VideoBroadcaster.END_OF_VIDEO_MAGIC_BYTES:
                self.__logger.info(f"Received end of video magic bytes. Received {total_bytes_count} bytes. " +
                    "Waiting for video to finish playing...")
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
            time.sleep(0.1)

        self.__logger.info("Video is done playing!")

    """
    `params_list` will be an array with one or two elements. The number of elements corresponds to the number of
    TVs that this receiver is driving.
    """
    def __build_command(self, params_list):
        params_list_len = len(params_list)
        if params_list_len != 1 and params_list_len != 2:
            raise Exception(f"Unexpected params list length (should be 1 or 2): {params_list_len}")

        """
        We use mbuffer in the receiver command. The mbuffer is here to solve two problems:

        1) Sometimes the python receiver process would get blocked writing directly to omxplayer. When this happens,
        the receiver's writes would occur rather slowly. While the receiver is blocked on writing, it cannot read
        incoming data from the UDP socket. The kernel's UDP buffers would then fill up, causing UDP packets to be
        dropped.

        Unlike python, mbuffer is multithreaded, meaning it can read and write simultaneously in two separate
        threads. Thus, while mbuffer is writing to omxplayer, it can still read the incoming data from python at
        full speed. Slow writes will not block reads.

        2) I am not sure how exactly omxplayer's various buffers work. There are many options:

            % omxplayer --help
            ...
             --audio_fifo  n         Size of audio output fifo in seconds
             --video_fifo  n         Size of video output fifo in MB
             --audio_queue n         Size of audio input queue in MB
             --video_queue n         Size of video input queue in MB
            ...

        More info: https://github.com/popcornmix/omxplayer/issues/256#issuecomment-57907940

        I am not sure which I would need to adjust to ensure enough buffering is available. By using mbuffer,
        we effectively have a single buffer that accounts for any possible source of delays, whether it's from audio,
        video, and no matter where in the pipeline the delay is coming from. Using mbuffer seems simpler, and it is
        easier to monitor. By checking its logs, we can see how close the mbuffer gets to becoming full.
        """
        mbuffer_cmd = f'mbuffer -q -l /tmp/mbuffer.out -m {self.MBUFFER_SIZE_BYTES}b'
        omx_cmd_template = 'omxplayer --crop {0} {1}'

        params = params_list[0]
        params2 = None
        omx_cmd = omx_cmd_template.format(shlex.quote(params['crop']), params['misc'])
        if params_list_len == 2:
            params2 = params[1]
            omx_cmd2 = omx_cmd_template.format(shlex.quote(params2['crop']), params2['misc'])
            cmd = f"{mbuffer_cmd} | tee >({omx_cmd}) >({omx_cmd2}) >/dev/null"
        else:
            cmd = f'{mbuffer_cmd} | {omx_cmd}'
        return cmd
