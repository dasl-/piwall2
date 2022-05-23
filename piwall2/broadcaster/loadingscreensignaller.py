import random

from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper

class LoadingScreenSignaller:

    def __init__(self):
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__config_loader = ConfigLoader()

    def send_loading_screen_signal(self, log_uuid):
        msg = {
            'log_uuid': log_uuid,
            'loading_screen_data': self.__choose_random_loading_screen()
        }
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_SHOW_LOADING_SCREEN, msg)

    def __choose_random_loading_screen(self):
        loading_screens_config = self.__config_loader.get_raw_config()['loading_screens']
        if self.__config_loader.is_any_receiver_dual_video_output():
            options = loading_screens_config['720p']
        else:
            options = loading_screens_config['1080p']
        loading_screen_data = random.choice(list(options.values()))
        return loading_screen_data
