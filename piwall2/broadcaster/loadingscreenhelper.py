import hashlib
import json
import os
import random
import subprocess

from piwall2.broadcaster.ffprober import Ffprober
from piwall2.cmdrunner import CmdRunner
from piwall2.config import Config
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger

class LoadingScreenHelper:

    __is_loaded = False

    """
    __loading_screen_videos format:
    {
        'all': [
            {
                video_path: 'path/to/video1',
                width: <width in pixels>,
                height: <height in pixels>,
            },
            {
                video_path: 'path/to/video2',
                width: <width in pixels>,
                height: <height in pixels>,
            },
            ...
        ]
        '720p': [
            {
                video_path: 'path/to/video1',
                width: <width in pixels>,
                height: <height in pixels>,
            },
            {
                video_path: 'path/to/video2',
                width: <width in pixels>,
                height: <height in pixels>,
            },
            ...
        ]
    }

    The key 'all' will contain all of the loading screen videos. The key '720p' will contain a subset of
    the loading screen videos: only those where height <= 720.
    """
    __loading_screen_videos = None
    __LOADING_SCREEN_DIRECTORY = DirectoryUtils().root_dir + '/assets/loading_screens'
    __LOADING_SCREEN_CACHE_PATH = DirectoryUtils().root_dir + '/loading_screen_config_cache.json'

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__load_config_if_not_loaded()

    def send_loading_screen_signal(self, log_uuid):
        loading_screen_data = self.__choose_random_loading_screen()
        if not loading_screen_data:
            return

        msg = {
            'log_uuid': log_uuid,
            'loading_screen_data': loading_screen_data
        }
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SHOW_LOADING_SCREEN, msg)

    # This method is called by setup scripts. It iterates through all loading screens in the config file.
    # For loading screen:
    #   1) check if it exists on the broadcaster. If not, throw an exception.
    #   2) check if it exists on each receiver. If not, copy it to all receivers.
    def copy_loading_screens_from_broadcaster_to_receivers(self):
        loading_screens = self.__get_loading_screen_candidates()
        cmd_runner = CmdRunner()
        for loading_screen in loading_screens:
            if not os.path.isfile(loading_screen['video_path']):
                raise Exception(f"Loading screen does not exist: {loading_screen['video_path']}")

        loading_screens_to_copy = self.__get_loading_screens_that_need_to_be_copied(loading_screens, cmd_runner)
        for loading_screen in loading_screens_to_copy:
            self.__logger.info(f"Sending loading screen to receivers: {loading_screen}")
            cmd = (DirectoryUtils().root_dir +
                f'/utils/msend_file_to_receivers --input-file {loading_screen} --output-file {loading_screen}')
            cmd_runner.run_cmd_with_realtime_output(cmd)

    # Returns a dict with the keys: video_path, width, height
    def __choose_random_loading_screen(self):
        candidates = self.__get_loading_screen_candidates()
        if candidates:
            loading_screen_data = random.choice(candidates)
        else:
            loading_screen_data = None
        return loading_screen_data

    def __get_loading_screen_candidates(self):
        if ConfigLoader().is_any_receiver_dual_video_output():
            candidates = LoadingScreenHelper.__loading_screen_videos['720p']
        else:
            candidates = LoadingScreenHelper.__loading_screen_videos['all']
        return candidates

    def __get_loading_screens_that_need_to_be_copied(self, loading_screens, cmd_runner):
        loading_screen_paths_str = ''
        for loading_screen in loading_screens:
            loading_screen_paths_str += f"{loading_screen['video_path']} "
        loading_screen_paths_str = loading_screen_paths_str.strip()

        checksum = subprocess.check_output(
            f"md5sum {loading_screen_paths_str}",
            shell = True,
            executable = '/usr/bin/bash',
            stderr = subprocess.STDOUT
        ).decode('utf-8').strip()

        cmd = f"md5sum --check --strict <( echo '{checksum}' ) 2>&1"
        return_code, stdout, stderr = cmd_runner.run_dsh(
            cmd, include_broadcaster = False, raise_on_failure = False, return_output = True
        )

        if return_code == 0:
            self.__logger.info("All loading screens already exist on receivers.")
            return []

        video_to_match_count_map = {}
        for loading_screen in loading_screens: # initialize the map
            video_to_match_count_map[loading_screen['video_path']] = 0

        for line in stdout.decode('utf-8').splitlines():
            if line.endswith(": OK"):
                # Line looks like:
                # pi@piwall9.local: /home/pi/development/piwall2/assets/loading_screens/dialup.ts: OK
                parts = line.split(':')
                video_path = parts[1].strip()
                video_to_match_count_map[video_path] += 1

        loading_screens_that_need_to_be_copied = []
        num_receivers = len(ConfigLoader().get_receivers_list())
        for video_path, match_count in video_to_match_count_map.items():
            if match_count < num_receivers:
                self.__logger.info("Loading screen needs to be copied to one or more receivers " +
                    f"(only matched on {match_count} of {num_receivers} receivers): {video_path}")
                loading_screens_that_need_to_be_copied.append(video_path)
            else:
                self.__logger.info(f"Loading screen doesn't need to be copied receivers {video_path}")
        return loading_screens_that_need_to_be_copied

    def __load_config_if_not_loaded(self):
        if LoadingScreenHelper.__is_loaded:
            return

        self.__logger.info("Loading loading screen video metadata...")
        loading_screen_config = Config.get('loading_screens', [])
        loading_screen_config_hash = hashlib.md5(json.dumps(loading_screen_config).encode('utf-8')).hexdigest()

        # Use a cache file to speed up loading the loading screen video metadata. This is because unlike other metadata
        # that we load, we cannot guarantee that we will never have to load this metadata in the broadcast
        # process, as opposed to in the queue process. Loading metadata in the queue process is fine and need not be
        # cached, because it is a long lived process, so the cost of loading metadata is a one-time cost. But loading
        # metadata in the broadcast process is "expensive" because it must be loaded with every video that
        # we play. In particular, this metadata would be loaded by the broadcast process if we passed the
        # '--show-loading-screen' flag to ./bin/broadcast.
        should_use_cache = False
        if os.path.isfile(self.__LOADING_SCREEN_CACHE_PATH):
            loading_screen_cache_file = open(self.__LOADING_SCREEN_CACHE_PATH, 'r')
            loading_screen_cache = loading_screen_cache_file.read()
            loading_screen_cache = json.loads(loading_screen_cache)
            loading_screen_cache_file.close()
            if loading_screen_cache['hash'] == loading_screen_config_hash:
                should_use_cache = True

        if should_use_cache:
            self.__logger.info("Using loading screen cache file.")
            LoadingScreenHelper.__loading_screen_videos = loading_screen_cache['loading_screens']
            return

        self.__logger.info("Not using loading screen cache file. Cache file is either invalid or does not exist.")
        ffprober = Ffprober()
        LoadingScreenHelper.__loading_screen_videos = {
            'all': [],
            '720p': [],
        }
        for loading_screen_metadata in loading_screen_config:
            video_path = self.__LOADING_SCREEN_DIRECTORY + '/' + loading_screen_metadata['video_file']
            ffprobe_metadata = ffprober.get_video_metadata(video_path, ['width', 'height'])
            this_metadata = {
                'video_path': video_path,
                'width': int(ffprobe_metadata['width']),
                'height': int(ffprobe_metadata['height']),
            }
            LoadingScreenHelper.__loading_screen_videos['all'].append(this_metadata)
            if this_metadata['height'] <= 720:
                LoadingScreenHelper.__loading_screen_videos['720p'].append(this_metadata)

        self.__logger.info("Writing loading screen cache file...")
        loading_screen_cache = {
            'loading_screens': LoadingScreenHelper.__loading_screen_videos,
            'hash': loading_screen_config_hash,
        }
        loading_screen_cache_json = json.dumps(loading_screen_cache, indent = 4)
        file = open(self.__LOADING_SCREEN_CACHE_PATH, "w")
        file.write(loading_screen_cache_json + "\n")
        os.chmod(self.__LOADING_SCREEN_CACHE_PATH, 0o777)
        file.close()
        self.__logger.info("Done loading loading screen video metadata.")
