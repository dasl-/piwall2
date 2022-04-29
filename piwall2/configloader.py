import json
import math
import socket
import subprocess
import toml

from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
from piwall2.tv import Tv

# Constructing a new instance of this class is what sets the global log level based on config settings
class ConfigLoader:

    # Keep this in sync with the CONFIG_PATH variable in the
    # install/setup_broadcaster_and_receivers script.
    CONFIG_PATH = DirectoryUtils().root_dir + '/config.toml'

    DUAL_VIDEO_OUTPUT_YTDL_VIDEO_FORMAT = 'bestvideo[vcodec^=avc1][height<=720]'
    SINGLE_VIDEO_OUTPUT_YTDL_VIDEO_FORMAT = 'bestvideo[vcodec^=avc1][height<=1080]'

    __is_loaded = False
    __receivers_config = None
    __raw_config = None
    __receivers = None
    __tv_config = None
    __wall_width = None
    __wall_height = None
    __youtube_dl_video_format = None
    __is_any_receiver_dual_video_output = None
    __hostname = None
    __local_ip_address = None
    __wall_rows = None
    __wall_columns = None

    __APP_TV_CONFIG_FILE = DirectoryUtils().root_dir + "/app/src/tv_config.json"

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__load_config_if_not_loaded()

    # returns dict keyed by receiver hostname, one item per receiver, even if the receiver has two TVs.
    def get_receivers_config(self):
        return ConfigLoader.__receivers_config

    # returns the portion of the receivers config stanza for this host's config, i.e. the portion
    # keyed by this hostname. Returns None if no matching stanza is found. This generally only makes
    # sense to run on a receiver host.
    def get_own_receiver_config_stanza(self):
        receivers_config = self.get_receivers_config()
        if ConfigLoader.__hostname in receivers_config:
            return receivers_config[ConfigLoader.__hostname]
        elif ConfigLoader.__local_ip_address in receivers_config:
            return receivers_config[ConfigLoader.__local_ip_address]
        else:
            return None

    # returns a list of all the receiver hostnames
    def get_receivers_list(self):
        return ConfigLoader.__receivers

    def get_raw_config(self):
        return ConfigLoader.__raw_config

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

    def get_num_wall_rows(self):
        return ConfigLoader.__raw_config.get('rows', 1)

    def get_num_wall_columns(self):
        return ConfigLoader.__raw_config.get('columns', 1)

    # Returns a 0-indexed array where each element of the array is an array of tv_ids
    # e.g. [[tv_id1, tv_id2], [tv_id3, tv_id4]]
    def get_wall_rows(self):
        return ConfigLoader.__wall_rows

    # Returns a 0-indexed array where each element of the array is an array of tv_ids
    # e.g. [[tv_id1, tv_id3], [tv_id2, tv_id4]]
    def get_wall_columns(self):
        return ConfigLoader.__wall_columns

    # youtube-dl video format depends on whether any receiver has dual video output
    # see: https://github.zm/dasl-/piwall2/blob/main/docs/tv_output_options.adoc#one-vs-two-tvs-per-receiver-raspberry-pi
    def get_youtube_dl_video_format(self):
        return ConfigLoader.__youtube_dl_video_format

    def is_any_receiver_dual_video_output(self):
        return ConfigLoader.__is_any_receiver_dual_video_output

    def write_tv_config_for_web_app(self):
        tv_config_json = json.dumps(self.get_tv_config())
        file = open(self.__APP_TV_CONFIG_FILE, "w")
        file.write(tv_config_json)
        file.close()

    def __load_config_if_not_loaded(self):
        if ConfigLoader.__is_loaded:
            return

        self.__logger.info(f"Loading piwall2 config from: {self.CONFIG_PATH}.")
        raw_config = toml.load(self.CONFIG_PATH)
        self.__logger.info(f"Validating piwall2 config: {raw_config}")

        is_any_receiver_dual_video_out = False
        receivers = []
        receivers_config = {}

        # The wall width and height will be computed based on the configuration measurements of each receiver.
        wall_width = None
        wall_height = None

        if 'receivers' not in raw_config:
            raise Exception("Config is missing 'receivers' stanza.")

        for receiver, receiver_config in raw_config['receivers'].items():
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
            ConfigLoader.__youtube_dl_video_format = self.DUAL_VIDEO_OUTPUT_YTDL_VIDEO_FORMAT
        else:
            ConfigLoader.__youtube_dl_video_format = self.SINGLE_VIDEO_OUTPUT_YTDL_VIDEO_FORMAT
        self.__logger.info(f"Using youtube-dl video format: {ConfigLoader.__youtube_dl_video_format}")

        self.__generate_tv_config()
        ConfigLoader.__hostname = socket.gethostname() + ".local"
        ConfigLoader.__local_ip_address = self.__get_local_ip()
        ConfigLoader.__is_any_receiver_dual_video_output = is_any_receiver_dual_video_out
        ConfigLoader.__raw_config = raw_config
        ConfigLoader.__wall_rows, ConfigLoader.__wall_columns = self.__compute_wall_rows_and_columns()

        if 'log_level' in raw_config:
            log_level = raw_config['log_level']
            self.__logger.info(f'Setting log_level to {log_level}.')
            Logger.set_level(log_level)

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

    # returns a tuple (rows, columns). Each part of the tuple will be a 0-indexed array
    # where each element of the array is an array of tv_ids
    #
    # e.g.
    # (
    #   rows = [[tv_id1, tv_id2], [tv_id3, tv_id4]],
    #   columns = [[tv_id1, tv_id3], [tv_id2, tv_id4]]
    # )
    def __compute_wall_rows_and_columns(self):
        num_rows = self.get_num_wall_rows()
        num_columns = self.get_num_wall_columns()
        wall_width = self.get_wall_width()
        wall_height = self.get_wall_height()
        rows = [[] for i in range(num_rows)]
        columns = [[] for i in range(num_columns)]

        row_height = wall_height / num_rows
        column_width = wall_width / num_columns
        for tv_id, tv_config in self.get_tv_config()['tvs'].items():
            tv_center_x = tv_config['x'] + tv_config['width'] / 2
            tv_center_y = tv_config['y'] + tv_config['height'] / 2
            tv_row = math.floor(tv_center_y / row_height)
            tv_column = math.floor(tv_center_x / column_width)

            rows[tv_row].append(tv_id)
            columns[tv_column].append(tv_id)

        return rows, columns

    def __get_local_ip(self):
        private_ip = (subprocess
            .check_output(
                'set -o pipefail && sudo ifconfig | grep -Eo \'inet (addr:)?([0-9]*\.){3}[0-9]*\' | ' +
                'grep -Eo \'([0-9]*\.){3}[0-9]*\' | grep -v \'127.0.0.1\'',
                stderr = subprocess.STDOUT, shell = True, executable = '/usr/bin/bash'
            )
            .decode("utf-8")
            .strip()
        )
        self.__logger.info(f"This device's private IP is: {private_ip}")
        return private_ip
