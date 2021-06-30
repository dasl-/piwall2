import shlex
import subprocess
import time
import traceback
import youtube_dl
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.piwall2configloader import Piwall2ConfigLoader
from piwall2.parallelrunner import ParallelRunner

class Broadcaster:

    # For passwordless ssh from the broadcaster to the receivers.
    # See: https://github.com/dasl-/piwall2/blob/main/utils/setup_broadcaster_ssh
    SSH_KEY_PATH = '/home/pi/.ssh/piwall2_broadcaster/id_ed25519'

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'

    def __init__(self, video_url):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        Logger.set_uuid(Logger.make_uuid())
        self.__config_loader = Piwall2ConfigLoader()
        self.__video_url = video_url

        # Metadata about the video we are using, such as title, resolution, file extension, etc
        # Access should go through self.__get_video_info() to populate it lazily
        self.__video_info = None

    def broadcast(self):
        self.__logger.info(f"Starting broadcast for: {self.__video_url}")

        # Bind multicast traffic to eth0. Otherwise it might send over wlan0 -- multicast doesn't work well over wifi.
        # `|| true` to avoid 'RTNETLINK answers: File exists' if the route has already been added.
        (subprocess.check_output(
            f"sudo ip route add {MulticastHelper.ADDRESS}/32 dev eth0 || true",
            shell = True,
            executable = '/usr/bin/bash',
            stderr = subprocess.STDOUT
        ))

        receivers_proc = self.__start_receivers()

        # Mix the best audio with the video and send via multicast
        cmd = ("ffmpeg -re " +
            f"-i <(youtube-dl {shlex.quote(self.__video_url)} -f 'bestvideo[vcodec^=avc1][height<=720]' -o -) " +
            f"-i <(youtube-dl {shlex.quote(self.__video_url)} -f 'bestaudio' -o -) " +
            "-c:v copy -c:a aac -f matroska " +
            f"\"udp://{MulticastHelper.ADDRESS}:{MulticastHelper.VIDEO_PORT}\"")
        self.__logger.info(f"Running broadcast command: {cmd}")
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )

        self.__logger.info("Waiting for broadcast to end...")
        while proc.poll() is None:
            time.sleep(0.1)

        MulticastHelper().send(self.END_OF_VIDEO_MAGIC_BYTES, MulticastHelper.MSG_TYPE_VIDEO_STREAM)

        receivers_proc.wait()

    def __start_receivers(self):
        ssh_opts = (
            "-o ConnectTimeout=5 " +
            "-o UserKnownHostsFile=/dev/null " +
            "-o StrictHostKeyChecking=no " +
            "-o LogLevel=ERROR " +
            "-o PasswordAuthentication=no " +
            f"-o IdentityFile={shlex.quote(self.SSH_KEY_PATH)} "
        )
        cmds = []
        for receiver in self.__config_loader.get_receivers():
            receiver_cmd = self.__get_receiver_cmd(receiver)
            cmds.append(
                f"ssh {ssh_opts} pi@{receiver} {shlex.quote(receiver_cmd)}\n".encode()
            )
        return ParallelRunner().run_cmds(cmds)

    # TODO: make this actually work
    def __get_receiver_cmd(self, receiver):
        receiver_config = self.__config_loader.get_receivers_config()[receiver]
        adev, adev2 = self.__get_adevs_for_receiver(receiver, receiver_config)
        display, display2 = self.__get_displays_for_receiver(receiver, receiver_config)
        crop, crop2 = self.__get_crops_for_receiver(receiver, receiver_config)

        receiver_cmd_template = ('/home/pi/piwall2/receive --command "{0}" --log-uuid ' +
            shlex.quote(Logger.get_uuid()))

        omx_cmd_template = 'omxplayer --adev {0} --display {1} --crop {2} --no-keys --threshold 3 pipe:0'
        omx_cmd = omx_cmd_template.format(shlex.quote(adev), shlex.quote(display), shlex.quote(crop))

        receiver_cmd = None
        if receiver_config['is_dual_video_output']:
            omx_cmd2 = omx_cmd_template.format(shlex.quote(adev2), shlex.quote(display2), shlex.quote(crop2))
            tee_cmd = f"tee >({omx_cmd}) >({omx_cmd2}) >/dev/null"
            receiver_cmd = receiver_cmd_template.format(tee_cmd)
        else:
            receiver_cmd = receiver_cmd_template.format(omx_cmd)

        self.__logger.debug(f"Using receiver command for {receiver}: {receiver_cmd}")
        return receiver_cmd

    def __get_adevs_for_receiver(self, receiver, receiver_config):
        adev = None
        if receiver_config['audio'] == 'hdmi' or receiver_config['audio'] == 'hdmi0':
            adev = 'hdmi'
        elif receiver_config['audio'] == 'headphone':
            adev = 'local'
        elif receiver_config['audio'] == 'hdmi_alsa' or receiver_config['audio'] == 'hdmi0_alsa':
            adev = 'alsa:default:CARD=b1'
        else:
            raise Exception(f"Unexpected audio config value for receiver: {receiver}, value: {receiver_config['audio']}")

        adev2 = None
        if receiver_config['is_dual_video_output']:
            if receiver_config['audio2'] == 'hdmi1':
                adev2 = 'hdmi1'
            elif receiver_config['audio2'] == 'headphone':
                adev2 = 'local'
            elif receiver_config['audio'] == 'hdmi1_alsa':
                adev2 = 'alsa:default:CARD=b2'
            else:
                raise Exception(f"Unexpected audio2 config value for receiver: {receiver}, value: {receiver_config['audio2']}")

        return (adev, adev2)

    def __get_displays_for_receiver(self, receiver, receiver_config):
        display = None
        if receiver_config['video'] == 'hdmi' or receiver_config['video'] == 'hdmi0':
            display = '2'
        elif receiver_config['video'] == 'composite':
            display = '3'
        else:
            raise Exception(f"Unexpected video config value for receiver: {receiver}, value: {receiver_config['video']}")

        display2 = None
        if receiver_config['is_dual_video_output']:
            if receiver_config['video2'] == 'hdmi1':
                display2 = '7'
            else:
                raise Exception(f"Unexpected video2 config value for receiver: {receiver}, value: {receiver_config['video2']}")

        return (display, display2)

    def __get_crops_for_receiver(self, receiver, receiver_config):
        video_width = self.__get_video_info()['width']
        video_height = self.__get_video_info()['height']
        video_aspect_ratio = video_width / video_height

        wall_width = self.__config_loader.get_wall_width()
        wall_height = self.__config_loader.get_wall_height()
        wall_aspect_ratio = wall_width / wall_height

        # The displayable width and height represents the section of the video that the wall will be
        # displaying. A section of these dimensions will be taken from the center of the original
        # video.
        #
        # Currently, the piwall only supports displaying videos in "fill" mode. This means that every
        # portion of the TVs will be displaying some section of the video (i.e. there will be no
        # letterboxing). Furthermore, there will be no warping of the video's aspect ratio. Instead,
        # regions of the original video will be cropped out if necessary.
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

        x0 = x_offset + ((receiver_config['x'] / wall_width) * displayable_video_width)
        y0 = y_offset + ((receiver_config['y'] / wall_height) * displayable_video_height)
        x1 = x_offset + (((receiver_config['x'] + receiver_config['width']) / wall_width) * displayable_video_width)
        y1 = y_offset + (((receiver_config['y'] + receiver_config['height']) / wall_height) * displayable_video_height)

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

        crop = f"{x0},{y0},{x1},{y1}"

        crop2 = None
        if receiver_config['is_dual_video_output']:
            x0_2 = x_offset + ((receiver_config['x2'] / wall_width) * displayable_video_width)
            y0_2 = y_offset + ((receiver_config['y2'] / wall_height) * displayable_video_height)
            x1_2 = x_offset + (((receiver_config['x2'] + receiver_config['width2']) / wall_width) * displayable_video_width)
            y1_2 = y_offset + (((receiver_config['y2'] + receiver_config['height2']) / wall_height) * displayable_video_height)

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

            crop2 = f"{x0_2},{y0_2},{x1_2},{y1_2}"

        return (crop, crop2)

    # Lazily populate video_info from youtube. This takes a couple seconds.
    def __get_video_info(self):
        if self.__video_info:
            return self.__video_info

        self.__logger.info("Downloading and populating video metadata...")
        ydl_opts = {
            'format': self.__config_loader.get_youtube_dl_video_format(),
            'logger': Logger().set_namespace('youtube_dl'),
            'restrictfilenames': True, # get rid of a warning ytdl gives about special chars in file names
        }
        ydl = youtube_dl.YoutubeDL(ydl_opts)

        # Automatically try to update youtube-dl and retry failed youtube-dl operations when we get a youtube-dl
        # error.
        #
        # The youtube-dl package needs updating periodically when youtube make updates. This is
        # handled on a cron once a day: https://github.com/dasl-/pifi/blob/a614b33e1be093f6ee3bb62b036ee6472ffe5132/install/pifi_cron.sh#L5
        #
        # But we also attempt to update it on the fly here if we get youtube-dl errors when trying to play
        # a video.
        #
        # Example of how this would look in logs: https://gist.github.com/dasl-/09014dca55a2e31bb7d27f1398fd8155
        max_attempts = 2
        for attempt in range(1, (max_attempts + 1)):
            try:
                self.__video_info = ydl.extract_info(self.__video_url, download = False)
            except Exception as e:
                caught_or_raising = "Raising"
                if attempt < max_attempts:
                    caught_or_raising = "Caught"
                self.__logger.warning("Problem downloading video info during attempt {} of {}. {} exception: {}"
                    .format(attempt, max_attempts, caught_or_raising, traceback.format_exc()))
                if attempt < max_attempts:
                    self.__logger.warning("Attempting to update youtube-dl before retrying download...")
                    update_youtube_dl_output = (subprocess
                        .check_output(
                            'sudo ' + DirectoryUtils().root_dir + '/utils/update_youtube-dl.sh',
                            shell = True,
                            executable = '/usr/bin/bash',
                            stderr = subprocess.STDOUT
                        )
                        .decode("utf-8"))
                    self.__logger.info("Update youtube-dl output: {}".format(update_youtube_dl_output))
                else:
                    self.__logger.error("Unable to download video info after {} attempts.".format(max_attempts))
                    raise e

        self.__logger.info("Done downloading and populating video metadata.")

        self.__logger.info(f"Using: {self.__video_info['vcodec']} / {self.__video_info['ext']}@" +
            f"{self.__video_info['width']}x{self.__video_info['height']}")

        return self.__video_info
