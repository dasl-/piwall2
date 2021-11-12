import datetime
import pytz
import sys
import random
import string

class Logger:

    # Log levels
    QUIET = 100
    ERROR = 40
    WARNING = 30
    INFO = 20
    DEBUG = 10
    ALL = 0

    __level = ALL

    __uuid = ''

    def __init__(self, dont_log_to_stdout = False):
        self.__namespace = ""
        self.__dont_log_to_stdout = dont_log_to_stdout

    def set_namespace(self, namespace):
        self.__namespace = namespace
        return self

    # A numeric level means to log everything at that level and above.
    @staticmethod
    def set_level(level):
        if (
            level != Logger.QUIET and level != Logger.ERROR and level != Logger.WARNING and
            level != Logger.INFO and level != Logger.DEBUG and level != Logger.ALL
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
        if Logger.__level > Logger.DEBUG:
            return

        msg = self.__format_msg(level = 'debug', msg = msg)
        if self.__dont_log_to_stdout:
            file = sys.stderr
        else:
            file = sys.stdout
        self.__print_msg(msg, file)

    def info(self, msg):
        if Logger.__level > Logger.INFO:
            return

        msg = self.__format_msg(level = 'info', msg = msg)
        if self.__dont_log_to_stdout:
            file = sys.stderr
        else:
            file = sys.stdout
        self.__print_msg(msg, file)

    def warning(self, msg):
        if Logger.__level > Logger.WARNING:
            return

        msg = self.__format_msg(level = 'warning', msg = msg)
        self.__print_msg(msg, sys.stderr)

    def error(self, msg):
        if Logger.__level > Logger.ERROR:
            return

        msg = self.__format_msg(level = 'error', msg = msg)
        self.__print_msg(msg, sys.stderr)

    def __format_msg(self, level, msg):
        return (datetime.datetime.now(pytz.timezone('UTC')).isoformat() +
            " [" + level + "] [" + self.__namespace + "] [" + Logger.__uuid + "] " + msg)

    def __print_msg(self, msg, file):
        # Note: we could use `flush = True` in our print function. This would result in quicker printing
        # of logs. But strace analysis showed that this resulted in a lot more `write` syscalls, so it is
        # likely harder on the disks, and SD cards in the raspberry pi aren't so great at taking writes
        # anyway.
        #
        # See docs:
        # https://docs.python.org/3/library/functions.html#print
        #
        # See strace analysis of with and without `flush = True`
        # https://gist.github.com/dasl-/796031c305ac26da76cdc2887d9fa817
        print(msg, file = file)
