import datetime
import pytz
import sys
import random
import string

class Logger:

    # Log levels
    ERROR = 40
    WARNING = 30
    INFO = 20
    DEBUG = 10

    __level = None

    __uuid = ''

    def __init__(self, dont_log_to_stdout = False):
        self.__namespace = ""
        self.__dont_log_to_stdout = dont_log_to_stdout

    def set_namespace(self, namespace):
        self.__namespace = namespace
        return self

    # A level of None means to log every level.
    # A numeric level means to log everything at that level and above.
    @staticmethod
    def set_level(level):
        if (
            level != Logger.ERROR and level != Logger.WARNING and level != Logger.INFO and
            level != Logger.DEBUG and level is not None
        ):
            raise Exception("Invalid level specified")
        Logger.__level = level

    @staticmethod
    def get_level():
        return Logger.__level

    @staticmethod
    def make_uuid():
        return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))

    @staticmethod
    def set_uuid(uuid):
        Logger.__uuid = uuid

    @staticmethod
    def get_uuid():
        return Logger.__uuid

    def debug(self, msg):
        if Logger.__level is not None and Logger.__level > Logger.DEBUG:
            return

        msg = self.__format_msg(level = 'debug', msg = msg)
        if self.__dont_log_to_stdout:
            file = sys.stderr
        else:
            file = sys.stdout
        print(msg, file = file, flush = True)

    def info(self, msg):
        if Logger.__level is not None and Logger.__level > Logger.INFO:
            return

        msg = self.__format_msg(level = 'info', msg = msg)
        if self.__dont_log_to_stdout:
            file = sys.stderr
        else:
            file = sys.stdout
        print(msg, file = file, flush = True)

    def warning(self, msg):
        if Logger.__level is not None and Logger.__level > Logger.WARNING:
            return

        msg = self.__format_msg(level = 'warning', msg = msg)
        print(msg, file = sys.stderr, flush = True)

    def error(self, msg):
        if Logger.__level is not None and Logger.__level > Logger.ERROR:
            return

        msg = self.__format_msg(level = 'error', msg = msg)
        print(msg, file = sys.stderr, flush = True)

    def __format_msg(self, level, msg):
        return (datetime.datetime.now(pytz.timezone('UTC')).isoformat() +
            " [" + level + "] [" + self.__namespace + "] [" + Logger.__uuid + "] " + msg)
