import shlex
import subprocess

class Broadcaster:

    MULTICAST_ADDRESS = '239.0.1.23'
    MULTICAST_PORT = 1234

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
                "-c:v copy -c:a aac -f matroska 'udp://239.0.1.23:1234?localaddr=$eth0_ip'"
        )
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True
        )
