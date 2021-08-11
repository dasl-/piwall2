import os
import shlex
import signal
import socket
import subprocess
import traceback

from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.omxplayercontroller import OmxplayerController

class Receiver:

    VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES = 1024 * 1024 * 400 # 400 MB

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__omxplayer_controller = OmxplayerController()
        self.__hostname = socket.gethostname() + ".local"
        self.__local_ip_address = self.__get_local_ip()
        self.__is_video_playback_in_progress = False
        self.__receive_and_play_video_proc = None
        # Store the PGID separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__receive_and_play_video_proc_pgid = None

    def run(self):
        self.__logger.info("Started receiver!")
        while True:
            try:
                self.__run_internal()
            except Exception:
                self.__logger.error('Caught exception: {}'.format(traceback.format_exc()))

    def __run_internal(self):
        ctrl_msg = None
        ctrl_msg = self.__control_message_helper.receive_msg() # This blocks until a message is received!
        self.__logger.debug(f"Received control message {ctrl_msg}. " +
            f"self.__is_video_playback_in_progress: {self.__is_video_playback_in_progress}.")

        if self.__is_video_playback_in_progress:
            if self.__receive_and_play_video_proc and self.__receive_and_play_video_proc.poll() is not None:
                self.__is_video_playback_in_progress = False

        msg_type = ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY]
        if self.__is_video_playback_in_progress:
            if msg_type == ControlMessageHelper.TYPE_VOLUME:
                self.__omxplayer_controller.set_vol_pct(ctrl_msg[ControlMessageHelper.CONTENT_KEY])
            elif msg_type == ControlMessageHelper.TYPE_SKIP_VIDEO:
                self.__stop_video_playback_if_playing()
        if msg_type == ControlMessageHelper.TYPE_PLAY_VIDEO:
            self.__stop_video_playback_if_playing()
            self.__receive_and_play_video_proc = self.__receive_and_play_video(ctrl_msg)
            self.__receive_and_play_video_proc_pgid = os.getpgid(self.__receive_and_play_video_proc.pid)

    def __receive_and_play_video(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        orig_uuid = Logger.get_uuid()
        if 'log_uuid' in ctrl_msg_content:
            Logger.set_uuid(ctrl_msg_content['log_uuid'])

        params_list = None
        try:
            if self.__hostname in ctrl_msg_content:
                params_list = ctrl_msg_content[self.__hostname]
            elif self.__local_ip_address in ctrl_msg_content:
                params_list = ctrl_msg_content[self.__local_ip_address]
            else:
                raise Exception(f"Unable to find hostname ({self.__hostname}) or local ip " +
                    f"({self.__local_ip_address}) in control message content: {ctrl_msg_content}")

            cmd = self.__build_receive_and_play_video_command(params_list)
            self.__logger.info(f"Running receive_and_play_video command: {cmd}")
            self.__is_video_playback_in_progress = True
            proc = subprocess.Popen(
                cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
            )
            return proc
        finally:
            Logger.set_uuid(orig_uuid)

    def __stop_video_playback_if_playing(self):
        if not self.__is_video_playback_in_progress:
            return
        if self.__receive_and_play_video_proc_pgid:
            self.__logger.info("Killing receive_and_play_video proc...")
            try:
                os.killpg(self.__receive_and_play_video_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        self.__is_video_playback_in_progress = False

    """
    `params_list` will be an array with one or two elements. The number of elements corresponds to the number of
    TVs that this receiver is driving.
    """
    def __build_receive_and_play_video_command(self, params_list):
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
        mbuffer_cmd = f'mbuffer -q -l /tmp/mbuffer.out -m {self.VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES}b'
        omx_cmd_template = 'omxplayer --crop {0} {1}'

        params = params_list[0]
        params2 = None
        omx_cmd = omx_cmd_template.format(shlex.quote(params['crop']), params['misc'])
        cmd = 'set -o pipefail && '
        if params_list_len == 2:
            params2 = params[1]
            omx_cmd2 = omx_cmd_template.format(shlex.quote(params2['crop']), params2['misc'])
            cmd += f'{mbuffer_cmd} | tee >({omx_cmd}) >({omx_cmd2}) >/dev/null'
        else:
            cmd += f'{mbuffer_cmd} | {omx_cmd}'

        receiver_cmd_template = (DirectoryUtils().root_dir + '/receive_and_play_video --command "{0}" ' +
            '--log-uuid ' + shlex.quote(Logger.get_uuid()))
        return receiver_cmd_template.format(cmd)

    def __get_local_ip(self):
        return (subprocess
            .check_output(
                'set -o pipefail && sudo ifconfig | grep -Eo \'inet (addr:)?([0-9]*\.){3}[0-9]*\' | ' +
                'grep -Eo \'([0-9]*\.){3}[0-9]*\' | grep -v \'127.0.0.1\'',
                stderr = subprocess.STDOUT, shell = True, executable = '/bin/bash'
            )
            .decode("utf-8")
            .strip())
