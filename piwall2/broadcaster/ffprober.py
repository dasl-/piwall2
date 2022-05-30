import json
import shlex
import subprocess

class Ffprober:

    def get_video_metadata(self, video_path, fields):
        # TODO: guard against unsupported video formats
        fields_str = shlex.quote(','.join(fields))
        ffprobe_cmd = ('ffprobe -hide_banner -v 0 -select_streams v:0 -show_entries ' +
            f'stream={fields_str} -print_format json {shlex.quote(video_path)}')
        ffprobe_output = (subprocess
            .check_output(ffprobe_cmd, shell = True, executable = '/usr/bin/bash', stderr = subprocess.STDOUT)
            .decode("utf-8"))

        ffprobe_data = json.loads(ffprobe_output)

        # Not sure if I should always expect the data in both places ('streams' vs 'programs' key), so be
        # defensive and check both.
        if 'streams' in ffprobe_data and fields[0] in ffprobe_data['streams'][0]:
            return ffprobe_data['streams'][0]
        else:
            return ffprobe_data['programs'][0]['streams'][0]
