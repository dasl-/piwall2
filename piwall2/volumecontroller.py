import subprocess
import re
import math

# Gets and sets alsa volume
class VolumeController:

    """
    sudo amixer cset numid=1 96.24%
    numid=1,iface=MIXER,name='Headphone Playback Volume'
      ; type=INTEGER,access=rw---R--,values=1,min=-10239,max=400,step=0
      : values=0
      | dBscale-min=-102.39dB,step=0.01dB,mute=1

    Setting 96.24% is equivalent to 0dB. Anything higher may result in clipping.
    """
    __LIMITED_MAX_VOL_VAL = 0

    # amixer output: ; type=INTEGER,access=rw---R--,values=1,min=-10239,max=400,step=0
    # These values are in millibels.
    __GLOBAL_MIN_VOL_VAL = -10239
    __GLOBAL_MAX_VOL_VAL = 400

    # gets a perceptual loudness %
    # returns a float in the range [0, 100]
    def get_vol_pct(self):
        mb_level = self.get_vol_millibels()
        if mb_level <= self.__GLOBAL_MIN_VOL_VAL:
            return 0

        # convert from decibel attenuation amount to perceptual loudness %
        # see: http://www.sengpielaudio.com/calculator-levelchange.htm
        db_level = mb_level / 100
        vol_pct = math.pow(2, (db_level / 10)) * 100
        vol_pct = max(0, vol_pct)
        vol_pct = min(100, vol_pct)
        return vol_pct

    # takes a perceptual loudness %.
    # vol_pct should be a float in the range [0, 100]
    def set_vol_pct(self, vol_pct):
        if (vol_pct <= 0):
            db_level = self.__GLOBAL_MIN_VOL_VAL / 100
        else:
            # get the decibel adjustment required for the human perceived loudness %.
            # see: http://www.sengpielaudio.com/calculator-levelchange.htm
            db_level = 10 * math.log(vol_pct / 100, 2)

        db_level = max(self.__GLOBAL_MIN_VOL_VAL / 100, db_level)
        db_level = min(self.__LIMITED_MAX_VOL_VAL, db_level)

        pct_to_set = (((db_level * 100) - self.__GLOBAL_MIN_VOL_VAL) / (self.__GLOBAL_MAX_VOL_VAL - self.__GLOBAL_MIN_VOL_VAL)) * 100
        subprocess.check_output(('amixer', 'cset', 'numid=1', '{}%'.format(pct_to_set)))

    # Return volume in millibels. Returns an integer in the range [self.__GLOBAL_MIN_VOL_VAL, 0]
    def get_vol_millibels(self):
        res = subprocess.check_output(('amixer', 'cget', 'numid=1')).decode("utf-8")
        m = re.search(r" values=(-?\d+)", res, re.MULTILINE)
        if m is None:
            return self.__GLOBAL_MIN_VOL_VAL

        mb_level = int(m.group(1))
        mb_level = max(self.__GLOBAL_MIN_VOL_VAL, mb_level)
        mb_level = min(0, mb_level)
        return mb_level
