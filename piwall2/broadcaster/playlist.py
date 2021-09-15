from piwall2.logger import Logger
import piwall2.broadcaster.database

class Playlist:

    STATUS_QUEUED = 'STATUS_QUEUED'
    STATUS_DELETED = 'STATUS_DELETED' # No longer in the queue
    STATUS_PLAYING = 'STATUS_PLAYING'
    STATUS_DONE = 'STATUS_DONE'

    def __init__(self):
        self.__cursor = piwall2.broadcaster.database.Database().get_cursor()
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def construct(self):
        self.__cursor.execute("DROP TABLE IF EXISTS playlist_videos")
        self.__cursor.execute("""
            CREATE TABLE playlist_videos (
                playlist_video_id INTEGER PRIMARY KEY,
                create_date DATETIME  DEFAULT CURRENT_TIMESTAMP,
                url TEXT,
                thumbnail TEXT,
                title TEXT,
                duration VARCHAR(20),
                status VARCHAR(20),
                is_skip_requested INTEGER DEFAULT 0,
                settings TEXT DEFAULT ''
            )""")

        self.__cursor.execute("DROP INDEX IF EXISTS status_idx")
        self.__cursor.execute("CREATE INDEX status_idx ON playlist_videos (status, playlist_video_id ASC)")

    def enqueue(self, url, thumbnail, title, duration, settings):
        self.__cursor.execute(
            ("INSERT INTO playlist_videos " +
                "(url, thumbnail, title, duration, status, settings) " +
                "VALUES(?, ?, ?, ?, ?, ?)"),
            [url, thumbnail, title, duration, self.STATUS_QUEUED, settings]
        )
        return self.__cursor.lastrowid

    # Passing the id of the video to skip ensures our skips are "atomic". That is, we can ensure we skip the
    # video that the user intended to skip.
    def skip(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set is_skip_requested = 1 WHERE status = ? AND playlist_video_id = ?",
            [self.STATUS_PLAYING, playlist_video_id]
        )
        return self.__cursor.rowcount >= 1

    def remove(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set status = ? WHERE playlist_video_id = ? AND status = ?",
            [self.STATUS_DELETED, playlist_video_id, self.STATUS_QUEUED]
        )
        return self.__cursor.rowcount >= 1

    def clear(self):
        self.__cursor.execute("UPDATE playlist_videos set status = ? WHERE status = ?",
            [self.STATUS_DELETED, self.STATUS_QUEUED]
        )
        self.__cursor.execute(
            "UPDATE playlist_videos set is_skip_requested = 1 WHERE status = ?",
            [self.STATUS_PLAYING]
        )

    def get_current_video(self):
        self.__cursor.execute("SELECT * FROM playlist_videos WHERE status = ? LIMIT 1", [self.STATUS_PLAYING])
        return self.__cursor.fetchone()

    def get_next_playlist_item(self):
        self.__cursor.execute(
            "SELECT * FROM playlist_videos WHERE status = ? order by playlist_video_id asc LIMIT 1",
            [self.STATUS_QUEUED]
        )
        return self.__cursor.fetchone()

    def get_queue(self):
        self.__cursor.execute(
            "SELECT * FROM playlist_videos WHERE status IN (?, ?) order by playlist_video_id asc",
            [self.STATUS_PLAYING, self.STATUS_QUEUED]
        )
        return self.__cursor.fetchall()

    # Atomically set the requested video to "playing" status. This may fail if in a scenario like:
    #   1) Next video in the queue is retrieved
    #   2) Someone deletes the video from the queue
    #   3) We attempt to set the video to "playing" status
    def set_current_video(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set status = ? WHERE status = ? AND playlist_video_id = ?",
            [self.STATUS_PLAYING, self.STATUS_QUEUED, playlist_video_id]
        )
        if self.__cursor.rowcount == 1:
            return True
        return False

    def end_video(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set status=? WHERE playlist_video_id=?",
            [self.STATUS_DONE, playlist_video_id]
        )

    # Clean up any weird state we may have in the DB as a result of unclean shutdowns, etc:
    # set any existing 'playing' videos to 'done'.
    def clean_up_state(self):
        self.__cursor.execute(
            "UPDATE playlist_videos set status = ? WHERE status = ?",
            [self.STATUS_DONE, self.STATUS_PLAYING]
        )

    def should_skip_video_id(self, playlist_video_id):
        current_video = self.get_current_video()
        if current_video and current_video['playlist_video_id'] != playlist_video_id:
            self.__logger.warning(
                "Database and current process disagree about which playlist item is currently playing. " +
                f"Database says playlist_video_id: {current_video['playlist_video_id']}, whereas current " +
                f"process says playlist_video_id: {playlist_video_id}."
            )
            return False

        if current_video and current_video["is_skip_requested"]:
            self.__logger.info("Skipping current playlist item as requested.")
            return True

        return False
