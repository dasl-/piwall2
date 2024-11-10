import hashlib
import json
import os
import random

from piwall2.broadcaster.ffprober import Ffprober
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

    # Returns a dict with the keys: video_path, width, height
    def __choose_random_loading_screen(self):
        if ConfigLoader().is_any_receiver_dual_video_output():
            options = LoadingScreenHelper.__loading_screen_videos['720p']
        else:
            options = LoadingScreenHelper.__loading_screen_videos['all']
        if options:
            loading_screen_data = random.choice(options)
        else:
            loading_screen_data = None
        return loading_screen_data

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
        path_prefix = DirectoryUtils().root_dir + '/assets/loading_screens/'
        LoadingScreenHelper.__loading_screen_videos = {
            'all': [],
            '720p': [],
        }
        for loading_screen_metadata in loading_screen_config:
            video_path = path_prefix + loading_screen_metadata['video_file']
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
