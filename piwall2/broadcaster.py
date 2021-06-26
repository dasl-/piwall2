import shlex
import subprocess
import time
import random
import string
import socket
import traceback
import youtube_dl
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.piwall2configloader import Piwall2ConfigLoader
from piwall2.parallelrunner import ParallelRunner

class Broadcaster:

    MULTICAST_ADDRESS = '239.0.1.23'
    MULTICAST_PORT = 1234

    # For passwordless ssh from the broadcaster to the receivers.
    # See: https://github.com/dasl-/piwall2/blob/main/utils/setup_broadcaster_ssh
    SSH_KEY_PATH = '/home/pi/.ssh/piwall2_broadcaster/id_ed25519'

    # regarding socket.IP_MULTICAST_TTL
    # ---------------------------------
    # for all packets sent, after two hops on the network the packet will not
    # be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
    MULTICAST_TTL = 2

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'

    __config = None
    __receivers = None
    __logger = None
    __eth0_ip_addr = None
    __youtube_dl_video_format = None

    # Metadata about the video we are using, such as title, resolution, file extension, etc
    # Access should go through self.__get_video_info() to populate it lazily
    __video_info = None
    __video_url = None

    def __init__(self, video_url):
        log_namespace_unique_id = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))
        self.__logger = Logger().set_namespace(self.__class__.__name__ + "__" + log_namespace_unique_id)
        self.__populateConfigAndYoutubeDlFormat()
        self.__eth0_ip_addr = self.__get_eth0_ip_addr()
        config_loader = Piwall2ConfigLoader()
        self.__config = config_loader.get_config()
        self.__receivers = config_loader.get_receivers()
        self.__youtube_dl_video_format = config_loader.get_youtube_dl_video_format()
        self.__video_url = video_url

    def __get_eth0_ip_addr(self):
        cmd = ("ip -json -pretty addr show eth0 | jq -c --raw-output '.[] | " +
            "select(.ifname != null) | select(.ifname | contains(\"eth0\")) | .addr_info | .[] | " +
            "select(.family == \"inet\") | .local'")
        return (subprocess.check_output(cmd, shell = True, executable = '/usr/bin/bash').decode("utf-8"))

    def broadcast(self):
        self.__logger.info(f"Starting broadcast for: {self.__video_url}")
        receivers_proc = self.__start_receivers()

        # Mix the best audio with the video and send via multicast
        cmd = ("ffmpeg -re " +
            f"-i <(youtube-dl {shlex.quote(self.__video_url)} -f 'bestvideo[vcodec^=avc1][height<=720]' -o -) " +
            f"-i <(youtube-dl {shlex.quote(self.__video_url)} -f 'bestaudio' -o -) " +
            "-c:v copy -c:a aac -f matroska " +
            f"\"udp://{self.MULTICAST_ADDRESS}:{self.MULTICAST_PORT}?localaddr={self.__eth0_ip_addr}\"")
        self.__logger.info(f"Running broadcast command: {cmd}")
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )

        self.__logger.info("Waiting for broadcast to end...")
        while proc.poll() is None:
            time.sleep(0.1)

        self.__logger.info("Sending end of video magic bytes to receivers...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.bind((self.__eth0_ip_addr, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.MULTICAST_TTL)

        # For Python 3, change next line to 'sock.sendto(b"robot", ...' to avoid the
        # "bytes-like object is required" msg (https://stackoverflow.com/a/42612820)
        sock.sendto(self.END_OF_VIDEO_MAGIC_BYTES, (self.MULTICAST_ADDRESS, self.MULTICAST_PORT))

        receivers_proc.wait()

    def __start_receivers(self):
        video_width = self.__get_video_info()['width']
        video_height = self.__get_video_info()['height']
        ssh_opts = (
            "-o ConnectTimeout=5 " +
            "-o UserKnownHostsFile=/dev/null " +
            "-o StrictHostKeyChecking=no " +
            "-o LogLevel=ERROR " +
            "-o PasswordAuthentication=no " +
            f"-o IdentityFile={shlex.quote(self.SSH_KEY_PATH)} "
        )
        cmds = []
        for receiver in self.__receivers:
            receiver_cmd = self.__get_receiver_cmd(receiver)
            cmds.append(
                f"ssh {ssh_opts} pi@receiver -- {receiver_cmd}"
            )
        return ParallelRunner().run_cmds(cmds)

    # TODO: make this actually work
    def __get_receiver_cmd(self, receiver):
        receiver_config = self.__config[receiver]
        if receiver == 'piwall2.local':
            return "/home/pi/piwall2/receive --command \"tee >(omxplayer --crop '640,360,1120,720' -o hdmi0 --display 2 --no-keys --threshold 3 pipe:0) >(omxplayer --crop '640,0,1120,360' -o hdmi1 --display 7 --no-keys --threshold 3 pipe:0) >/dev/null\""
        if receiver == 'piwall3.local':
            return "/home/pi/piwall2/receive --command \"omxplayer --crop '640,0,1120,360' -o local --no-keys --threshold 3 pipe:0\""
        if receiver == 'piwall4.local':
            return "/home/pi/piwall2/receive --command \"omxplayer --crop '640,360,1120,720' -o local --no-keys --threshold 3 --no-keys pipe:0\""

    # Lazily populate video_info from youtube. This takes a couple seconds.
    def __get_video_info(self):
        if self.__video_info:
            return self.__video_info

        self.__logger.info("Downloading and populating video metadata...")
        ydl_opts = {
            'format': self.__youtube_dl_video_format,
            'logger': Logger(),
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
                self.__video_info = ydl.extract_info(self.__url, download = False)
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
