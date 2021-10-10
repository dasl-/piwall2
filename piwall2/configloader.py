import toml
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.tv import Tv

class ConfigLoader:

    __RECEIVERS_CONFIG_FILE_NAME = 'receivers.toml'
    RECEIVERS_CONFIG_PATH = DirectoryUtils().root_dir + '/' + __RECEIVERS_CONFIG_FILE_NAME

    __is_loaded = False
    __receivers_config = None
    __receivers = None
    __tv_config = None
    __wall_width = None
    __wall_height = None
    __youtube_dl_video_format = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__load_config_if_not_loaded()

    # returns dict keyed by receiver hostname, one item per receiver, even if the receiver has two TVs.
    def get_receivers_config(self):
        return ConfigLoader.__receivers_config

    # returns a list of all the receiver hostnames
    def get_receivers_list(self):
        return ConfigLoader.__receivers

    # returns a dict that has a key 'tvs'. This key maps to a dict of TVs and their configuration, and is
    # keyed by tv_id. A single receiver may be present in the 'tvs' dict twice if it has two TVs.
    def get_tv_config(self):
        return ConfigLoader.__tv_config

    def get_tv_ids_list(self):
        return list(ConfigLoader.__tv_config['tvs'])

    def get_wall_width(self):
        return ConfigLoader.__wall_width

    def get_wall_height(self):
        return ConfigLoader.__wall_height

    # youtube-dl video format depends on whether any receiver has dual video output
    # see: https://github.zm/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#one-vs-two-tvs-per-receiver-raspberry-pi
    def get_youtube_dl_video_format(self):
        return ConfigLoader.__youtube_dl_video_format

    def __load_config_if_not_loaded(self):
        if ConfigLoader.__is_loaded:
            return

        self.__logger.info(f"Loading piwall2 config from: {self.RECEIVERS_CONFIG_PATH}.")
        raw_config = toml.load(self.RECEIVERS_CONFIG_PATH)
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

        ConfigLoader.__receivers_config = receivers_config
        ConfigLoader.__receivers = receivers
        self.__logger.info(f"Found receivers: {ConfigLoader.__receivers} and config: {ConfigLoader.__receivers_config}")

        ConfigLoader.__wall_width = wall_width
        ConfigLoader.__wall_height = wall_height
        self.__logger.info(f"Computed wall dimensions: {ConfigLoader.__wall_width}x{ConfigLoader.__wall_height}.")

        if is_any_receiver_dual_video_out:
            ConfigLoader.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=720]'
        else:
            ConfigLoader.__youtube_dl_video_format = 'bestvideo[vcodec^=avc1][height<=1080]'
        self.__logger.info(f"Using youtube-dl video format: {ConfigLoader.__youtube_dl_video_format}")

        self.__generate_tv_config()

        ConfigLoader.__is_loaded = True

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

    # Config read by the react app
    def __generate_tv_config(self):
        tvs = {}
        for receiver, cfg in ConfigLoader.__receivers_config.items():
            tv_id = Tv(receiver, 1).tv_id
            tvs[tv_id] = {
                'x': cfg['x'],
                'y': cfg['y'],
                'width': cfg['width'],
                'height': cfg['height'],
                'tv_id': tv_id,
            }
            if cfg['is_dual_video_output']:
                tv_id = Tv(receiver, 2).tv_id
                tvs[tv_id] = {
                    'x': cfg['x2'],
                    'y': cfg['y2'],
                    'width': cfg['width2'],
                    'height': cfg['height2'],
                    'tv_id': tv_id,
                }

        ConfigLoader.__tv_config = {
            'tvs': tvs,
            'wall_width': self.get_wall_width(),
            'wall_height': self.get_wall_height(),
        }
