import math
import time

from piwall2.broadcaster.settingsdb import SettingsDb
from piwall2.configloader import ConfigLoader
from piwall2.controlmessagehelper import ControlMessageHelper
from piwall2.displaymode import DisplayMode
from piwall2.logger import Logger

class Animator:

    # No animation
    ANIMATION_MODE_NONE = 'ANIMATION_MODE_NONE'

    # Cycles between switching all TVs to DISPLAY_MODE_FULLSCREEN and DISPLAY_MODE_TILE
    ANIMATION_MODE_FULLSCREEN_TILE = 'ANIMATION_MODE_FULLSCREEN_TILE'

    ANIMATION_MODE_RAIN = 'ANIMATION_MODE_RAIN'
    ANIMATION_MODE_SPIRAL = 'ANIMATION_MODE_SPIRAL'

    # Toggle display_modes one column at a time
    ANIMATION_MODE_LEFT = 'ANIMATION_MODE_LEFT'
    ANIMATION_MODE_RIGHT = 'ANIMATION_MODE_RIGHT'

    # Toggle display_modes one row at a time
    ANIMATION_MODE_UP = 'ANIMATION_MODE_UP'
    ANIMATION_MODE_DOWN = 'ANIMATION_MODE_DOWN'

    # Pseudo animation mode: turn all the TVs to DISPLAY_MODE_FULLSCREEN
    ANIMATION_MODE_FULLSCREEN = 'ANIMATION_MODE_FULLSCREEN'

    # Pseudo animation mode: turn all the TVs to DISPLAY_MODE_TILE
    ANIMATION_MODE_TILE = 'ANIMATION_MODE_TILE'

    ANIMATION_MODES = (ANIMATION_MODE_NONE, ANIMATION_MODE_FULLSCREEN_TILE, ANIMATION_MODE_LEFT,
        ANIMATION_MODE_RIGHT, ANIMATION_MODE_UP, ANIMATION_MODE_DOWN, ANIMATION_MODE_FULLSCREEN, ANIMATION_MODE_TILE,
        ANIMATION_MODE_RAIN, ANIMATION_MODE_SPIRAL)
    PSEUDO_ANIMATION_MODES = (ANIMATION_MODE_FULLSCREEN, ANIMATION_MODE_TILE)

    __NUM_SECS_BTWN_DB_UPDATES = 2

    def __init__(self, ticks_per_second = 1):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__animation_mode = None
        self.__settings_db = SettingsDb()
        self.__config_loader = ConfigLoader()
        self.__control_message_helper = ControlMessageHelper().setup_for_broadcaster()
        self.__ticks = None
        self.__display_mode_helper = DisplayMode()
        self.__last_update_db_time = 0
        self.__ticks_per_second = ticks_per_second

    def set_animation_mode(self, animation_mode):
        if animation_mode in self.PSEUDO_ANIMATION_MODES:
            if animation_mode == self.ANIMATION_MODE_FULLSCREEN:
                display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
            else:
                display_mode = DisplayMode.DISPLAY_MODE_TILE

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
            if first_display_mode == DisplayMode.DISPLAY_MODE_FULLSCREEN:
                return self.ANIMATION_MODE_FULLSCREEN
            elif first_display_mode == DisplayMode.DISPLAY_MODE_TILE:
                return self.ANIMATION_MODE_TILE

        return self.ANIMATION_MODE_NONE

    def tick(self):
        old_animation_mode = self.__animation_mode
        new_animation_mode = self.get_animation_mode(use_pseudo_animation_mode = False)
        self.__animation_mode = new_animation_mode
        if old_animation_mode != new_animation_mode:
            self.__ticks = 0
        else:
            self.__ticks += 1

        display_mode_by_tv_id = None
        if self.__animation_mode == self.ANIMATION_MODE_NONE:
            if not self.__should_update(2):
                return
            display_mode_by_tv_id = self.__get_current_display_modes()
        elif self.__animation_mode == self.ANIMATION_MODE_FULLSCREEN_TILE:
            if not self.__should_update(2):
                return
            display_mode_by_tv_id = self.__get_display_modes_for_fullscreen_tile()
        elif (
            self.__animation_mode in (
                self.ANIMATION_MODE_LEFT, self.ANIMATION_MODE_RIGHT,
                self.ANIMATION_MODE_UP, self.ANIMATION_MODE_DOWN
            )
        ):
            if not self.__should_update(2):
                return
            display_mode_by_tv_id = self.__get_display_modes_for_direction()
        elif self.__animation_mode == self.ANIMATION_MODE_RAIN:
            if not self.__should_update(0):
                return
            display_mode_by_tv_id = self.__get_display_modes_for_rain()
        elif self.__animation_mode == self.ANIMATION_MODE_SPIRAL:
            if not self.__should_update(0):
                return
            display_mode_by_tv_id = self.__get_display_modes_for_spiral()

        if not display_mode_by_tv_id:
            return

        if self.__animation_mode == self.ANIMATION_MODE_NONE:
            # send the DISPLAY_MODE control message even if we're using ANIMATION_MODE_NONE to ensure
            # eventual consistency of the DISPLAY_MODE
            self.__control_message_helper.send_msg(ControlMessageHelper.TYPE_DISPLAY_MODE, display_mode_by_tv_id)
        else:
            # Updating the DB can be slow -- occasionally it takes ~2 seconds because the SD cards
            # can be slow randomly. So don't do it too often.
            should_update_db = False
            now = time.time()
            if (now - self.__last_update_db_time) > self.__NUM_SECS_BTWN_DB_UPDATES:
                should_update_db = True
                self.__last_update_db_time = now
            self.__display_mode_helper.set_display_mode(display_mode_by_tv_id, should_update_db)

    # When update_every_N_seconds == 0, we update every tick.
    # Be less spamy updating state on receivers. Spamming them with the same state rapidly mqakes it more likely
    # that they will be busy when you actually DO want to update the state with a new state.
    def __should_update(self, update_every_N_seconds):
        if update_every_N_seconds <= 0:
            return True
        num_ticks_before_changing = self.__ticks_per_second * update_every_N_seconds
        if self.__ticks % num_ticks_before_changing != 0:
            return False
        return True

    def __get_current_display_modes(self):
        display_mode_by_tv_id = {}
        for tv_id, tv_settings in self.__settings_db.get_tv_settings().items():
            display_mode_by_tv_id[tv_id] = tv_settings[SettingsDb.SETTING_DISPLAY_MODE]
        return display_mode_by_tv_id

    def __get_display_modes_for_fullscreen_tile(self):
        # Change modes every N seconds
        num_ticks_before_changing = self.__ticks_per_second * 2
        adjusted_tick = math.floor(self.__ticks / num_ticks_before_changing)
        if adjusted_tick % 2 == 0:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
        else:
            display_mode = DisplayMode.DISPLAY_MODE_TILE

        tv_ids = self.__config_loader.get_tv_ids_list()
        display_mode_by_tv_id = {}
        for tv_id in tv_ids:
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id

    def __get_display_modes_for_direction(self):
        num_rows = self.__config_loader.get_num_wall_rows()
        num_columns = self.__config_loader.get_num_wall_columns()

        if self.__ticks == 0:
            tv_ids = self.__config_loader.get_tv_ids_list()
        elif self.__animation_mode == self.ANIMATION_MODE_LEFT:
            column_number = (num_columns - 1) - ((self.__ticks - 1) % num_columns)
            tv_ids = self.__config_loader.get_wall_columns()[column_number]
        elif self.__animation_mode == self.ANIMATION_MODE_RIGHT:
            column_number = ((self.__ticks - 1) % num_columns)
            tv_ids = self.__config_loader.get_wall_columns()[column_number]
        elif self.__animation_mode == self.ANIMATION_MODE_UP:
            row_number = (num_rows - 1) - ((self.__ticks - 1) % num_rows)
            tv_ids = self.__config_loader.get_wall_rows()[row_number]
        elif self.__animation_mode == self.ANIMATION_MODE_DOWN:
            row_number = ((self.__ticks - 1) % num_rows)
            tv_ids = self.__config_loader.get_wall_rows()[row_number]

        if self.__ticks == 0:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
        elif self.__animation_mode in (self.ANIMATION_MODE_LEFT, self.ANIMATION_MODE_RIGHT):
            if math.floor((self.__ticks - 1) / num_columns) % 2 == 0:
                display_mode = DisplayMode.DISPLAY_MODE_TILE
            else:
                display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
        elif self.__animation_mode in (self.ANIMATION_MODE_UP, self.ANIMATION_MODE_DOWN):
            if math.floor((self.__ticks - 1) / num_rows) % 2 == 0:
                display_mode = DisplayMode.DISPLAY_MODE_TILE
            else:
                display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN

        display_mode_by_tv_id = {}
        for tv_id in tv_ids:
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id

    def __get_display_modes_for_rain(self):
        num_rows = self.__config_loader.get_num_wall_rows()
        num_columns = self.__config_loader.get_num_wall_columns()

        if self.__ticks == 0:
            tv_ids = self.__config_loader.get_tv_ids_list()
        else:
            column_number = (math.floor((self.__ticks - 1) / num_columns) % num_columns)
            row_number = ((self.__ticks - 1) % num_rows)
            tv_ids = self.__get_tv_ids_in_row_column_intersection(row_number, column_number)

        if self.__ticks == 0:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
        elif math.floor((self.__ticks - 1) / (num_rows * num_columns)) % 2 == 0:
            display_mode = DisplayMode.DISPLAY_MODE_TILE
        else:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN

        display_mode_by_tv_id = {}
        for tv_id in tv_ids:
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id

    # TODO use formula for spiral instead of hardcoding.
    def __get_display_modes_for_spiral(self):
        num_rows = self.__config_loader.get_num_wall_rows()
        num_columns = self.__config_loader.get_num_wall_columns()

        if self.__ticks == 0:
            tv_ids = self.__config_loader.get_tv_ids_list()
        else:
            # pause for N seconds after each spiral cycle completes
            num_ticks_to_pause_at_cycle_end = self.__ticks_per_second * 1
            ticks_per_cycle = (num_rows * num_columns + num_ticks_to_pause_at_cycle_end)
            adjusted_tick = (self.__ticks - 1)
            if adjusted_tick % ticks_per_cycle == 0:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(0, 0)
            elif adjusted_tick % ticks_per_cycle == 1:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(0, 1)
            elif adjusted_tick % ticks_per_cycle == 2:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(0, 2)
            elif adjusted_tick % ticks_per_cycle == 3:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(1, 2)
            elif adjusted_tick % ticks_per_cycle == 4:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(2, 2)
            elif adjusted_tick % ticks_per_cycle == 5:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(2, 1)
            elif adjusted_tick % ticks_per_cycle == 6:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(2, 0)
            elif adjusted_tick % ticks_per_cycle == 7:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(1, 0)
            elif adjusted_tick % ticks_per_cycle == 8:
                tv_ids = self.__get_tv_ids_in_row_column_intersection(1, 1)
            else:
                tv_ids = [] # pause at end of cycle

        if self.__ticks == 0:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN
        elif math.floor(adjusted_tick / ticks_per_cycle) % 2 == 0:
            display_mode = DisplayMode.DISPLAY_MODE_TILE
        else:
            display_mode = DisplayMode.DISPLAY_MODE_FULLSCREEN

        display_mode_by_tv_id = {}
        for tv_id in tv_ids:
            display_mode_by_tv_id[tv_id] = display_mode
        return display_mode_by_tv_id

    def __get_tv_ids_in_row_column_intersection(self, row_number, column_number):
        column_tv_ids = self.__config_loader.get_wall_columns()[column_number]
        row_tv_ids = self.__config_loader.get_wall_rows()[row_number]
        row_column_intersection_tv_ids = []
        for tv_id in column_tv_ids:
            if tv_id in row_tv_ids:
                row_column_intersection_tv_ids.append(tv_id)
        return row_column_intersection_tv_ids
