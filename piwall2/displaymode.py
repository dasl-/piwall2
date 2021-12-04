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
    # Updating the DB can be slow -- occasionally it takes ~2 seconds because the SD cards
    # can be slow randomly. So don't do it too often. Hence the `should_update_db` parameter.
    def set_display_mode(self, display_mode_by_tv_id, should_update_db = True):
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, display_mode_by_tv_id)

        if not should_update_db:
            return True

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

    # TODO: use SettingsDb.toggle_multi once we have a version of sqlite that supports the `returning` clause
    # See: SettingsDb.toggle_multi
    def toggle_display_mode(self, tv_ids):
        db_keys = []
        for tv_id in tv_ids:
            db_keys.append(self.__settings_db.make_tv_key_for_setting(
                piwall2.broadcaster.settingsdb.SettingsDb.SETTING_DISPLAY_MODE,
                tv_id
            ))

        old_display_modes = self.__settings_db.get_multi(db_keys, self.DEFAULT_DISPLAY_MODE)
        new_display_modes_for_db = {}
        new_display_mode_by_tv_id = {}
        for key, old_display_mode in old_display_modes.items():
            if old_display_mode == self.DISPLAY_MODE_TILE:
                new_display_mode = self.DISPLAY_MODE_REPEAT
            else:
                new_display_mode = self.DISPLAY_MODE_TILE
            new_display_modes_for_db[key] = new_display_mode

            tv_id = self.__settings_db.get_tv_id_from_settings_key(key)
            new_display_mode_by_tv_id[tv_id] = new_display_mode

        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, new_display_mode_by_tv_id)
        return self.__settings_db.set_multi(new_display_modes_for_db)
