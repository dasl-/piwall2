from piwall2.broadcaster.settingsdb import SettingsDb
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.displaymode import DisplayMode

class Animator:
    
    # No animation
    ANIMATION_MODE_NONE = 'ANIMATION_MODE_NONE'

    # Cycles between switching all TVs to DISPLAY_MODE_TILE and DISPLAY_MODE_REPEAT
    ANIMATION_MODE_TILE_REPEAT = 'ANIMATION_MODE_TILE_REPEAT'    

    # Pseudo animation mode: turn all the TVs to DISPLAY_MODE_TILE
    ANIMATION_MODE_TILE = 'ANIMATION_MODE_TILE'

    # Pseudo animation mode: turn all the TVs to DISPLAY_MODE_REPEAT
    ANIMATION_MODE_REPEAT = 'ANIMATION_MODE_REPEAT'

    ANIMATION_MODES = (ANIMATION_MODE_NONE, ANIMATION_MODE_TILE_REPEAT, ANIMATION_MODE_TILE, ANIMATION_MODE_REPEAT)
    PSEUDO_ANIMATION_MODES = (ANIMATION_MODE_TILE, ANIMATION_MODE_REPEAT)

    def __init__(self):
        self.__animation_mode = None
        self.__settings_db = SettingsDb()
        self.__config_loader = ConfigLoader()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__ticks = None
        self.__display_mode_helper = DisplayMode()

    def set_animation_mode(self, animation_mode):
        if animation_mode in self.PSEUDO_ANIMATION_MODES:
            if animation_mode == self.ANIMATION_MODE_TILE:
                display_mode = DisplayMode.DISPLAY_MODE_TILE
            else:
                display_mode = DisplayMode.DISPLAY_MODE_REPEAT

            animation_mode = self.ANIMATION_MODE_NONE
            display_mode_by_tv_id = {}
            tv_ids = self.__config_loader.get_tv_ids_list()
            for tv_id in tv_ids:
                display_mode_by_tv_id[tv_id] = display_mode
            self.__display_mode_helper.set_display_mode(display_mode_by_tv_id)

        success = self.__settings_db.set(SettingsDb.SETTING_ANIMATION_MODE, animation_mode)
        return success

    # Pseudo-animation modes are never stored in the DB. Instead, a value of ANIMATION_MODE_NONE will be stored
    # in the DB in place of the pseudo animation mode. But if all of the TVs are using the same display_mode,
    # we will return the corresponding pseudo-animation mode -- inferring an animation mode based on the
    # display_mode settings. This enables
    def get_animation_mode(self, use_pseudo_animation_mode = True):
        animation_mode = self.__settings_db.get(SettingsDb.SETTING_ANIMATION_MODE, self.ANIMATION_MODE_NONE)
        if (
            not use_pseudo_animation_mode or
            (animation_mode not in self.PSEUDO_ANIMATION_MODES and animation_mode != self.ANIMATION_MODE_NONE)
        ):
            return animation_mode

        display_mode_by_tv_id = self.__display_mode_helper.get_display_mode_by_tv_id()
        first_display_mode = None
        are_all_display_modes_the_same = True
        for display_mode in display_mode_by_tv_id.values():
            if first_display_mode is None:
                first_display_mode = display_mode
            elif display_mode != first_display_mode:
                are_all_display_modes_the_same = False
                break

        if are_all_display_modes_the_same:
            if first_display_mode == DisplayMode.DISPLAY_MODE_TILE:
                return self.ANIMATION_MODE_TILE
            elif first_display_mode == DisplayMode.DISPLAY_MODE_REPEAT:
                return self.ANIMATION_MODE_REPEAT

        return self.ANIMATION_MODE_NONE

    def tick(self):
        old_animation_mode = self.__animation_mode
        new_animation_mode = self.get_animation_mode(use_pseudo_animation_mode = False)
        self.__animation_mode = new_animation_mode
        if old_animation_mode != new_animation_mode:
            self.__ticks = 0
        else:
            self.__ticks += 1

        if self.__animation_mode == self.ANIMATION_MODE_NONE:
            display_mode_by_tv_id = self.__get_current_display_modes()
        elif self.__animation_mode == self.ANIMATION_MODE_TILE_REPEAT:
            display_mode_by_tv_id = self.__get_display_modes_for_tile_repeat()

        if self.__animation_mode == self.ANIMATION_MODE_NONE:
            # send the DISPLAY_MODE control message even if we're using ANIMATION_MODE_NONE to ensure
            # eventual consistency of the DISPLAY_MODE
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, display_mode_by_tv_id)
        else:
            self.__display_mode_helper.set_display_mode(display_mode_by_tv_id)

    def __get_current_display_modes(self):
        display_mode_by_tv_id = {}
        for tv_id, tv_settings in self.__settings_db.get_tv_settings().items():
            display_mode_by_tv_id[tv_id] = tv_settings[SettingsDb.SETTING_DISPLAY_MODE]
        return display_mode_by_tv_id

    def __get_display_modes_for_tile_repeat(self):
        if self.__ticks % 2 == 0:
            display_mode = DisplayMode.DISPLAY_MODE_REPEAT
        else:
            display_mode = DisplayMode.DISPLAY_MODE_TILE

        tv_ids = self.__config_loader.get_tv_ids_list()
        display_mode_by_tv_id = {}
        for tv_id in tv_ids:
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id
