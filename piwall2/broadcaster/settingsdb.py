from piwall2.logger import Logger
import piwall2.broadcaster.database

"""
Stores settings that are modifiable at runtime. They are stored in a DB
and re-read during program execution. They may be modified from a UI.
"""
class SettingsDb:

    # Format string for DISPLAY_MODE setting key. Receiver's host name will be interpolated.
    # This is a per-receiver setting.
    DISPLAY_MODE_TEMPLATE = 'display_mode_{hostname}_{tv_id}'

    def __init__(self):
        self.__cursor = piwall2.broadcaster.database.Database().get_cursor()
        self.__logger = Logger().set_namespace(self.__class__.__name__)

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

    # This may return None if the row doesn't exist.
    def getRow(self, key):
        self.__cursor.execute(
            "SELECT * FROM settings WHERE key = ?", [key]
        )
        return self.__cursor.fetchone()

    def isEnabled(self, key, default = False):
        res = self.get(key, default)
        if res is True or res == '1':
            return True
        else:
            return False
