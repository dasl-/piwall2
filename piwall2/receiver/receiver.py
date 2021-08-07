import socket
import subprocess

from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.logger import Logger
from piwall2.omxplayercontroller import OmxplayerController
from piwall2.receiver.videoreceiver import VideoReceiver

class Receiver:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__control_message_helper = ControlMessageHelper().setup_for_receiver()
        self.__omxplayer_controller = OmxplayerController()
        self.__video_receiver = VideoReceiver()
        self.__hostname = socket.gethostname() + ".local"
        self.__local_ip_address = self.__get_local_ip()

    def run(self):
        self.__logger.info("Started receiver!")

        while True:
            ctrl_msg = None
            try:
                ctrl_msg = self.__control_message_helper.receive_msg()
                self.__logger.debug(f"Received control message {ctrl_msg}.")
            except Exception:
                continue

            if ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY] == ControlMessageHelper.TYPE_VOLUME:
                self.__omxplayer_controller.set_vol_pct(ctrl_msg[ControlMessageHelper.CONTENT_KEY])
            elif ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY] == ControlMessageHelper.TYPE_PLAY_VIDEO:
                self.__receive_and_play_video(ctrl_msg)
            else:
                raise Exception(f"Unsupported control message type: {ctrl_msg[ControlMessageHelper.CTRL_MSG_TYPE_KEY]}.")

    def __receive_and_play_video(self, ctrl_msg):
        ctrl_msg_content = ctrl_msg[ControlMessageHelper.CONTENT_KEY]
        orig_uuid = Logger.get_uuid()
        if 'log_uuid' in ctrl_msg_content:
            Logger.set_uuid(ctrl_msg_content['log_uuid'])

        try:
            if self.__hostname in ctrl_msg_content:
                params_list = ctrl_msg_content[self.__hostname]
            elif self.__local_ip_address in ctrl_msg_content:
                params_list = ctrl_msg_content[self.__local_ip_address]
            else:
                raise Exception(f"Unable to find hostname ({self.__hostname}) or local ip " +
                    f"({self.__local_ip_address}) in control message content: {ctrl_msg_content}")
            self.__video_receiver.receive_and_play_video(params_list)
        finally:
            Logger.set_uuid(orig_uuid)

    def __get_local_ip(self):
        return (subprocess
            .check_output(
                'sudo ifconfig | grep -Eo \'inet (addr:)?([0-9]*\.){3}[0-9]*\' | grep -Eo \'([0-9]*\.){3}[0-9]*\' | grep -v \'127.0.0.1\'',
                stderr = subprocess.STDOUT, shell = True, executable = '/bin/bash'
            )
            .decode("utf-8")
            .strip())
