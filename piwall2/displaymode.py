import piwall2.broadcaster.settingsdb

class DisplayMode:
    
    # Tile mode is like this: https://i.imgur.com/BBrA1Cr.png
    # Repeat mode is like this: https://i.imgur.com/cpS61s8.png
    DISPLAY_MODE_TILE = 'DISPLAY_MODE_TILE'
    DISPLAY_MODE_REPEAT = 'DISPLAY_MODE_REPEAT'    
    DISPLAY_MODES = (DISPLAY_MODE_TILE, DISPLAY_MODE_REPEAT)

    def __init__(self):
        self.__settings_db = piwall2.broadcaster.settingsdb.SettingsDb()

    # store display_mode settings in DB
    def update_db(self, display_mode_by_tv_id):
        db_data = {}
        for tv_id, display_mode in display_mode_by_tv_id.items():
            db_key = self.__settings_db.make_tv_key_for_setting(
                piwall2.broadcaster.settingsdb.SettingsDb.SETTING_DISPLAY_MODE,
                tv_id
            )
            db_data[db_key] = display_mode
        success = self.__settings_db.set_multi(db_data)
        return success
