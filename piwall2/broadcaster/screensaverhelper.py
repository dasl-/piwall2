import random

from piwall2.broadcaster.ffprober import Ffprober
from piwall2.config import Config
from piwall2.configloader import ConfigLoader
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger

class ScreensaverHelper:

    __is_loaded = False
    __screensavers = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__load_config_if_not_loaded()

    def choose_random_screensaver(self):
        if len(ScreensaverHelper.__screensavers) <= 0:
            return None
        return random.choice(ScreensaverHelper.__screensavers)

    def __load_config_if_not_loaded(self):
        if ScreensaverHelper.__is_loaded:
            return

        self.__logger.info("Loading screensaver metadata...")
        screensaver_config = Config.get('screensavers', [])
        ffprober = Ffprober()
        ScreensaverHelper.__screensavers = []
        root_dir = DirectoryUtils().root_dir
        for screensaver_metadata in screensaver_config:
            video_path = root_dir + '/' + screensaver_metadata['video_path']
            ffprobe_metadata = ffprober.get_video_metadata(video_path, ['height'])
            height = int(ffprobe_metadata['height'])
            if ConfigLoader().is_any_receiver_dual_video_output() and height > 720:
                self.__logger.warning(f'Not adding video [{video_path}] to screensavers because its resolution' +
                    f'was too high for a dual output receiver ({height} is greater than 720p).')
                continue
            ScreensaverHelper.__screensavers.append({
                'video_path': video_path,
                'height': height,
            })
        self.__logger.info("Done loading screensaver metadata.")
