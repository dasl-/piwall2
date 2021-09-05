import os

class DirectoryUtils:

    def __init__(self):
        # Will be: "/home/pi/development/piwall2" if you install in the default location
        self.root_dir = os.path.abspath(os.path.dirname(__file__) + '/..')
