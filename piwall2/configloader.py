import toml
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger

class ConfigLoader:

    __RECEIVERS_CONFIG_FILE_NAME = 'receivers.toml'

    def __init__(self, load = True):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__receivers_config = None
        self.__receivers = []
        self.__wall_width = None
        self.__wall_height = None
        self.__youtube_dl_video_format = None
        self.__is_loaded = False
        if load:
            self.load_config_if_not_loaded()

    def get_receivers_config(self):
        return self.__receivers_config

    def get_receivers_list(self):
        return self.__receivers

    def get_wall_width(self):
        return self.__wall_width

    def get_wall_height(self):
        return self.__wall_height

    # youtube-dl video format depends on whether any receiver has dual video output
    # see: https://github.com/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#one-vs-two-tvs-per-receiver-raspberry-pi
    def get_youtube_dl_video_format(self):
        return self.__youtube_dl_video_format

    def get_receivers_config_path(self):
        return DirectoryUtils().root_dir + '/' + self.__RECEIVERS_CONFIG_FILE_NAME

    def load_config_if_not_loaded(self):
        if self.__is_loaded:
            return

        config_path = self.get_receivers_config_path()
        self.__logger.info(f"Loading piwall2 config from: {config_path}.")
        raw_config = toml.load(config_path)
        self.__logger.info(f"Validating piwall2 config: {raw_config}")

        is_any_receiver_dual_video_out = False
        receivers = []
        receivers_config = {}

        # The wall width and height will be computed based on the configuration measurements of each receiver.
        wall_width = None
        wall_height = None
        for receiver, receiver_config in raw_config.items():
            is_this_receiver_dual_video_out = False
            for key in receiver_config:
                if key.endswith('2'):
                    is_this_receiver_dual_video_out = True
                    is_any_receiver_dual_video_out = True
                    break

            self.__assert_receiver_config_valid(receiver, receiver_config, is_this_receiver_dual_video_out)

            receiver_config['is_dual_video_output'] = is_this_receiver_dual_video_out

            wall_width_at_this_receiver = receiver_config['x'] + receiver_config['width']
            wall_height_at_this_receiver = receiver_config['y'] + receiver_config['height']
            if wall_width is None or wall_width < wall_width_at_this_receiver:
                wall_width = wall_width_at_this_receiver
            if wall_height is None or wall_height < wall_height_at_this_receiver:
                wall_height = wall_height_at_this_receiver

            receivers.append(receiver)
            receivers_config[receiver] = receiver_config

        self.__receivers_config = receivers_config
        self.__receivers = receivers
        self.__logger.info(f"Found receivers: {self.__receivers} and config: {self.__receivers_config}")

        self.__wall_width = wall_width
        self.__wall_height = wall_height
        self.__logger.info(f"Computed wall dimensions: {self.__wall_width}x{self.__wall_height}.")

        if is_any_receiver_dual_video_out:
            self.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=720]'
        else:
            self.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=1080]'
        self.__logger.info(f"Using youtube-dl video format: {self.__youtube_dl_video_format}")

        self.__is_loaded = True

    def __assert_receiver_config_valid(self, receiver, receiver_config, is_this_receiver_dual_video_out):
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
