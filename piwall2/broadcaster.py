import shlex
import subprocess
import time
import socket

class Broadcaster:

    MULTICAST_ADDRESS = '239.0.1.23'
    MULTICAST_PORT = 1234

    # regarding socket.IP_MULTICAST_TTL
    # ---------------------------------
    # for all packets sent, after two hops on the network the packet will not
    # be re-sent/broadcast (see https://www.tldp.org/HOWTO/Multicast-HOWTO-6.html)
    MULTICAST_TTL = 2

    END_OF_VIDEO_MAGIC_BYTES = b'PIWALL2_END_OF_VIDEO_MAGIC_BYTES'

    def __init__(self):
        pass

    def broadcast(self, video_url):
        cmd = (
            # Get eth0 IP
            "eth0_ip=$(ip -json -pretty addr show eth0 | jq -c --raw-output '.[] | " +
                "select(.ifname != null) | select(.ifname | contains(\"eth0\")) | .addr_info | .[] | " +
                "select(.family == \"inet\") | .local') ; " +

            # Mix the best audio with the video and send via multicast
            "ffmpeg -re " +
                f"-i <(youtube-dl {shlex.quote(video_url)} -f 'bestvideo[vcodec^=avc1][height<=720]' -o -) " +
                f"-i <(youtube-dl {shlex.quote(video_url)} -f 'bestaudio' -o -) " +
                f"-c:v copy -c:a aac -f matroska \"udp://{self.MULTICAST_ADDRESS}:{self.MULTICAST_PORT}?localaddr=$eth0_ip\""
        )
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )

        while proc.poll() is None:
            time.sleep(0.1)

        print("DONE!")
        print("DONE!")
        print("DONE!")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.bind(('192.168.1.7', 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.MULTICAST_TTL)

        # For Python 3, change next line to 'sock.sendto(b"robot", ...' to avoid the
        # "bytes-like object is required" msg (https://stackoverflow.com/a/42612820)
        sock.sendto(self.END_OF_VIDEO_MAGIC_BYTES, (self.MULTICAST_ADDRESS, self.MULTICAST_PORT))
