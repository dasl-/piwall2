import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from piwall2.broadcaster.loadingscreenhelper import LoadingScreenHelper
from piwall2.broadcaster.youtubedlexception import YoutubeDlException
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.multicasthelper import MulticastHelper
from piwall2.receiver.receiver import Receiver

# Broadcasts a video for playback on the piwall
class VideoBroadcaster:

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'

    __VIDEO_URL_TYPE_YOUTUBE = 'video_url_type_youtube'
    __VIDEO_URL_TYPE_LOCAL_FILE = 'video_url_type_local_file'
    __AUDIO_FORMAT = 'bestaudio'

    __FIFO_PREFIX = 'piwall2_fifo'

    # Touch this file when video playing is done.
    # We check for its existence to determine when video playback is over.
    __VIDEO_PLAYBACK_DONE_FILE = '/tmp/video_playback_done.file'

    # Workaround for https://github.com/yt-dlp/yt-dlp/issues/6447
    __VIDEO_TMP_DIR = '/tmp/piwall2_video_tmp'
    __AUDIO_TMP_DIR = '/tmp/piwall2_audio_tmp'

    # video_url: may be a youtube url or a path to a file on disk
    # show_loading_screen: Loading screen may also get shown by the queue process. Sending the
    #   signal to show it from the queue is faster than showing it in the videobroadcaster
    #   process. But one may still wish to show a loading screen when playing videos via the
    #   command line.
    #
    # yt_dlp_extractors: string. Extractor names for yt-dlp to use, separated by commas.
    #   Whitelisting extractors to use can speed up video download initialization time.
    #   Refer to yt-dlp documentation for the '--use-extractors' flag for more details.
    def __init__(self, video_url, log_uuid, show_loading_screen, yt_dlp_extractors):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        if log_uuid:
            Logger.set_uuid(log_uuid)
        else:
            Logger.set_uuid(Logger.make_uuid())

        self.__config_loader = ConfigLoader()
        self.__video_url = video_url
        self.__show_loading_screen = show_loading_screen
        self.__yt_dlp_extractors = yt_dlp_extractors

        # Store the PGIDs separately, because attempting to get the PGID later via `os.getpgid` can
        # raise `ProcessLookupError: [Errno 3] No such process` if the process is no longer running
        self.__video_broadcast_proc_pgid = None
        self.__download_and_convert_video_proc_pgid = None

        self.__dimensions_fifo_name = None

        # Bind multicast traffic to eth0. Otherwise it might send over wlan0 -- multicast doesn't work well over wifi.
        # `|| true` to avoid 'RTNETLINK answers: File exists' if the route has already been added.
        (subprocess.check_output(
            f"sudo ip route add {MulticastHelper.ADDRESS}/32 dev eth0 || true",
            shell = True,
            executable = '/usr/bin/bash',
            stderr = subprocess.STDOUT
        ))

        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__do_housekeeping(for_end_of_video = False)
        self.__register_signal_handlers()

    def broadcast(self):
        attempt = 1
        max_attempts = 2
        while attempt <= max_attempts:
            try:
                self.__broadcast_internal()
                break
            except YoutubeDlException as e:
                if attempt < max_attempts:
                    self.__logger.warning("Caught exception in VideoBroadcaster.__broadcast_internal: " +
                        traceback.format_exc())
                    self.__logger.warning("Updating youtube-dl and retrying broadcast...")
                    self.__update_youtube_dl()
                if attempt >= max_attempts:
                    raise e
            finally:
                self.__do_housekeeping(for_end_of_video = True)
            attempt += 1

    def __broadcast_internal(self):
        self.__logger.info(f"Starting broadcast for: {self.__video_url}")
        if self.__show_loading_screen:
            LoadingScreenHelper().send_loading_screen_signal(Logger.get_uuid())

        """
        What's going on here? We invoke youtube-dl (ytdl) twice in the broadcast code:
        1) To download the proper video format (which generally does not have sound included) and mux it with (2)
        2) To download the best audio quality

        Ytdl takes couple of seconds to be invoked. Luckily, (1) and (2) happen in parallel
        (see self.__get_ffmpeg_input_clause_and_video_dimensions_pipeline).

        Originally, a single pipeline was responsible for downloading, converting, and broadcasting the video.
        Video dimensions were calculated separately, outside of this single pipeline.

        Now we have two pipelines that we start separately:
        1) download_and_convert_video_proc, which downloads the video, calculates the video dimensions, and
            converts / muxes the video to the proper format.
        2) video_broadcast_proc, which broadcasts the converted video

        We connect the stdout of proc 1 to the stdin of proc 2.

        In order to calculate the video dimensions inline with the rest of the video pipeline, we had to break up
        the original single pipeline into these two halves, because broadcasting the video requires having started the
        receivers first. And starting the receivers requires knowing how much to crop, which requires knowing the
        video dimensions. Thus, we need to know the video dimensions before broadcasting the video. Without breaking
        up the pipeline, we wouldn't be able to enforce that we don't start broadcasting the video before knowing the
        dimensions.

        So what happens is:
        1) The download_and_convert_video_proc starts. The ffmpeg conversion and muxing part of this pipeline is
            actually blocked by calculating the video dimensions first and writing them to a FIFO file.
        2) Whenever the dimensions are calculated and written to the FIFO, the ffmpeg conversion and muxing part
            of the pipeline is unblocked. Simultaneously, the videobroadcaster will read the dimensions from the
            FIFO.
        3) The videobroadcaster starts the receivers, and tells them the video dimensions.
        4) The videobroadcaster starts the video_broadcast_proc, which broadcasts the converted video
        """
        download_and_convert_video_proc = self.start_download_and_convert_video_proc()
        self.__start_receivers()

        """
        This `sleep` makes the videos more likely to start in-sync across all the TVs, but I'm not totally
        sure why. My current theory is that this give the receivers enough time to start before the broadcast
        command starts sending its data.

        Another potential solution is making use of delay_buffer in video_broadcast_cmd, although I have
        abandoned that approach for now: https://gist.github.com/dasl-/9ed9d160384a8dd77382ce6a07c43eb6

        Another thing I tried was only sending the data once a few megabytes have been read, in case it was a
        problem with the first few megabytes of the video being downloaded slowly, but this approach resulted in
        occasional very brief video artifacts (green screen, etc) within the first 30 seconds or so of playback:
        https://gist.github.com/dasl-/f3fcc941e276d116320d6fa9e4de25de

        And another thing I tried is starting the receivers early without any crop args to the invocation of
        omxplayer. I would only send the crop args later via dbus. This allowed me to get rid of the sleep
        below. I wasn't 100%, but it may have made things *slightly* less likely to start in sync. Hard to
        know. Very rarely, you would see the crop change at the very start of the video if it couldn't complete
        the dbus message before the video started playing. See the approach here:
        https://gist.github.com/dasl-/db3ce584ba90802ba390ac0f07611dea

        See data collected on the effectiveness of this sleep:
        https://gist.github.com/dasl-/e5c05bf89c7a92d43881a2ff978dc889
        """
        time.sleep(2)
        video_broadcast_proc = self.__start_video_broadcast_proc(download_and_convert_video_proc)

        self.__logger.info("Waiting for download_and_convert_video and video_broadcast procs to end...")
        has_download_and_convert_video_proc_ended = False
        has_video_broadcast_proc_ended = False
        while True: # Wait for the download_and_convert_video and video_broadcast procs to end...
            if not has_download_and_convert_video_proc_ended and download_and_convert_video_proc.poll() is not None:
                has_download_and_convert_video_proc_ended = True
                if download_and_convert_video_proc.returncode != 0:
                    raise YoutubeDlException("The download_and_convert_video process exited non-zero: " +
                        f"{download_and_convert_video_proc.returncode}. This could mean an issue with youtube-dl; " +
                        "it may require updating.")
                self.__logger.info("The download_and_convert_video proc ended.")

            if not has_video_broadcast_proc_ended and video_broadcast_proc.poll() is not None:
                has_video_broadcast_proc_ended = True
                if video_broadcast_proc.returncode != 0:
                    raise Exception(f"The video broadcast process exited non-zero: {video_broadcast_proc.returncode}")
                self.__logger.info("The video_broadcast proc ended.")

            if has_download_and_convert_video_proc_ended and has_video_broadcast_proc_ended:
                break

            time.sleep(0.1)

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

    This command also includes a pipeline to calculate video dimensions inline with the video download.
    """
    def start_download_and_convert_video_proc(self, ytdl_video_format = None):
        if self.__get_video_url_type() == self.__VIDEO_URL_TYPE_LOCAL_FILE:
            cmd = f"< {shlex.quote(self.__video_url)} {self.__get_video_dimensions_pipeline_cmd()}"
        else:
            # Mix the best audio with the video and send via multicast
            # See: https://github.com/dasl-/piwall2/blob/main/docs/best_video_container_format_for_streaming.adoc
            # See: https://github.com/dasl-/piwall2/blob/main/docs/streaming_high_quality_videos_from_youtube-dl_to_stdout.adoc
            ffmpeg_input_clause = self.__get_ffmpeg_input_clause_and_video_dimensions_pipeline(ytdl_video_format)
            # TODO: can we use mp3 instead of mp2?
            cmd = (f"set -o pipefail && export SHELLOPTS && {self.__get_standard_ffmpeg_cmd()} {ffmpeg_input_clause} " +
                "-c:v copy -c:a mp2 -b:a 192k -f mpegts -")
        self.__logger.info(f"Running download_and_convert_video_proc command: {cmd}")

        # Info on start_new_session: https://gist.github.com/dasl-/1379cc91fb8739efa5b9414f35101f5f
        # Allows killing all processes (subshells, children, grandchildren, etc as a group)
        download_and_convert_video_proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True, stdout = subprocess.PIPE
        )
        self.__download_and_convert_video_proc_pgid = os.getpgid(download_and_convert_video_proc.pid)
        return download_and_convert_video_proc

    def __start_video_broadcast_proc(self, download_and_convert_video_proc):
        # See: https://github.com/dasl-/piwall2/blob/main/docs/controlling_video_broadcast_speed.adoc
        mbuffer_size = round(Receiver.VIDEO_PLAYBACK_MBUFFER_SIZE_BYTES / 2)
        burst_throttling_clause = (f'mbuffer -q -l /tmp/mbuffer-broadcast.out -m {mbuffer_size}b | ' +
            f'{self.__get_standard_ffmpeg_cmd()} -re -i pipe:0 -c:v copy -c:a copy -f mpegts - >/dev/null ; ' +
            f'touch {self.__VIDEO_PLAYBACK_DONE_FILE}')
        broadcasting_clause = (f"{DirectoryUtils().root_dir}/bin/msend_video " +
            f'--log-uuid {shlex.quote(Logger.get_uuid())} ' +
            f'--end-of-video-magic-bytes {self.END_OF_VIDEO_MAGIC_BYTES.decode()}')

        # Mix the best audio with the video and send via multicast
        # See: https://github.com/dasl-/piwall2/blob/main/docs/best_video_container_format_for_streaming.adoc
        #
        # Use `pv` to rate limit how fast we send the video. This is especially important when playing back
        # local files. Without `pv`, they may send as fast as network bandwidth permits, which would prevent
        # control messages from being received in a timely manner. Without `pv` here, when playing local files,
        # we observed that a control message could be sent over the network and received ~10 seconds later --
        # a delay because the tubes were clogged.
        video_broadcast_cmd = ("set -o pipefail && export SHELLOPTS && " +
            f"pv --rate-limit 4M | tee >({burst_throttling_clause}) >({broadcasting_clause}) >/dev/null")
        self.__logger.info(f"Running broadcast command: {video_broadcast_cmd}")

        # Info on start_new_session: https://gist.github.com/dasl-/1379cc91fb8739efa5b9414f35101f5f
        # Allows killing all processes (subshells, children, grandchildren, etc as a group)
        video_broadcast_proc = subprocess.Popen(
            video_broadcast_cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True,
            stdin = download_and_convert_video_proc.stdout
        )
        self.__video_broadcast_proc_pgid = os.getpgid(video_broadcast_proc.pid)
        return video_broadcast_proc

    def __start_receivers(self):
        video_dimensions = self.__read_dimensions_from_fifo()
        msg = {
            'log_uuid': Logger.get_uuid(),
            'video_width': video_dimensions[0],
            'video_height': video_dimensions[1],
        }
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_INIT_VIDEO, msg)
        self.__logger.info(f"Sent {ControlMessageHelper.TYPE_INIT_VIDEO} control message.")

    def __get_standard_ffmpeg_cmd(self):
        # unfortunately there's no way to make ffmpeg output its stats progress stuff with line breaks
        log_opts = '-nostats '
        if sys.stderr.isatty():
            log_opts = '-stats '

        if Logger.get_level() <= Logger.DEBUG:
            pass # don't change anything, ffmpeg is pretty verbose by default
        else:
            log_opts += '-loglevel error'

        # Note: don't use ffmpeg's `-xerror` flag:
        # https://gist.github.com/dasl-/1ad012f55f33f14b44393960f66c6b00
        return f"ffmpeg -hide_banner {log_opts} "

    def __get_ffmpeg_input_clause_and_video_dimensions_pipeline(self, ytdl_video_format):
        video_url_type = self.__get_video_url_type()
        if video_url_type is not self.__VIDEO_URL_TYPE_YOUTUBE:
            raise Exception(f'Unexpected video_url_type: {video_url_type}.')

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
        youtube_dl_cmd_template = ("mkdir -p {0} && cd {0} && yt-dlp {1} --retries infinite --format {2} --output - {3} {4} | " +
            "mbuffer -q -Q -m {5}b")

        log_opts = '--no-progress'
        if Logger.get_level() <= Logger.DEBUG:
            log_opts = '' # show video download progress
        if not sys.stderr.isatty():
            log_opts += ' --newline'

        if not ytdl_video_format:
            ytdl_video_format = self.__config_loader.get_youtube_dl_video_format()

        use_extractors = ''
        if self.__yt_dlp_extractors is not None:
            use_extractors = f'--use-extractors {shlex.quote(self.__yt_dlp_extractors)}'

        # 50 MB. Based on one video, 1080p avc1 video consumes about 0.36 MB/s. So this should
        # be enough buffer for ~139s
        video_buffer_size = 1024 * 1024 * 50
        youtube_dl_video_cmd = youtube_dl_cmd_template.format(
            shlex.quote(self.__VIDEO_TMP_DIR),
            shlex.quote(self.__video_url),
            shlex.quote(ytdl_video_format),
            log_opts,
            use_extractors,
            video_buffer_size
        )

        youtube_dl_video_cmd_with_dimensions_calculation = youtube_dl_video_cmd + ' | ' + self.__get_video_dimensions_pipeline_cmd()

        # 5 MB. Based on one video, audio consumes about 0.016 MB/s. So this should
        # be enough buffer for ~312s
        audio_buffer_size = 1024 * 1024 * 5
        youtube_dl_audio_cmd = youtube_dl_cmd_template.format(
            shlex.quote(self.__AUDIO_TMP_DIR),
            shlex.quote(self.__video_url),
            shlex.quote(self.__AUDIO_FORMAT),
            log_opts,
            use_extractors,
            audio_buffer_size
        )

        return f"-i <({youtube_dl_video_cmd_with_dimensions_calculation}) -i <({youtube_dl_audio_cmd})"

    def __get_video_dimensions_pipeline_cmd(self):
        self.__dimensions_fifo_name = self.__make_fifo(additional_prefix = 'dimensions')

        # Explanation of the video dimensions extraction pipeline:
        #
        # cat - >/dev/null: Prevent tee from exiting uncleanly (SIGPIPE) after ffprobe has finished probing.
        #
        # mbuffer: use mbuffer so that writes in either half of the tee are not blocked by shell pipeline backpressure.
        # Specifically, ffprobe_mbuffer1 ensures that if ffprobe_cmd is slow to read input, that writing to the stdout
        # half of the tee will not be blocked. The stdout of the tee is eventually piped to ffmpeg, which
        # muxes and converts the video. So we ensure this is not blocked by a slow ffprobe. Likewise, ffprobe_mbuffer2
        # ensures that if the downstream ffmpeg half of the pipeline is slow to read input, that writing to ffprobe
        # will not be blocked.
        #
        # Note: ffprobe may need to read a number of bytes proportional to the video size, thus there may
        # be no buffer size that works for all videos (see: https://stackoverflow.com/a/70707003/627663 )
        # But our current buffer size works for videos that are ~24 hours long, so it's good enough in
        # most cases. Something fails for videos that are 100h+ long, but I believe it's unrelated to
        # mbuffer size -- those videos failed even with our old model of calculating dimensions separately from
        # the video playback pipeline. See: https://github.com/yt-dlp/yt-dlp/issues/3390
        ffprobe_cmd = f'ffprobe -v 0 -of csv=p=0 -select_streams v:0 -show_entries stream=width,height - > {self.__dimensions_fifo_name}'
        ffprobe_mbuffer1 = f'mbuffer -q -l /tmp/mbuffer-ffprobe1.out -m {1024 * 1024 * 50}b'
        ffprobe_mbuffer2 = f'mbuffer -q -l /tmp/mbuffer-ffprobe2.out -m {1024 * 1024 * 50}b'
        dimensions_cmd = f'tee >( {ffprobe_mbuffer1} | {{ {ffprobe_cmd} && cat - >/dev/null ; }} ) | {ffprobe_mbuffer2} '

        return dimensions_cmd

    def __read_dimensions_from_fifo(self):
        dimensions = None
        try:
            dimensions_fifo = open(self.__dimensions_fifo_name, 'r')
            # Need to call .read() rather than .readline() because in some cases, the output could
            # contain multiple lines. We're only interested in the first line. Closing the fifo
            # after only reading the first line when it has multi-line output would result in
            # SIGPIPE errors
            dimensions = list(map(int, dimensions_fifo.read().splitlines()[0].strip().split(',')))
            dimensions_fifo.close()
        except Exception as ex:
            if self.__config_loader.is_any_receiver_dual_video_output():
                dimensions = [1280, 720]
            else:
                dimensions = [1920, 1080]

            self.__logger.error("Got an error determining the dimensions: " + str(ex))
            self.__logger.error(f"Assuming dimensions are {dimensions} for this video.")

        self.__logger.info(f'Calculated video dimensions: {dimensions}')

        if self.__config_loader.is_any_receiver_dual_video_output() and dimensions[1] > 720:
            raise Exception("This video's resolution is too high for a dual output receiver: " +
                f"({dimensions[1]} is greater than 720p).")

        return dimensions

    def __get_video_url_type(self):
        if self.__video_url.startswith('http://') or self.__video_url.startswith('https://'):
            return self.__VIDEO_URL_TYPE_YOUTUBE
        else:
            return self.__VIDEO_URL_TYPE_LOCAL_FILE

    def __make_fifo(self, additional_prefix = None):
        prefix = self.__FIFO_PREFIX + '__'
        if additional_prefix:
            prefix += additional_prefix + '__'

        make_fifo_cmd = (
            'fifo_name=$(mktemp --tmpdir={} --dry-run {}) && mkfifo -m 600 "$fifo_name" && printf $fifo_name'
            .format(
                tempfile.gettempdir(),
                prefix + 'XXXXXXXXXX'
            )
        )
        self.__logger.info('Making fifo...')
        fifo_name = (subprocess
            .check_output(make_fifo_cmd, shell = True, executable = '/usr/bin/bash')
            .decode("utf-8"))
        return fifo_name

    def __update_youtube_dl(self):
        update_youtube_dl_output = (subprocess
            .check_output(
                'sudo ' + DirectoryUtils().root_dir + '/utils/update_youtube-dl.sh',
                shell = True,
                executable = '/usr/bin/bash',
                stderr = subprocess.STDOUT
            )
            .decode("utf-8"))
        self.__logger.info("Update youtube-dl output: {}".format(update_youtube_dl_output))

    # for_end_of_video: whether we are doing housekeeping before or after playing a video
    def __do_housekeeping(self, for_end_of_video):
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
                f"{self.__video_broadcast_proc_pgid})...")
            try:
                os.killpg(self.__video_broadcast_proc_pgid, signal.SIGTERM)
            except Exception:
                # might raise: `ProcessLookupError: [Errno 3] No such process`
                pass
        if for_end_of_video:
            # sending a skip signal at the beginning of a video could skip the loading screen
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SKIP_VIDEO, {})

        self.__logger.info(f"Deleting fifos, temp dirs, and {self.__VIDEO_PLAYBACK_DONE_FILE} ...")
        fifos_path_glob = shlex.quote(tempfile.gettempdir() + "/" + self.__FIFO_PREFIX) + '*'
        cleanup_files_cmd = f'sudo rm -rf {fifos_path_glob} {self.__VIDEO_PLAYBACK_DONE_FILE} {self.__VIDEO_TMP_DIR} {self.__AUDIO_TMP_DIR}'
        subprocess.check_output(cleanup_files_cmd, shell = True, executable = '/usr/bin/bash')

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
        self.__do_housekeeping(for_end_of_video = True)
        sys.exit(sig)
