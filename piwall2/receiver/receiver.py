import os
import shlex
import signal
import socket
import subprocess
import time
import traceback

from piwall2.configloader import ConfigLoader
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
        self.__hostname = socket.gethostname() + ".local"
        self.__local_ip_address = self.__get_local_ip()

        self.__config_loader = ConfigLoader()
        receivers_config = self.__config_loader.get_receivers_config()
        if self.__hostname in receivers_config:
            self.__receiver_config_stanza = receivers_config[self.__hostname]
        elif self.__local_ip_address in receivers_config:
            self.__receiver_config_stanza = receivers_config[self.__local_ip_address]
        else:
            raise Exception("Unable to find config stanza for this receiver's " +
                f"hostname ({self.__hostname}) or local ip address ({self.__local_ip_address}) " +
                f"in receivers config file ({ConfigLoader.RECEIVERS_CONFIG_PATH}).")

        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__orig_log_uuid = Logger.get_uuid()
        self.__is_video_playback_in_progress = False
        self.__receive_and_play_video_proc = None
        # Store the PGID separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__receive_and_play_video_proc_pgid = None
        self.__crop = None

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
            elif msg_type == ControlMessageHelper.TYPE_TILE:
                if ctrl_msg[ControlMessageHelper.CONTENT_KEY]:
                    self.__omxplayer_controller.set_crop("0 0 1920 1080")
                else:
                    crop = self.__crop.replace(',', ' ')
                    self.__logger.info(f"Setting crop to {crop}")
                    self.__omxplayer_controller.set_crop(crop)
            elif msg_type == ControlMessageHelper.TYPE_SKIP_VIDEO:
                self.__stop_video_playback_if_playing()
        if msg_type == ControlMessageHelper.TYPE_PLAY_VIDEO:
            self.__stop_video_playback_if_playing()
            self.__receive_and_play_video_proc = self.__receive_and_play_video(ctrl_msg)
            self.__receive_and_play_video_proc_pgid = os.getpgid(self.__receive_and_play_video_proc.pid)

    def __receive_and_play_video(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        self.__orig_log_uuid = Logger.get_uuid()
        Logger.set_uuid(ctrl_msg_content['log_uuid'])
        cmd = self.__build_receive_and_play_video_command(
            ctrl_msg_content['log_uuid'], ctrl_msg_content['video_width'],
            ctrl_msg_content['video_height'], ctrl_msg_content['volume']
        )
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

    def __build_receive_and_play_video_command(self, log_uuid, video_width, video_height, volume):
        adev, adev2 = self.__get_video_command_adev_args()
        display, display2 = self.__get_video_command_display_args()
        crop, crop2 = self.__get_video_command_crop_args(video_width, video_height)

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

        # See: https://github.com/dasl-/piwall2/blob/main/docs/configuring_omxplayer.adoc
        omx_cmd_template = ('omxplayer --crop {0} --adev {1} --display {2} --vol {3} ' +
            '--no-keys --timeout 20 --threshold 0.2 --video_fifo 35 --genlog pipe:0')

        omx_cmd = omx_cmd_template.format(
            shlex.quote(crop), shlex.quote(adev), shlex.quote(display), shlex.quote(str(volume))
        )
        self.__crop = crop
        cmd = 'set -o pipefail && '
        if self.__receiver_config_stanza['is_dual_video_output']:
            omx_cmd2 = omx_cmd_template.format(
                shlex.quote(crop2), shlex.quote(adev2), shlex.quote(display2), shlex.quote(str(volume))
            )
            cmd += f'{mbuffer_cmd} | tee >({omx_cmd}) >({omx_cmd2}) >/dev/null'
        else:
            cmd += f'{mbuffer_cmd} | {omx_cmd}'

        receiver_cmd = (f'{DirectoryUtils().root_dir}/bin/receive_and_play_video --command {shlex.quote(cmd)} ' +
            f'--log-uuid {shlex.quote(log_uuid)}')
        return receiver_cmd

    def __get_video_command_adev_args(self):
        receiver_config = self.__receiver_config_stanza
        adev = None
        if receiver_config['audio'] == 'hdmi' or receiver_config['audio'] == 'hdmi0':
            adev = 'hdmi'
        elif receiver_config['audio'] == 'headphone':
            adev = 'local'
        elif receiver_config['audio'] == 'hdmi_alsa' or receiver_config['audio'] == 'hdmi0_alsa':
            adev = 'alsa:default:CARD=b1'
        else:
            raise Exception(f"Unexpected audio config value: {receiver_config['audio']}")

        adev2 = None
        if receiver_config['is_dual_video_output']:
            if receiver_config['audio2'] == 'hdmi1':
                adev2 = 'hdmi1'
            elif receiver_config['audio2'] == 'headphone':
                adev2 = 'local'
            elif receiver_config['audio'] == 'hdmi1_alsa':
                adev2 = 'alsa:default:CARD=b2'
            else:
                raise Exception(f"Unexpected audio2 config value: {receiver_config['audio2']}")

        return (adev, adev2)

    def __get_video_command_display_args(self):
        receiver_config = self.__receiver_config_stanza
        display = None
        if receiver_config['video'] == 'hdmi' or receiver_config['video'] == 'hdmi0':
            display = '2'
        elif receiver_config['video'] == 'composite':
            display = '3'
        else:
            raise Exception(f"Unexpected video config value: {receiver_config['video']}")

        display2 = None
        if receiver_config['is_dual_video_output']:
            if receiver_config['video2'] == 'hdmi1':
                display2 = '7'
            else:
                raise Exception(f"Unexpected video2 config value: {receiver_config['video2']}")

        return (display, display2)

    def __get_video_command_crop_args(self, video_width, video_height):
        receiver_config = self.__receiver_config_stanza
        video_aspect_ratio = video_width / video_height

        wall_width = self.__config_loader.get_wall_width()
        wall_height = self.__config_loader.get_wall_height()
        wall_aspect_ratio = wall_width / wall_height

        # The displayable width and height represents the section of the video that the wall will be
        # displaying. A section of these dimensions will be taken from the center of the original
        # video.
        #
        # Currently, the piwall only supports displaying videos in "fill" mode (as opposed to
        # "letterbox" or "stretch"). This means that every portion of the TVs will be displaying
        # some section of the video (i.e. there will be no letterboxing). Furthermore, there will be
        # no warping of the video's aspect ratio. Instead, regions of the original video will be
        # cropped or stretched if necessary.
        displayable_video_width = None
        displayable_video_height = None
        if wall_aspect_ratio >= video_aspect_ratio:
            displayable_video_width = video_width
            displayable_video_height = video_width / wall_aspect_ratio
        else:
            displayable_video_height = video_height
            displayable_video_width = wall_aspect_ratio * video_height

        if displayable_video_width > video_width:
            self.__logger.warn(f"The displayable_video_width ({displayable_video_width}) " +
                f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
        if displayable_video_height > video_height:
            self.__logger.warn(f"The displayable_video_height ({displayable_video_height}) " +
                f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")

        x_offset = (video_width - displayable_video_width) / 2
        y_offset = (video_height - displayable_video_height) / 2

        x0 = round(x_offset + ((receiver_config['x'] / wall_width) * displayable_video_width))
        y0 = round(y_offset + ((receiver_config['y'] / wall_height) * displayable_video_height))
        x1 = round(x_offset + (((receiver_config['x'] + receiver_config['width']) / wall_width) * displayable_video_width))
        y1 = round(y_offset + (((receiver_config['y'] + receiver_config['height']) / wall_height) * displayable_video_height))

        if x0 > video_width:
            self.__logger.warn(f"The crop x0 coordinate ({x0}) " +
                f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
        if x1 > video_width:
            self.__logger.warn(f"The crop x1 coordinate ({x1}) " +
                f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
        if y0 > video_height:
            self.__logger.warn(f"The crop y0 coordinate ({y0}) " +
                f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")
        if y1 > video_height:
            self.__logger.warn(f"The crop y1 coordinate ({y1}) " +
                f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")

        crop = f"{x0} {y0} {x1} {y1}"

        crop2 = None
        if receiver_config['is_dual_video_output']:
            x0_2 = round(x_offset + ((receiver_config['x2'] / wall_width) * displayable_video_width))
            y0_2 = round(y_offset + ((receiver_config['y2'] / wall_height) * displayable_video_height))
            x1_2 = round(x_offset + (((receiver_config['x2'] + receiver_config['width2']) / wall_width) * displayable_video_width))
            y1_2 = round(y_offset + (((receiver_config['y2'] + receiver_config['height2']) / wall_height) * displayable_video_height))

            if x0_2 > video_width:
                self.__logger.warn(f"The crop x0_2 coordinate ({x0_2}) " +
                    f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
            if x1_2 > video_width:
                self.__logger.warn(f"The crop x1_2 coordinate ({x1_2}) " +
                    f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
            if y0_2 > video_height:
                self.__logger.warn(f"The crop y0_2 coordinate ({y0_2}) " +
                    f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")
            if y1_2 > video_height:
                self.__logger.warn(f"The crop y1_2 coordinate ({y1_2}) " +
                    f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")

            crop2 = f"{x0_2} {y0_2} {x1_2} {y1_2}"

        return (crop, crop2)

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
