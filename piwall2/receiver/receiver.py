import os
import pathlib
import shlex
import signal
import socket
import subprocess
import time
import traceback

from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.receiver.omxplayercontroller import OmxplayerController
from piwall2.volumecontroller import VolumeController

class Receiver:

    VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES = 1024 * 1024 * 400 # 400 MB

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Started receiver!")
        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__hostname = socket.gethostname() + ".local"
        self.__local_ip_address = self.__get_local_ip()
        self.__orig_log_uuid = Logger.get_uuid()
        self.__is_video_playback_in_progress = False
        self.__receive_and_play_video_proc = None
        # Store the PGID separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__receive_and_play_video_proc_pgid = None

        # house keeping
        (VolumeController()).set_vol_pct(100)
        self.__play_warmup_video()

        # This must come after the warmup video. When run as a systemd service, omxplayer wants to
        # start new dbus sessions / processes every time the service is restarted. This means it will
        # create new dbus files in /tmp when the first video is played after the service is restarted
        # But the old files will still be in /tmp. So if we initialize the OmxplayerController before
        # the new dbus files are created by playing the first video since restarting the service, we
        # will be reading stale dbus info from the files in /tmp.
        self.__omxplayer_controller = OmxplayerController()

    def run(self):
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
                self.__logger.info("Ending video playback because receive_and_play_video_proc is no longer running...")
                self.__stop_video_playback_if_playing()

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
        self.__orig_log_uuid = Logger.get_uuid()
        if 'log_uuid' in ctrl_msg_content:
            Logger.set_uuid(ctrl_msg_content['log_uuid'])

        params_list = None
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

    def __stop_video_playback_if_playing(self):
        if not self.__is_video_playback_in_progress:
            return
        if self.__receive_and_play_video_proc_pgid:
            self.__logger.info("Killing receive_and_play_video proc (if it's still running)...")
            try:
                os.killpg(self.__receive_and_play_video_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        Logger.set_uuid(self.__orig_log_uuid)
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
        mbuffer_cmd = f'HOME=/home/pi mbuffer -q -l /tmp/mbuffer.out -m {self.VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES}b'
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

        receiver_cmd_template = (DirectoryUtils().root_dir + '/bin/receive_and_play_video --command "{0}" ' +
            '--log-uuid ' + shlex.quote(Logger.get_uuid()))
        return receiver_cmd_template.format(cmd)

    # The first video that is played after a system restart appears to have a lag in starting,
    # which can affect video synchronization across the receivers. Ensure we have played at
    # least one video since system startup. This is a short, one-second video.
    #
    # Perhaps one thing this warmup video does is start the various dbus processes for the first
    # time, which can involve some sleeps:
    # https://github.com/popcornmix/omxplayer/blob/1f1d0ccd65d3a1caa86dc79d2863a8f067c8e3f8/omxplayer#L50-L59
    #
    # When the receiver is run as as a systemd service, the first time a video is played after the service
    # is restarted, it seems that omxplayer must initialize dbus. Thus, it is important to run the warmup
    # video whenever the service is restarted.
    #
    # This is as opposed to when running the service as a regular user / process -- the dbus stuff stays
    # initialized until the pi is rebooted.
    def __play_warmup_video(self):
        self.__logger.info("Playing receiver warmup video...")
        warmup_cmd = f'omxplayer --vol 0 {DirectoryUtils().root_dir}/utils/short_black_screen.ts'
        proc = subprocess.Popen(
            warmup_cmd, shell = True, executable = '/usr/bin/bash'
        )
        while proc.poll() is None:
            time.sleep(0.1)
        if proc.returncode != 0:
            raise Exception(f"The process for cmd: [{warmup_cmd}] exited non-zero: " +
                f"{proc.returncode}.")

    def __get_local_ip(self):
        return (subprocess
            .check_output(
                'set -o pipefail && sudo ifconfig | grep -Eo \'inet (addr:)?([0-9]*\.){3}[0-9]*\' | ' +
                'grep -Eo \'([0-9]*\.){3}[0-9]*\' | grep -v \'127.0.0.1\'',
                stderr = subprocess.STDOUT, shell = True, executable = '/bin/bash'
            )
            .decode("utf-8")
            .strip())
