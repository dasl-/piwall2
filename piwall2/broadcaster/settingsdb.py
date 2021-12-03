import piwall2.broadcaster.database
import piwall2.displaymode
from piwall2.configloader import ConfigLoader
from piwall2.logger import Logger

"""
Stores settings that are modifiable at runtime. They are stored in a DB
and re-read during program execution. They may be modified from a UI.
"""
class SettingsDb:

    # This is a per-TV setting.
    # Determines whether each individual TV is in tile vs repeat mode.
    # See: DisplayMode
    SETTING_DISPLAY_MODE = 'display_mode'

    # This is a global setting. See: Animator
    SETTING_ANIMATION_MODE = 'animation_mode'

    # This is a global setting.
    SETTING_YOUTUBE_API_KEY = 'youtube_api_key'

    __SETTING_TV_ID_DELIM = '__'

    def __init__(self):
        self.__cursor = piwall2.broadcaster.database.Database().get_cursor()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__config_loader = ConfigLoader()

    def construct(self):
        self.__cursor.execute("DROP TABLE IF EXISTS settings")
        self.__cursor.execute("""
            CREATE TABLE settings (
                key VARCHAR(200) PRIMARY KEY,
                value VARCHAR(200),
                create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                update_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")

    def set(self, key, value):
        self.__cursor.execute(
            ("INSERT INTO settings (key, value, update_date) VALUES(?, ?, datetime()) ON CONFLICT(key) DO " +
                "UPDATE SET value=excluded.value, update_date=excluded.update_date"),
            [key, value]
        )
        return self.__cursor.rowcount == 1

    # returns boolean success
    def set_multi(self, kv_dict):
        placeholders = ''
        params = []
        for key, value in kv_dict.items():
            placeholders += '(?, ?, datetime()),'
            params.extend([key, value])
        placeholders = placeholders.rstrip(',')

        self.__cursor.execute(
            (f"INSERT INTO settings (key, value, update_date) VALUES {placeholders} ON CONFLICT(key) DO " +
                "UPDATE SET value=excluded.value, update_date=excluded.update_date"),
            params
        )
        return self.__cursor.rowcount == len(kv_dict)

    # TODO: use RETURNING clause if we have a recent version of sqlite that supports it (>= 3.35.0)
    # https://www.sqlite.org/lang_returning.html
    def toggle_multi(self, key_list, toggle_value1, toggle_value2):
        params = [toggle_value1, toggle_value2, toggle_value1]
        placeholders = '('
        for key in key_list:
            placeholders += '?,'
            params.append(key)
        placeholders = placeholders.rstrip(',') + ')'

        self.__cursor.execute(
            (f"UPDATE settings SET value = CASE WHEN value = ? THEN ? ELSE ? END WHERE key IN {placeholders}"),
            params
        )
        return self.__cursor.rowcount == len(key_list)

    def get(self, key, default = None):
        self.__cursor.execute(
            "SELECT value FROM settings WHERE key = ?", [key]
        )
        res = self.__cursor.fetchone()
        if res is None:
            return default
        return res['value']

    # Returns a dict of `key => value` data. If the key was not found in the DB, the corresponding
    # value will be set to the `default` value.
    def get_multi(self, keys, default = None):
        placeholders = '('
        return_value = {}
        for key in keys:
            placeholders += '?,'
            return_value[key] = default
        placeholders = placeholders.rstrip(',')
        placeholders += ')'

        self.__cursor.execute(
            f"SELECT key, value FROM settings WHERE key IN {placeholders}", keys
        )
        res = self.__cursor.fetchall()

        for row in res:
            return_value[row['key']] = row['value']
        return return_value

    # This may return None if the row doesn't exist.
    def get_row(self, key):
        self.__cursor.execute(
            "SELECT * FROM settings WHERE key = ?", [key]
        )
        return self.__cursor.fetchone()

    def is_enabled(self, key, default = False):
        res = self.get(key, default)
        if res is True or res == '1':
            return True
        else:
            return False

    # Returns a dict: {
    #   tv_id => {
    #       setting1: value,
    #       ...,
    #   },
    #   ...
    # }
    #
    # All TVs are guaranteed to be present in the dict.
    def get_tv_settings(self):
        tv_config = self.__config_loader.get_tv_config()
        display_mode_settings_keys = []
        tv_settings = {}
        for tv_id in tv_config['tvs']:
            display_mode_settings_key = self.make_tv_key_for_setting(self.SETTING_DISPLAY_MODE, tv_id)
            display_mode_settings_keys.append(display_mode_settings_key)
            tv_settings[tv_id] = {}

        display_mode_settings = self.get_multi(display_mode_settings_keys, piwall2.displaymode.DisplayMode.DEFAULT_DISPLAY_MODE)
        for key, display_mode in display_mode_settings.items():
            tv_id = self.get_tv_id_from_settings_key(key)
            tv_settings[tv_id][self.SETTING_DISPLAY_MODE] = display_mode

        return tv_settings

    def make_tv_key_for_setting(self, setting, tv_id):
        return f'{setting}{self.__SETTING_TV_ID_DELIM}{tv_id}'

    def get_tv_id_from_settings_key(self, key):
        return key.split(self.__SETTING_TV_ID_DELIM)[1]
