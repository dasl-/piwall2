from piwall2.logger import Logger
import piwall2.broadcaster.database
from piwall2.displaymode import DisplayMode

"""
Stores settings that are modifiable at runtime. They are stored in a DB
and re-read during program execution. They may be modified from a UI.
"""
class SettingsDb:

    # This is a per-TV setting.
    SETTING_DISPLAY_MODE = 'display_mode'

    def __init__(self, config_loader):
        self.__cursor = piwall2.broadcaster.database.Database().get_cursor()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__config_loader = config_loader

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
        return self.__cursor.lastrowid

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
        return self.__cursor.lastrowid is not None

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
            "SELECT key, value FROM settings WHERE keys IN {placeholders}", keys
        )
        res = self.__cursor.fetchall()

        for row in res:
            return_value[row['key']] = row['value']
        return res

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

    def make_tv_key_for_setting(self, setting, hostname, tv_id):
        return f'{setting}_{hostname}_{tv_id}'

    def get_tv_settings(self):
        tv_config = self.__config_loader.get_tv_config()
        display_mode_settings_keys = []
        for tv in tv_config.tvs:
            display_mode_settings_key = self.make_tv_key_for_setting(
                self.SETTING_DISPLAY_MODE, tv['hostname'], tv['tv_id']
            )
            display_mode_settings_keys.append(display_mode_settings_key)

        display_mode_settings = self.get_multi(display_mode_settings_keys, DisplayMode.DISPLAY_MODE_TILE)
        return display_mode_settings
