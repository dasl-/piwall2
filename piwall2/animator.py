from piwall2.broadcaster.settingsdb import SettingsDb
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.displaymode import DisplayMode

class Animator:
    
    # No animation
    ANIMATION_MODE_NONE = 'ANIMATION_MODE_NONE'

    # Cycles between switching all TVs to DISPLAY_MODE_TILE and DISPLAY_MODE_REPEAT
    ANIMATION_MODE_TILE_REPEAT = 'ANIMATION_MODE_TILE_REPEAT'    

    ANIMATION_MODES = (ANIMATION_MODE_NONE, ANIMATION_MODE_TILE_REPEAT)

    def __init__(self):
        self.__animation_mode = None
        self.__settings_db = SettingsDb()
        self.__config_loader = ConfigLoader()
        self.__control_message_helper = ControlMessageHelper()
        self.__ticks = None

    def tick(self):
        old_animation_mode = self.__animation_mode
        new_animation_mode = self.__settings_db.get(SettingsDb.SETTING_ANIMATION_MODE, self.ANIMATION_MODE_NONE)
        self.__animation_mode = new_animation_mode
        if old_animation_mode != new_animation_mode:
            self.__ticks = 0
        else:
            self.__ticks += 1

        if self.__animation_mode == self.ANIMATION_MODE_NONE:
            display_modes_by_tv_id = self.__get_current_display_modes()
        elif self.__animation_mode == self.ANIMATION_MODE_TILE_REPEAT:
            display_modes_by_tv_id = self.__get_display_modes_for_tile_repeat()

        self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, display_modes_by_tv_id)

    def __get_current_display_modes(self):
        display_modes_by_tv_id = {}
        for tv_id, tv_settings in self.__settings_db.get_tv_settings().items():
            display_modes_by_tv_id[tv_id] = tv_settings[SettingsDb.SETTING_DISPLAY_MODE]
        return display_modes_by_tv_id

    def __get_display_modes_for_tile_repeat(self):
        if self.__ticks % 2 == 0:
            display_mode = DisplayMode.DISPLAY_MODE_REPEAT
        else:
            display_mode = DisplayMode.DISPLAY_MODE_TILE

        tv_ids = self.__config_loader.get_tv_ids_list()
        display_modes_by_tv_id = {}
        for tv_id in tv_ids:
            display_modes_by_tv_id[tv_id] = display_mode
        return display_modes_by_tv_id
