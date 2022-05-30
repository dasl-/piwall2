import time

class TimeUtils:

    @staticmethod
    def database_date_to_unix_time(database_date):
        return time.mktime(time.strptime(database_date, '%Y-%m-%d  %H:%M:%S'))

    @staticmethod
    def pretty_duration(duration_s):
        duration_s = round(duration_s)
        hours, remainder_seconds = divmod(duration_s, 3600)
        minutes, seconds = divmod(remainder_seconds, 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
