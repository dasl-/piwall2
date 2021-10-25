import math
import shlex

from piwall2.directoryutils import DirectoryUtils
from piwall2.displaymode import DisplayMode
from piwall2.logger import Logger
import piwall2.receiver.receiver
from piwall2.volumecontroller import VolumeController

# Helper to build the "receive and play video" command
class ReceiverCommandBuilder:

    def __init__(self, config_loader, receiver_config_stanza):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__config_loader = config_loader
        self.__receiver_config_stanza = receiver_config_stanza

    def build_receive_and_play_video_command_and_get_crop_args(
        self, log_uuid, video_width, video_height, volume_pct, display_mode, display_mode2
    ):
        adev, adev2 = self.__get_video_command_adev_args()
        display, display2 = self.__get_video_command_display_args()
        crop_args, crop_args2 = self.__get_video_command_crop_args(video_width, video_height)
        crop = crop_args[display_mode]
        crop2 = crop_args2[display_mode2]
        orientation = self.__receiver_config_stanza.get('orientation', 0)
        orientation2 = self.__receiver_config_stanza.get('orientation2', 0)
        live = ' --live ' if orientation else ''
        live2 = ' --live ' if orientation2 else ''

        volume_pct = VolumeController.normalize_vol_pct(volume_pct)

        # See: https://github.com/popcornmix/omxplayer/#volume-rw
        if volume_pct == 0:
            volume_millibels = VolumeController.GLOBAL_MIN_VOL_VAL
        else:
            volume_millibels = 2000 * math.log(volume_pct, 10)

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
        mbuffer_cmd = ('HOME=/home/pi mbuffer -q -l /tmp/mbuffer.out -m ' +
            f'{piwall2.receiver.receiver.Receiver.VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES}b')

        # See: https://github.com/dasl-/piwall2/blob/main/docs/configuring_omxplayer.adoc
        omx_cmd_template = ('omxplayer --crop {0} --adev {1} --display {2} --vol {3} --orientation {4} {5} ' +
            '--no-keys --timeout 30 --threshold 0.2 --video_fifo 35 --genlog pipe:0')

        omx_cmd = omx_cmd_template.format(
            shlex.quote(crop), shlex.quote(adev), shlex.quote(display), shlex.quote(str(volume_millibels)),
            shlex.quote(str(orientation)), live
        )
        cmd = 'set -o pipefail && '
        if self.__receiver_config_stanza['is_dual_video_output']:
            omx_cmd2 = omx_cmd_template.format(
                shlex.quote(crop2), shlex.quote(adev2), shlex.quote(display2), shlex.quote(str(volume_millibels)),
                shlex.quote(str(orientation2)), live2
            )
            cmd += f'{mbuffer_cmd} | tee >({omx_cmd}) >({omx_cmd2}) >/dev/null'
        else:
            cmd += f'{mbuffer_cmd} | {omx_cmd}'

        receiver_cmd = (f'{DirectoryUtils().root_dir}/bin/receive_and_play_video --command {shlex.quote(cmd)} ' +
            f'--log-uuid {shlex.quote(log_uuid)}')
        return (receiver_cmd, crop_args, crop_args2)

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

    """
    Returns a set of crop args supporting two display modes: tile mode and repeat mode.
    Tile mode is like this: https://i.imgur.com/BBrA1Cr.png
    Repeat mode is like this: https://i.imgur.com/cpS61s8.png

    We return four crop settings because for each mode, we calculate the crop arguments
    for each of two TVs (each receiver can have at most two TVs hooked up to it).
    """
    def __get_video_command_crop_args(self, video_width, video_height):
        receiver_config = self.__receiver_config_stanza

        #####################################################################################
        # Do tile mode calculations first ###################################################
        #####################################################################################
        wall_width = self.__config_loader.get_wall_width()
        wall_height = self.__config_loader.get_wall_height()

        displayable_video_width, displayable_video_height = (
            self.__get_displayable_video_dimensions_for_screen(
                video_width, video_height, wall_width, wall_height
            )
        )
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

        tile_mode_crop = f"{x0} {y0} {x1} {y1}"

        tile_mode_crop2 = None
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

            tile_mode_crop2 = f"{x0_2} {y0_2} {x1_2} {y1_2}"

        #####################################################################################
        # Do repeat mode calculations second ################################################
        #####################################################################################
        displayable_video_width, displayable_video_height = (
            self.__get_displayable_video_dimensions_for_screen(
                video_width, video_height, receiver_config['width'], receiver_config['height']
            )
        )
        x_offset = (video_width - displayable_video_width) / 2
        y_offset = (video_height - displayable_video_height) / 2

        repeat_mode_crop = f"{x_offset} {y_offset} {x_offset + displayable_video_width} {x_offset + displayable_video_height}"

        repeat_mode_crop2 = None
        if receiver_config['is_dual_video_output']:
            displayable_video_width, displayable_video_height = (
                self.__get_displayable_video_dimensions_for_screen(
                    video_width, video_height, receiver_config['width2'], receiver_config['height2']
                )
            )
            x_offset = (video_width - displayable_video_width) / 2
            y_offset = (video_height - displayable_video_height) / 2

            repeat_mode_crop2 = f"{x_offset} {y_offset} {x_offset + displayable_video_width} {x_offset + displayable_video_height}"

        crop_args = {
            DisplayMode.DISPLAY_MODE_TILE: tile_mode_crop,
            DisplayMode.DISPLAY_MODE_REPEAT: repeat_mode_crop,
        }
        crop_args2 = {
            DisplayMode.DISPLAY_MODE_TILE: tile_mode_crop2,
            DisplayMode.DISPLAY_MODE_REPEAT: repeat_mode_crop2,
        }
        return (crop_args, crop_args2)

    """
    The displayable width and height represents the section of the video that the wall will be
    displaying. A section of these dimensions will be taken from the center of the original
    video.

    Currently, the piwall only supports displaying videos in "fill" mode (as opposed to
    "letterbox" or "stretch"). This means that every portion of the TVs will be displaying
    some section of the video (i.e. there will be no letterboxing). Furthermore, there will be
    no warping of the video's aspect ratio. Instead, regions of the original video will be
    cropped or stretched if necessary.

    The units of the width and height arguments are not important. We are just concerned with
    the aspect ratio. Thus, as long as video_width and video_height are in the same units
    (probably pixels), and as long as screen_width and screen_height are in the same units
    (probably inches or centimeters), everything will work.

    The returned dimensions will be in the units of the inputted video_width and video_height
    (probably pixels).
    """
    def __get_displayable_video_dimensions_for_screen(self, video_width, video_height, screen_width, screen_height):
        video_aspect_ratio = video_width / video_height
        screen_aspect_ratio = screen_width / screen_height
        if screen_aspect_ratio >= video_aspect_ratio:
            displayable_video_width = video_width
            displayable_video_height = video_width / screen_aspect_ratio
            """
            Note that `video_width = video_aspect_ratio * video_height`.
            Thus, via substitution, we have:
                displayable_video_height = (video_aspect_ratio * video_height) / screen_aspect_ratio
                displayable_video_height = (video_aspect_ratio / screen_aspect_ratio) * video_height

            And because of the above inequality, we know that:
                (video_aspect_ratio / screen_aspect_ratio) <= 1

            Thus, in this case, we have: `displayable_video_height <= video_height`. The video height
            will be "cropped" such that when the video is proportionally stretched, it will fill the
            screen size.
            """

        else:
            displayable_video_height = video_height
            displayable_video_width = screen_aspect_ratio * video_height
            """
            Note that `video_height = video_width / video_aspect_ratio`.
            Thus, via substitution, we have:
                displayable_video_width = screen_aspect_ratio * (video_width / video_aspect_ratio)
                displayable_video_width = video_width * (screen_aspect_ratio / video_aspect_ratio)

            And because of the above inequality for which we are now in the `else` clause, we know that:
                (screen_aspect_ratio / video_aspect_ratio) <= 1

            Thus, in this case, we have: `displayable_video_width <= video_width`. The video width
            will be "cropped" such that when the video is proportionally stretched, it will fill the
            screen size.
            """

        if displayable_video_width > video_width:
            self.__logger.warn(f"The displayable_video_width ({displayable_video_width}) " +
                f"was greater than the video_width ({video_width}). This may indicate a misconfiguration.")
        if displayable_video_height > video_height:
            self.__logger.warn(f"The displayable_video_height ({displayable_video_height}) " +
                f"was greater than the video_height ({video_height}). This may indicate a misconfiguration.")

        return (displayable_video_width, displayable_video_height)
