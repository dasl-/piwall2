import toml
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger

class Piwall2ConfigLoader:

    __CONFIG_FILE_NAME = '.piwall2'
    __config = None
    __youtube_dl_video_format = None
    __receivers = None
    __is_loaded = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__config = None
        self.__youtube_dl_video_format = None
        self.__receivers = []
        self.__is_loaded = False
        self.__load_config_if_not_loaded()

    def get_config(self):
        return self.__config

    # youtube-dl video format depends on whether any receiver has dual video output
    # see: https://github.com/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#one-vs-two-tvs-per-receiver-raspberry-pi
    def get_youtube_dl_video_format(self):
        return self.__youtube_dl_video_format

    def get_receivers(self):
        return self.__receivers

    def __load_config_if_not_loaded(self):
        if self.__is_loaded:
            return

        config_path = DirectoryUtils().root_dir + '/' + self.__CONFIG_FILE_NAME
        self.__logger.info(f"Loading piwall2 config from: {config_path}.")
        config = toml.load(config_path)
        self.__logger.info(f"Validating piwall2 config: {config}")

        is_any_receiver_dual_video_out = False
        receivers = []
        for receiver, receiver_config in config.items():
            receivers.append(receiver)
            is_this_receiver_dual_video_out = False
            for key in receiver_config:
                if key.endswith('2'):
                    is_this_receiver_dual_video_out = True
                    is_any_receiver_dual_video_out = True
                    break
            if 'x' not in receiver_config:
                raise Exception(f"Config missing field 'x' for receiver: {receiver}.")
            if 'y' not in receiver_config:
                raise Exception(f"Config missing field 'y' for receiver: {receiver}.")
            if 'width' not in receiver_config:
                raise Exception(f"Config missing field 'width' for receiver: {receiver}.")
            if 'height' not in receiver_config:
                raise Exception(f"Config missing field 'height' for receiver: {receiver}.")
            if 'audio' not in receiver_config:
                raise Exception(f"Config missing field 'audio' for receiver: {receiver}.")
            if 'video' not in receiver_config:
                raise Exception(f"Config missing field 'video' for receiver: {receiver}.")

            if is_this_receiver_dual_video_out:
                if 'x2' not in receiver_config:
                    raise Exception(f"Config missing field 'x2' for receiver: {receiver}.")
                if 'y2' not in receiver_config:
                    raise Exception(f"Config missing field 'y2' for receiver: {receiver}.")
                if 'width2' not in receiver_config:
                    raise Exception(f"Config missing field 'width2' for receiver: {receiver}.")
                if 'height2' not in receiver_config:
                    raise Exception(f"Config missing field 'height2' for receiver: {receiver}.")
                if 'audio2' not in receiver_config:
                    raise Exception(f"Config missing field 'audio2' for receiver: {receiver}.")
                if 'video2' not in receiver_config:
                    raise Exception(f"Config missing field 'video2' for receiver: {receiver}.")

        self.__config = config
        self.__receivers = receivers

        if is_any_receiver_dual_video_out:
            self.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=720]'
        else:
            self.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=1080]'
        self.__logger.info(f"Using youtube-dl video format: {self.__youtube_dl_video_format}")
