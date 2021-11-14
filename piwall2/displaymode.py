import piwall2.broadcaster.settingsdb
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper

class DisplayMode:
    
    # Tile mode is like this: https://i.imgur.com/BBrA1Cr.png
    # Repeat mode is like this: https://i.imgur.com/cpS61s8.png
    DISPLAY_MODE_TILE = 'DISPLAY_MODE_TILE'
    DISPLAY_MODE_REPEAT = 'DISPLAY_MODE_REPEAT'    
    DISPLAY_MODES = (DISPLAY_MODE_TILE, DISPLAY_MODE_REPEAT)
    DEFAULT_DISPLAY_MODE = DISPLAY_MODE_TILE

    def __init__(self):
        self.__settings_db = piwall2.broadcaster.settingsdb.SettingsDb()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__config_loader = ConfigLoader()

    # send display_mode control message to receivers and update DB
    def set_display_mode(self, display_mode_by_tv_id):
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, display_mode_by_tv_id)

        db_data = {}
        for tv_id, display_mode in display_mode_by_tv_id.items():
            db_key = self.__settings_db.make_tv_key_for_setting(
                piwall2.broadcaster.settingsdb.SettingsDb.SETTING_DISPLAY_MODE,
                tv_id
            )
            db_data[db_key] = display_mode
        success = self.__settings_db.set_multi(db_data)
        return success

    def get_display_mode_by_tv_id(self):
        tv_ids = self.__config_loader.get_tv_ids_list()
        display_mode_settings_keys = []
        for tv_id in tv_ids:
            display_mode_settings_key = self.__settings_db.make_tv_key_for_setting(
                piwall2.broadcaster.settingsdb.SettingsDb.SETTING_DISPLAY_MODE, tv_id)
            display_mode_settings_keys.append(display_mode_settings_key)

        display_mode_settings = self.__settings_db.get_multi(
            display_mode_settings_keys, self.DEFAULT_DISPLAY_MODE)
        display_mode_by_tv_id = {}
        for key, display_mode in display_mode_settings.items():
            tv_id = self.__settings_db.get_tv_id_from_settings_key(key)
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id
