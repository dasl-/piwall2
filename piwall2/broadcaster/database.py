import sqlite3
import threading
import time

from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger
import piwall2.broadcaster.playlist
import piwall2.broadcaster.settingsdb

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


thread_local = threading.local()

class Database:

    __DB_PATH = DirectoryUtils().root_dir + '/piwall2.db'

    # Zero indexed schema_version (first version is v0).
    __SCHEMA_VERSION = 3

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    # Schema change how-to:
    # 1) Update all DB classes with 'virgin' sql (i.e. Playlist().construct(), etc)
    # 2) Increment self.__SCHEMA_VERSION
    # 3) Implement self.__update_schema_to_vN method for the incremented SCHEMA_VERSION
    # 4) Call the method in the below for loop.
    # 5) Run ./install/install.sh
    def construct(self):
        self.get_cursor().execute("BEGIN TRANSACTION")
        try:
            self.get_cursor().execute("SELECT version FROM schema_version")
            current_schema_version = int(self.get_cursor().fetchone()['version'])
        except Exception:
            current_schema_version = -1

        self.__logger.info("current_schema_version: {}".format(current_schema_version))

        if current_schema_version == -1:
            # construct from scratch
            self.__logger.info("Constructing database schema from scratch...")
            self.__construct_schema_version()
            piwall2.broadcaster.playlist.Playlist().construct()
            piwall2.broadcaster.settingsdb.SettingsDb().construct()
        elif current_schema_version < self.__SCHEMA_VERSION:
            self.__logger.info(
                f"Database schema is outdated. Updating from version {current_schema_version} to " +
                f"{self.__SCHEMA_VERSION}."
            )
            for i in range(current_schema_version + 1, self.__SCHEMA_VERSION + 1):
                self.__logger.info(
                    "Running database schema change to update from version {} to {}.".format(i - 1, i)
                )

                if i == 1:
                    self.__update_schema_to_v1()
                elif i == 2:
                    self.__update_schema_to_v2()
                elif i == 3:
                    self.__update_schema_to_v3()
                else:
                    msg = "No update schema method defined for version: {}.".format(i)
                    self.__logger.error(msg)
                    raise Exception(msg)
                self.get_cursor().execute("UPDATE schema_version set version = ?", [i])
        elif current_schema_version == self.__SCHEMA_VERSION:
            self.__logger.info("Database schema is already up to date!")
            return
        else:
            msg = ("Database schema is newer than should be possible. This should never happen. " +
                "current_schema_version: {}. Tried to update to version: {}."
                .format(current_schema_version, self.__SCHEMA_VERSION))
            self.__logger.error(msg)
            raise Exception(msg)

        self.get_cursor().execute("COMMIT")
        self.__logger.info("Database schema constructed successfully.")

    def get_cursor(self):
        cursor = getattr(thread_local, 'database_cursor', None)
        if cursor is None:
            # `isolation_level = None` specifies autocommit mode.
            conn = sqlite3.connect(self.__DB_PATH, isolation_level = None)
            conn.row_factory = dict_factory
            cursor = conn.cursor()
            thread_local.database_cursor = cursor
        return cursor

    def __construct_schema_version(self):
        self.get_cursor().execute("DROP TABLE IF EXISTS schema_version")
        self.get_cursor().execute("CREATE TABLE schema_version (version INTEGER)")
        self.get_cursor().execute(
            "INSERT INTO schema_version (version) VALUES(?)",
            [self.__SCHEMA_VERSION]
        )

    # Add new table for storing settings
    def __update_schema_to_v1(self):
        piwall2.broadcaster.settingsdb.SettingsDb().construct()

    def __update_schema_to_v2(self):
        self.get_cursor().execute("ALTER TABLE playlist_videos ADD COLUMN type VARCHAR(20) DEFAULT 'TYPE_VIDEO'")
        self.get_cursor().execute("DROP INDEX IF EXISTS status_idx")
        self.get_cursor().execute("CREATE INDEX status_type_idx ON playlist_videos (status, type ASC, playlist_video_id ASC)")

    def __update_schema_to_v3(self):
        self.get_cursor().execute("ALTER TABLE playlist_videos ADD COLUMN priority INTEGER DEFAULT 0")
        self.get_cursor().execute("DROP INDEX IF EXISTS status_type_idx")
        self.get_cursor().execute("DROP INDEX IF EXISTS status_type_priority_idx")
        self.get_cursor().execute("CREATE INDEX status_type_priority_idx ON playlist_videos (status, type, priority)")
        self.get_cursor().execute("DROP INDEX IF EXISTS status_priority_idx")
        self.get_cursor().execute("CREATE INDEX status_priority_idx ON playlist_videos (status, priority DESC, playlist_video_id ASC)")
