import os
import shlex
import signal
import subprocess
import sys
import time
import traceback
import youtube_dl

from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.receiver.receiver import Receiver
from piwall2.volumecontroller import VolumeController

# Broadcasts a video for playback on the piwall
class VideoBroadcaster:

    # For passwordless ssh from the broadcaster to the receivers.
    # See: https://github.com/dasl-/piwall2/blob/main/utils/setup_broadcaster_and_receivers
    SSH_KEY_PATH = '/home/pi/.ssh/piwall2_broadcaster/id_ed25519'

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'

    __VIDEO_URL_TYPE_YOUTUBEDL = 'video_url_type_youtubedl'
    __VIDEO_URL_TYPE_FILE = 'video_url_type_file'
    __AUDIO_FORMAT = 'bestaudio'

    # Touch this file when video playing is done.
    # We check for its existence to determine when video playback is over.
    __VIDEO_PLAYBACK_DONE_FILE = '/tmp/video_playback_done.file'

    # video_url may be a youtube url or a path to a file on disk
    def __init__(self, video_url):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        Logger.set_uuid(Logger.make_uuid())
        self.__config_loader = ConfigLoader()
        self.__video_url = video_url

        # Store the PGIDs separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__video_broadcast_proc_pgid = None
        self.__download_and_convert_video_proc_pgid = None

        # Metadata about the video we are using, such as title, resolution, file extension, etc
        # Access should go through self.__get_video_info() to populate it lazily
        self.__video_info = None

        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__do_housekeeping()
        self.__register_signal_handlers()

    def broadcast(self):
        try:
            self.__broadcast_internal()
        finally:
            self.__do_housekeeping()

    def __broadcast_internal(self):
        self.__logger.info(f"Starting broadcast for: {self.__video_url}")

        # Bind multicast traffic to eth0. Otherwise it might send over wlan0 -- multicast doesn't work well over wifi.
        # `|| true` to avoid 'RTNETLINK answers: File exists' if the route has already been added.
        (subprocess.check_output(
            f"sudo ip route add {MulticastHelper.ADDRESS}/32 dev eth0 || true",
            shell = True,
            executable = '/usr/bin/bash',
            stderr = subprocess.STDOUT
        ))

        """
        What's going on here? We invoke youtube-dl (ytdl) three times in the broadcast code:
        1) To populate video metadata, including dimensions which allow us to know how much to crop the video
        2) To download the proper video format (which generally does not have sound included) and mux it with (3)
        3) To download the best audio quality

        Ytdl takes couple of seconds to be invoked. Luckily, (2) and (3) happen in parallel
        (see self.____get_ffmpeg_input_clause). But that would still leave us with effectively two groups of ytdl
        invocations which are happening serially: the group consisting of "1" and the group consisting of "2 and 3".
        Note that (1) happens in self.__get_video_info.

        By starting a separate process for "2 and 3", we can actually ensure that all three of these invocations
        happen in parallel. This separate process is started in self.__start_download_and_convert_video_proc.
        This shaves 2-3 seconds off of video start up time.

        This requires that we break up the original single pipeline into two halves. Originally, a single
        pipeline was responsible for downloading, converting, and broadcasting the video. Receivers were
        """
        download_and_convert_video_proc = self.__start_download_and_convert_video_proc()
        self.__get_video_info(assert_data_not_yet_loaded = True)
        self.__start_receivers()

        # See: https://github.com/dasl-/piwall2/blob/main/docs/controlling_video_broadcast_speed.adoc
        mbuffer_size = round(Receiver.VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES / 2)
        burst_throttling_clause = (f'mbuffer -q -l /tmp/mbuffer.out -m {mbuffer_size}b | ' +
            'ffmpeg -re -i pipe:0 -c:v copy -c:a copy -f mpegts - >/dev/null ; ' +
            f'touch {self.__VIDEO_PLAYBACK_DONE_FILE}')
        broadcasting_clause = DirectoryUtils().root_dir + f"/msend_video --log-uuid {shlex.quote(Logger.get_uuid())}"

        # Mix the best audio with the video and send via multicast
        # See: https://github.com/dasl-/piwall2/blob/main/docs/best_video_container_format_for_streaming.adoc
        cmd = (f"set -o pipefail && tee >({burst_throttling_clause}) >({broadcasting_clause}) >/dev/null")
        self.__logger.info(f"Running broadcast command: {cmd}")

        # Info on start_new_session: https://gist.github.com/dasl-/1379cc91fb8739efa5b9414f35101f5f
        # Allows killing all processes (subshells, children, grandchildren, etc as a group)
        video_broadcast_proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True,
            stdin = download_and_convert_video_proc.stdout
        )
        self.__video_broadcast_proc_pgid = os.getpgid(video_broadcast_proc.pid)

        self.__logger.info("Waiting for broadcast command to end...")
        while video_broadcast_proc.poll() is None:
            time.sleep(0.1)
        self.__logger.info("Video broadcast command ended. Waiting for video playback to end...")
        MulticastHelper().setup_broadcaster_socket().send(self.END_OF_VIDEO_MAGIC_BYTES, MulticastHelper.VIDEO_PORT)

        while not os.path.isfile(self.__VIDEO_PLAYBACK_DONE_FILE):
            time.sleep(0.1)

        # Wait to ensure video playback is done. Data collected suggests one second is sufficient:
        # https://docs.google.com/spreadsheets/d/1YzxsD3GPzsIeKYliADN3af7ORys5nXHCRBykSnHaaxk/edit#gid=0
        time.sleep(1)
        self.__logger.info("Video playback is likely over.")

    """
    Process to download video via youtube-dl and convert it to proper format via ffmpeg.
    Note that we only download the video if the input was a youtube_url. If playing a local file, no
    download is necessary.
    """
    def __start_download_and_convert_video_proc(self):
        # See: https://github.com/dasl-/piwall2/blob/main/docs/streaming_high_quality_videos_from_youtube-dl_to_stdout.adoc
        ffmpeg_input_clause = self.__get_ffmpeg_input_clause()

        audio_clause = '-c:a mp2 -b:a 192k' # TODO: is this necessary? Can we use mp3?
        if self.__get_video_url_type() == self.__VIDEO_URL_TYPE_FILE:
            # Don't transcode audio if we don't need to
            audio_clause = '-c:a copy'

        # Mix the best audio with the video and send via multicast
        # See: https://github.com/dasl-/piwall2/blob/main/docs/best_video_container_format_for_streaming.adoc
        cmd = (f"set -o pipefail && ffmpeg {ffmpeg_input_clause} " +
            f"-c:v copy {audio_clause} -f mpegts -")

        # Info on start_new_session: https://gist.github.com/dasl-/1379cc91fb8739efa5b9414f35101f5f
        # Allows killing all processes (subshells, children, grandchildren, etc as a group)
        download_and_convert_video_proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdout = subprocess.PIPE
        )
        self.__download_and_convert_video_proc_pgid = os.getpgid(download_and_convert_video_proc.pid)
        return download_and_convert_video_proc

    def __start_receivers(self):
        msg = {}
        for receiver in self.__config_loader.get_receivers_list():
            msg[receiver] = self.__get_receiver_params_list(receiver)
        msg['log_uuid'] = Logger.get_uuid()
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_PLAY_VIDEO, msg)
        self.__logger.info("Sent play_video control message.")

    def __get_receiver_params_list(self, receiver):
        receiver_config = self.__config_loader.get_receivers_config()[receiver]
        adev, adev2 = self.__get_adevs_for_receiver(receiver, receiver_config)
        display, display2 = self.__get_displays_for_receiver(receiver, receiver_config)
        crop, crop2 = self.__get_crops_for_receiver(receiver, receiver_config)
        volume = VolumeController().get_vol_millibels()

        # See: https://github.com/dasl-/piwall2/blob/main/docs/configuring_omxplayer.adoc
        omx_misc_params_template = ('--adev {0} --display {1} --vol {2} ' +
            '--no-keys --timeout 20 --threshold 0.2 --video_fifo 35 --genlog pipe:0')
        omx_misc_params = omx_misc_params_template.format(shlex.quote(adev), shlex.quote(display),
            shlex.quote(str(volume)))

        params = {
            'crop': crop,
            'misc': omx_misc_params,
        }

        if receiver_config['is_dual_video_output']:
            omx_misc_params2 = omx_misc_params_template.format(shlex.quote(adev2), shlex.quote(display2),
                shlex.quote(str(volume)))
            params2 = {
                'crop': crop2,
                'misc': omx_misc_params2,
            }
            params_list = [params, params2]
        else:
            params_list = [params]

        self.__logger.debug(f"Using params_list for {receiver}: {params_list}")
        return params_list

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

            Use yt-dlp, a fork of youtube-dl that has a workaround (for now) for an issue where youtube has been
            throttling youtube-dl’s download speed:
            https://github.com/ytdl-org/youtube-dl/issues/29326#issuecomment-879256177
            """
            youtube_dl_cmd_template = ("yt-dlp --extractor-args youtube:player_client=android {0} " +
                "--retries infinite --format {1} --output - | mbuffer -q -Q -m {2}b")

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
            # ffmpeg an opportunity to start-up without us having to explicitly sleep.
            return f"-i <( sleep 2 ; cat {shlex.quote(self.__video_url)} )"

    # Lazily populate video_info from youtube. This takes a couple seconds, as it invokes youtube-dl on the video.
    # Must return a dict containing the keys: width, height
    def __get_video_info(self, assert_data_not_yet_loaded = False):
        if self.__video_info:
            if assert_data_not_yet_loaded:
                raise Exception('Failed asserting that data was not yet loaded')
            return self.__video_info

        video_url_type = self.__get_video_url_type()
        if video_url_type == self.__VIDEO_URL_TYPE_YOUTUBEDL:
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
            # handled on a cron once a day:
            # https://github.com/dasl-/pifi/blob/a614b33e1be093f6ee3bb62b036ee6472ffe5132/install/pifi_cron.sh#L5
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
        elif video_url_type == self.__VIDEO_URL_TYPE_FILE:
            # TODO: guard against unsupported video formats
            ffprobe_cmd = ('ffprobe -v 0 -of csv=p=0 -select_streams v:0 -show_entries stream=width,height ' +
                shlex.quote(self.__video_url))
            ffprobe_output = (subprocess
                .check_output(ffprobe_cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT)
                .decode("utf-8"))
            ffprobe_output = ffprobe_output.split('\n')[0]
            ffprobe_parts = ffprobe_output.split(',')
            self.__video_info = {
                'width': int(ffprobe_parts[0]),
                'height': int(ffprobe_parts[1]),
            }

        return self.__video_info

    def __get_video_url_type(self):
        if self.__video_url.startswith('http://') or self.__video_url.startswith('https://'):
            return self.__VIDEO_URL_TYPE_YOUTUBEDL
        else:
            return self.__VIDEO_URL_TYPE_FILE

    def __do_housekeeping(self):
        if self.__download_and_convert_video_proc_pgid:
            self.__logger.info("Killing download and convert video process group (PGID: " +
                f"{self.__download_and_convert_video_proc_pgid})...")
            try:
                os.killpg(self.__download_and_convert_video_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        if self.__video_broadcast_proc_pgid:
            self.__logger.info("Killing video broadcast process group (PGID: " +
                f"{self.__video_broadcast_proc_pgid}...")
            try:
                os.killpg(self.__video_broadcast_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SKIP_VIDEO, '')
        try:
            os.remove(self.__VIDEO_PLAYBACK_DONE_FILE)
        except Exception:
            pass

    def __register_signal_handlers(self):
        signal.signal(signal.SIGINT, self.__signal_handler)
        signal.signal(signal.SIGHUP, self.__signal_handler)
        signal.signal(signal.SIGQUIT, self.__signal_handler)
        signal.signal(signal.SIGABRT, self.__signal_handler)
        signal.signal(signal.SIGFPE, self.__signal_handler)
        signal.signal(signal.SIGSEGV, self.__signal_handler)
        signal.signal(signal.SIGPIPE, self.__signal_handler)
        signal.signal(signal.SIGTERM, self.__signal_handler)

    def __signal_handler(self, sig, frame):
        self.__logger.info(f"Caught signal {sig}, exiting gracefully...")
        self.__do_housekeeping()
        sys.exit(sig)
