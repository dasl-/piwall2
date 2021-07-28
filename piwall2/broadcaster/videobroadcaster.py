import shlex
import subprocess
import time
import traceback
import youtube_dl
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.configloader import ConfigLoader
from piwall2.parallelrunner import ParallelRunner
from piwall2.volumecontroller import VolumeController

# Broadcasts a video for playback on the piwall
class VideoBroadcaster:

    # For passwordless ssh from the broadcaster to the receivers.
    # See: https://github.com/dasl-/piwall2/blob/main/utils/setup_broadcaster_and_receivers
    SSH_KEY_PATH = '/home/pi/.ssh/piwall2_broadcaster/id_ed25519'

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'
    RECEIVER_MBUFFER_SIZE = 1024 * 1024 * 1024 # 1024 MB

    __VIDEO_URL_TYPE_YOUTUBEDL = 'video_url_type_youtubedl'
    __VIDEO_URL_TYPE_FILE = 'video_url_type_file'
    __AUDIO_FORMAT = 'bestaudio'

    # video_url may be a youtube url or a path to a file on disk
    def __init__(self, video_url):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        Logger.set_uuid(Logger.make_uuid())
        self.__config_loader = ConfigLoader()
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

        # See: https://github.com/dasl-/piwall2/blob/main/docs/streaming_high_quality_videos_from_youtube-dl_to_stdout.adoc
        ffmpeg_input_clause = self.__get_ffmpeg_input_clause()

        audio_clause = '-c:a mp2 -b:a 192k'
        if self.__get_video_url_type() == self.__VIDEO_URL_TYPE_FILE:
            audio_clause = '-c:a copy'

        duration = shlex.quote(str(self.__video_info['duration']))
        size = shlex.quote(str(self.__video_info['__total_size__']))

        # Mix the best audio with the video and send via multicast
        # See: https://github.com/dasl-/piwall2/blob/main/docs/best_video_container_format_for_streaming.adoc
        cmd = (f"ffmpeg {ffmpeg_input_clause} " +
            f"-c:v copy {audio_clause} -f mpegts - | " +
            f"{DirectoryUtils().root_dir}/throttle_broadcast --size {size} --duration {duration} " +
            f"--log-uuid {shlex.quote(Logger.get_uuid())}")
        self.__logger.info(f"Running broadcast command: {cmd}")
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )

        self.__logger.info("Waiting for broadcast to end...")
        while proc.poll() is None:
            time.sleep(0.1)

        MulticastHelper().setup_broadcaster_socket().send(self.END_OF_VIDEO_MAGIC_BYTES, MulticastHelper.MSG_TYPE_VIDEO_STREAM)

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
        for receiver in self.__config_loader.get_receivers_list():
            receiver_cmd = self.__get_receiver_cmd(receiver)
            cmds.append(
                f"ssh {ssh_opts} pi@{receiver} {shlex.quote(receiver_cmd)}\n".encode()
            )
        return ParallelRunner().run_cmds(cmds)

    def __get_receiver_cmd(self, receiver):
        receiver_config = self.__config_loader.get_receivers_config()[receiver]
        adev, adev2 = self.__get_adevs_for_receiver(receiver, receiver_config)
        display, display2 = self.__get_displays_for_receiver(receiver, receiver_config)
        crop, crop2 = self.__get_crops_for_receiver(receiver, receiver_config)
        volume = VolumeController().get_vol_millibels()

        receiver_cmd_template = ('/home/pi/piwall2/receive --command "{0}" --log-uuid ' +
            shlex.quote(Logger.get_uuid()) + ' >/tmp/receiver.log 2>&1')

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
        mbuffer_cmd = f'mbuffer -q -l /tmp/mbuffer.out -m {self.RECEIVER_MBUFFER_SIZE}b'

        # See: https://github.com/dasl-/piwall2/blob/main/docs/configuring_omxplayer.adoc
        omx_cmd_template = ('omxplayer --adev {0} --display {1} --crop {2} --vol {3} ' +
            '--no-keys --threshold 5 --video_fifo 35 --genlog pipe:0')
        omx_cmd = omx_cmd_template.format(shlex.quote(adev), shlex.quote(display),
            shlex.quote(crop), shlex.quote(str(volume)))

        receiver_cmd = None
        if receiver_config['is_dual_video_output']:
            omx_cmd2 = omx_cmd_template.format(shlex.quote(adev2), shlex.quote(display2),
                shlex.quote(crop2), shlex.quote(str(volume)))
            tee_cmd = f"{mbuffer_cmd} | tee >({omx_cmd}) >({omx_cmd2}) >/dev/null"
            receiver_cmd = receiver_cmd_template.format(tee_cmd)
        else:
            receiver_cmd = receiver_cmd_template.format(f'{mbuffer_cmd} | {omx_cmd}')

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

        crop = f"{x0},{y0},{x1},{y1}"

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

            crop2 = f"{x0_2},{y0_2},{x1_2},{y1_2}"

        return (crop, crop2)

    def __get_ffmpeg_input_clause(self):
        video_url_type = self.__get_video_url_type()
        if video_url_type == self.__VIDEO_URL_TYPE_YOUTUBEDL:
            """
            Pipe to mbuffer to avoid video drop outs when youtube-dl temporarily loses its connection
            and is trying to reconnect:

                [download] Got server HTTP error: [Errno 104] Connection reset by peer. Retrying (attempt 1 of 10)...
                [download] Got server HTTP error: [Errno 104] Connection reset by peer. Retrying (attempt 2 of 10)...
                [download] Got server HTTP error: [Errno 104] Connection reset by peer. Retrying (attempt 3 of 10)...

            This can happen from time to time when downloading long videos.
            Youtube-dl should download quickly until it fills the mbuffer. After the mbuffer is filled,
            ffmpeg will apply backpressure to youtube-dl because of ffmpeg's `-re` flag

            --retries infinite: using this to avoid scenarios where all of the retries (10 by default) were
            exhausted on long video downloads. After a while, retries would be necessary to reconnect. The
            retries would be successful, but the connection errors would happen again a few minutes later.
            This allows us to keep retrying whenever it is necessary.
            """
            youtube_dl_cmd_template = "youtube-dl {0} --retries infinite --format {1} --output - | mbuffer -q -Q -m {2}b"

            # 50 MB. Based on one video, 1080p avc1 video consumes about 0.36 MB/s. So this should
            # be enough buffer for ~139s
            video_buffer_size = 1024 * 1024 * 50
            youtube_dl_video_cmd = youtube_dl_cmd_template.format(
                shlex.quote(self.__video_url),
                shlex.quote(self.__config_loader.get_youtube_dl_video_format()),
                video_buffer_size
            )

            # 5 MB. Based on one video, audio consumes about 0.016 MB/s. So this should
            # be enough buffer for ~312s
            audio_buffer_size = 1024 * 1024 * 5
            youtube_dl_audio_cmd = youtube_dl_cmd_template.format(
                shlex.quote(self.__video_url),
                shlex.quote(self.__AUDIO_FORMAT),
                audio_buffer_size
            )

            return f"-i <({youtube_dl_video_cmd}) -i <({youtube_dl_audio_cmd})"
        elif video_url_type == self.__VIDEO_URL_TYPE_FILE:
            # Why the process substitution and sleep? Ffmpeg seemed to occasionally stumble playing the video
            # without the sleep. This would result in:
            # 1) The first couple seconds of the video getting skipped
            # 2) Slightly out of sync video across the TVs
            #
            # (1) would happen every time, whereas (2) happened 3 out of 8 times during testing.
            # Perhaps the sleep gives ffmpeg time to start up before starting to play the video.
            # When using youtube-dl, it takes some time for the download of the video to start, giving
            # ffmpeg an opportunity to start-up without us having to explicltly sleep.
            return f"-i <( sleep 2 ; cat {shlex.quote(self.__video_url)} )"

    # Lazily populate video_info from youtube. This takes a couple seconds.
    # Must return a dict containing the keys: width, height
    def __get_video_info(self):
        if self.__video_info:
            return self.__video_info

        video_url_type = self.__get_video_url_type()
        if video_url_type == self.__VIDEO_URL_TYPE_YOUTUBEDL:
            self.__logger.info("Downloading and populating video metadata...")
            ydl_opts = {
                'format': self.__config_loader.get_youtube_dl_video_format() + '+' + self.__AUDIO_FORMAT,
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

            total_size = (self.__video_info['requested_formats'][0]['filesize'] +
                self.__video_info['requested_formats'][1]['filesize'])
            self.__video_info['__total_size__'] = total_size

            self.__logger.info("Done downloading and populating video metadata.")
            self.__logger.info(f"Using: {self.__video_info['vcodec']} / {self.__video_info['ext']}@" +
                f"{self.__video_info['width']}x{self.__video_info['height']}")
        elif video_url_type == self.__VIDEO_URL_TYPE_FILE:
            # TODO: guard against unsupported video formats
            ffprobe_cmd = ('ffprobe -v 0 -of csv=p=0 -select_streams v:0 -show_entries stream=width,height,duration ' +
                f'-show_entries format=size {shlex.quote(self.__video_url)}')
            ffprobe_output = (subprocess
                .check_output(ffprobe_cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT)
                .decode("utf-8"))
            ffprobe_lines = ffprobe_output.split('\n')
            ffprobe_stream_parts = ffprobe_lines[0].split(',')

            # sometimes this may have either 2 or 3 lines of output. The format parts will always be on the last line.
            ffprobe_format_parts = ffprobe_lines[len(ffprobe_lines - 1)].split(',')
            self.__video_info = {
                'width': int(ffprobe_stream_parts[0]),
                'height': int(ffprobe_stream_parts[1]),
                'duration': int(ffprobe_stream_parts[2]),
                '__total_size__': int(ffprobe_format_parts[0])
            }

        return self.__video_info

    def __get_video_url_type(self):
        if self.__video_url.startswith('http://') or self.__video_url.startswith('https://'):
            return self.__VIDEO_URL_TYPE_YOUTUBEDL
        else:
            return self.__VIDEO_URL_TYPE_FILE
