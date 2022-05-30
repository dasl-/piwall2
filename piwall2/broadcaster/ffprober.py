import shlex
import subprocess

class Ffprober:

    def get_video_metadata(self, video_path, fields):
        # TODO: guard against unsupported video formats
        fields_str = shlex.quote(','.join(fields))
        ffprobe_cmd = ('ffprobe -hide_banner -v 0 -of csv=p=0 -select_streams v:0 -show_entries ' +
            f'stream={fields_str} {shlex.quote(video_path)}')
        ffprobe_output = (subprocess
            .check_output(ffprobe_cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT)
            .decode("utf-8"))
        ffprobe_output = ffprobe_output.split('\n')[0]
        ffprobe_parts = ffprobe_output.split(',')

        metadata = {}
        for i in range(len(fields)):
            metadata[fields[i]] = ffprobe_parts[i]
        return metadata
