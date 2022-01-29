import http.server
import io
import json
import traceback
import urllib
from urllib.parse import urlparse

from piwall2.animator import Animator
from piwall2.broadcaster.playlist import Playlist
from piwall2.broadcaster.settingsdb import SettingsDb
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.directoryutils import DirectoryUtils
from piwall2.displaymode import DisplayMode
from piwall2.logger import Logger
from piwall2.volumecontroller import VolumeController

class Piwall2Api():

    def __init__(self):
        self.__playlist = Playlist()
        self.__settings_db = SettingsDb()
        self.__vol_controller = VolumeController()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__display_mode_helper = DisplayMode()
        self.__animator = Animator()

    # get all the data that we poll for every second in the piwall2
    def get_queue(self):
        response_details = {}
        queue = self.__playlist.get_queue()
        tv_settings = self.__settings_db.get_tv_settings()
        animation_mode = self.__animator.get_animation_mode()
        response_details = {
            'queue': queue,
            'vol_pct': self.__vol_controller.get_vol_pct(),
            'tv_settings': tv_settings,
            SettingsDb.SETTING_ANIMATION_MODE: animation_mode,
            'success': True,
        }
        return response_details

    def get_title(self):
        current_video = self.__playlist.get_current_video()
        if current_video:
            return current_video['title']
        else:
            return ''

    def get_volume(self):
        response_details = {
            'vol_pct': self.__vol_controller.get_vol_pct(),
            'success': True,
        }
        return response_details

    def enqueue(self, post_data):
        self.__playlist.enqueue(
            post_data['url'], post_data['thumbnail'], post_data['title'],
            post_data['duration'], '', Playlist.TYPE_VIDEO
        )
        response_details = post_data
        response_details['success'] = True
        return response_details

    def skip(self, post_data):
        success = self.__playlist.skip(post_data['playlist_video_id'])
        return {'success': success}

    def remove(self, post_data):
        success = self.__playlist.remove(post_data['playlist_video_id'])
        return {'success': success}

    def clear(self):
        self.__playlist.clear()
        return {'success': True}

    # TODO : race conditions when setting volume, bigger surface area after converting to ThreadingHTTPServer.
    # Options:
    # 1) increase time interval to send ajax volume requests to reduce likelihood of race condition
    # 2) lock sending ajax volume requests until any in-flight requests return their response
    #
    # Also, investigate whatever client side locking I did here...?
    def set_vol_pct(self, post_data):
        vol_pct = int(post_data['vol_pct'])
        self.__vol_controller.set_vol_pct(vol_pct)
        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_VOLUME, vol_pct)
        return {
            'vol_pct': vol_pct,
            'success': True
        }

    # post_data is key value pairs where the key is a tv_id and the value is a display_mode for that TV.
    def set_display_mode(self, post_data):
        # validate data
        display_mode_by_tv_id = post_data
        for tv_id, display_mode in display_mode_by_tv_id.items():
            if display_mode not in DisplayMode.DISPLAY_MODES:
                return {'success': False}

        success = self.__display_mode_helper.set_display_mode(display_mode_by_tv_id)
        return {'success': success}

    def set_animation_mode(self, post_data):
        animation_mode = post_data[SettingsDb.SETTING_ANIMATION_MODE]
        if animation_mode not in Animator.ANIMATION_MODES:
            return {'success': False}
        success = self.__animator.set_animation_mode(animation_mode)
        return {'success': success}

    def get_youtube_api_key(self):
        return {
            SettingsDb.SETTING_YOUTUBE_API_KEY: self.__settings_db.get(SettingsDb.SETTING_YOUTUBE_API_KEY),
            'success': True,
        }

class ServerRequestHandler(http.server.BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
        self.__root_dir = DirectoryUtils().root_dir + "/app/build"
        self.__api = Piwall2Api()
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        http.server.BaseHTTPRequestHandler.__init__(self, request, client_address, server)

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            if self.path[:4] == "/api":
                return self.__do_api_GET(self.path[5:])

            return self.__serve_static_asset()
        except Exception:
            self.log_error('Exception: {}'.format(traceback.format_exc()))

    def do_POST(self):
        try:
            if self.path[:4] == "/api":
                return self.__do_api_POST(self.path[5:])
            return self.__serve_static_asset()
        except Exception:
            self.log_error('Exception: {}'.format(traceback.format_exc()))

    def __do_404(self):
        self.send_response(404)
        self.end_headers()

    def __do_api_GET(self, path):
        parsed_path = urllib.parse.urlparse(path)
        get_data = urllib.parse.unquote(parsed_path.query)
        if get_data:
            get_data = json.loads(get_data)

        if parsed_path.path == 'queue':
            response = self.__api.get_queue()
        elif parsed_path.path == 'vol_pct':
            response = self.__api.get_volume()
        elif parsed_path.path == 'youtube_api_key':
            response = self.__api.get_youtube_api_key()
        elif parsed_path.path == 'title':
            response = self.__api.get_title()
        else:
            self.__do_404()
            return

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp = io.BytesIO()
        resp.write(bytes(json.dumps(response), 'utf-8'))
        self.wfile.write(resp.getvalue())

    def __do_api_POST(self, path):
        content_length = int(self.headers['Content-Length'])

        post_data = None
        if content_length > 0:
            body = self.rfile.read(content_length)
            post_data = json.loads(body.decode("utf-8"))

        if path == 'queue':
            response = self.__api.enqueue(post_data)
        elif path == 'skip':
            response = self.__api.skip(post_data)
        elif path == 'remove':
            response = self.__api.remove(post_data)
        elif path == 'clear':
            response = self.__api.clear()
        elif path == 'vol_pct':
            response = self.__api.set_vol_pct(post_data)
        elif path == 'display_mode':
            response = self.__api.set_display_mode(post_data)
        elif path == 'animation_mode':
            response = self.__api.set_animation_mode(post_data)
        else:
            self.__do_404()
            return

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp = io.BytesIO()
        resp.write(bytes(json.dumps(response), 'utf-8'))
        self.wfile.write(resp.getvalue())

    def __serve_static_asset(self):
        self.path = urlparse(self.path).path # get rid of query parameters e.g. `?foo=bar&baz=1`
        if self.path == '/':
            self.path = self.__root_dir + '/index.html'
        elif self.path.startswith('/assets/'):
            self.path = DirectoryUtils().root_dir + '/assets/' + self.path[len('/assets/'):]
        else:
            self.path = self.__root_dir + self.path

        try:
            file_to_open = open(self.path, 'rb').read()
            self.send_response(200)
        except Exception:
            self.log_error("")
            self.log_error(f'Unable to open file at {self.path}. Exception: {traceback.format_exc()}')
            self.__do_404()
            return

        if self.path.endswith('.js'):
            self.send_header("Content-Type", "text/javascript")
        elif self.path.endswith('.css'):
            self.send_header("Content-Type", "text/css")
        elif self.path.endswith('.svg') or self.path.endswith('.svgz'):
            self.send_header("Content-Type", "image/svg+xml")
        self.end_headers()

        if type(file_to_open) is bytes:
            self.wfile.write(file_to_open)
        else:
            self.wfile.write(bytes(file_to_open, 'utf-8'))
        return

    def log_request(self, code='-', size='-'):
        if isinstance(code, http.server.HTTPStatus):
            code = code.value
        self.log_message('[REQUEST] "%s" %s %s', self.requestline, str(code), str(size))

    def log_error(self, format, *args):
        self.__logger.error("%s - - %s" % (self.client_address[0], format % args))

    def log_message(self, format, *args):
        self.__logger.info("%s - - %s" % (self.client_address[0], format % args))

class Piwall2ThreadingHTTPServer(http.server.ThreadingHTTPServer):

    # Override: https://github.com/python/cpython/blob/18cb2ef46c9998480f7182048435bc58265c88f2/Lib/socketserver.py#L421-L443
    # See: https://docs.python.org/3/library/socketserver.html#socketserver.BaseServer.request_queue_size
    # This prevents messages we might see in `dmesg` like:
    #   [Sat Jan 29 00:44:36 2022] TCP: request_sock_TCP: Possible SYN flooding on port 80. Sending cookies.  Check SNMP counters.
    request_queue_size = 128

class Server:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info('Starting up server...')
        self.__server = Piwall2ThreadingHTTPServer(('0.0.0.0', 80), ServerRequestHandler)
        self.__config_loader = ConfigLoader()

    def serve_forever(self):
        self.__logger.info('Server is serving forever...')
        self.__server.serve_forever()
