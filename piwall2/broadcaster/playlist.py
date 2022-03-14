from piwall2.logger import Logger
import piwall2.broadcaster.database

class Playlist:

    STATUS_QUEUED = 'STATUS_QUEUED'
    STATUS_DELETED = 'STATUS_DELETED' # No longer in the queue
    STATUS_PLAYING = 'STATUS_PLAYING'
    STATUS_DONE = 'STATUS_DONE'

    """
    The Playlist DB holds a queue of playlist items to play. These items can be either regular videos or "channel"
    videos, which are queued when the channel up / down buttons on the remote are pressed.
    When a channel video is requested, we insert a new row in the playlist DB. This gets an autoincremented playlist_video_id,
    and playlist_video_id is what we use to order the playlist queue. Thus, if we didn't do anything special, the
    channel video would only start when the current queue of playlist items had been exhausted.

    The behavior we actually want though is to skip the current video (if there is one) and immediately start playing
    the requested channel video. Thus, we actually order the queue by a combination of `type` and `playlist_video_id`. Rows in the
    DB with a `channel_video` type get precedence in the queue.
    """
    TYPE_VIDEO = 'TYPE_VIDEO'
    TYPE_CHANNEL_VIDEO = 'TYPE_CHANNEL_VIDEO'

    # sqlite3's maximum integer value. Higher priority means play the video first.
    __CHANNEL_VIDEO_PRIORITY = 2 ** 63 - 1

    def __init__(self):
        self.__cursor = piwall2.broadcaster.database.Database().get_cursor()
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def construct(self):
        self.__cursor.execute("DROP TABLE IF EXISTS playlist_videos")
        self.__cursor.execute("""
            CREATE TABLE playlist_videos (
                playlist_video_id INTEGER PRIMARY KEY,
                type VARCHAR(20) DEFAULT 'TYPE_VIDEO',
                create_date DATETIME  DEFAULT CURRENT_TIMESTAMP,
                url TEXT,
                thumbnail TEXT,
                title TEXT,
                duration VARCHAR(20),
                status VARCHAR(20),
                is_skip_requested INTEGER DEFAULT 0,
                settings TEXT DEFAULT '',
                priority INTEGER DEFAULT 0
            )""")

        self.__cursor.execute("DROP INDEX IF EXISTS status_type_priority_idx")
        self.__cursor.execute("CREATE INDEX status_type_priority_idx ON playlist_videos (status, type, priority)")
        self.__cursor.execute("DROP INDEX IF EXISTS status_priority_idx")
        self.__cursor.execute("CREATE INDEX status_priority_idx ON playlist_videos (status, priority DESC, playlist_video_id ASC)")

    def enqueue(self, url, thumbnail, title, duration, settings, video_type):
        if video_type == self.TYPE_CHANNEL_VIDEO:
            priority = self.__CHANNEL_VIDEO_PRIORITY
        else:
            priority = 0

        self.__cursor.execute(
            ("INSERT INTO playlist_videos " +
                "(url, thumbnail, title, duration, status, settings, type, priority) " +
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)"),
            [url, thumbnail, title, duration, self.STATUS_QUEUED, settings, video_type, priority]
        )
        return self.__cursor.lastrowid

    def reenqueue(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set status = ?, is_skip_requested = ? WHERE playlist_video_id = ?",
            [self.STATUS_QUEUED, 0, playlist_video_id]
        )
        return self.__cursor.rowcount >= 1

    # Passing the id of the video to skip ensures our skips are "atomic". That is, we can ensure we skip the
    # video that the user intended to skip.
    def skip(self, playlist_video_id):
        self.__cursor.execute(
            "UPDATE playlist_videos set is_skip_requested = 1 WHERE status = ? AND playlist_video_id = ?",
            [self.STATUS_PLAYING, playlist_video_id]
        )
        return self.__cursor.rowcount >= 1

    def remove_videos_of_type(self, video_type):
        self.__cursor.execute(
            "UPDATE playlist_videos set status = ? WHERE status = ? AND type = ?",
            [self.STATUS_DELETED, self.STATUS_QUEUED, video_type]
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

    def play_next(self, playlist_video_id):
        self.__cursor.execute(
            """
                UPDATE playlist_videos set priority = (
                    SELECT MAX(priority)+1 FROM playlist_videos WHERE type = ? AND status = ?
                ) WHERE playlist_video_id = ?
            """,
            [self.TYPE_VIDEO, self.STATUS_QUEUED, playlist_video_id]
        )
        return self.__cursor.rowcount >= 1

    def get_current_video(self):
        self.__cursor.execute("SELECT * FROM playlist_videos WHERE status = ? LIMIT 1", [self.STATUS_PLAYING])
        return self.__cursor.fetchone()

    def get_next_playlist_item(self):
        self.__cursor.execute(
            "SELECT * FROM playlist_videos WHERE status = ? order by priority desc, playlist_video_id asc LIMIT 1",
            [self.STATUS_QUEUED]
        )
        return self.__cursor.fetchone()

    def get_queue(self):
        self.__cursor.execute(
            "SELECT * FROM playlist_videos WHERE status IN (?, ?) order by priority desc, playlist_video_id asc",
            [self.STATUS_PLAYING, self.STATUS_QUEUED]
        )
        queue = self.__cursor.fetchall()
        ordered_queue = []
        for playlist_item in queue:
            if playlist_item['status'] == self.STATUS_PLAYING:
                ordered_queue.insert(0, playlist_item)
            else:
                ordered_queue.append(playlist_item)
        return ordered_queue

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
