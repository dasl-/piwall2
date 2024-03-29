import subprocess
import re
import math

# Gets and sets alsa volume
#
# On the receivers, we use this to ensure their audio output is at max volume when the receiver
# process starts. Volume adjustments on receivers are made by setting the volume in software
# (in omxplayer). Receiver alsa volume should always be at 100%.
#
# On the broadcaster, we use the alsa volume as a mere state store. The broadcaster is not hooked
# up to any audio output device, yet we set its alsa volume whenever volume adjustments are made
# in the web UI. This is to allow the broadcaster's queue process to read the volume level and set
# it on the receivers. In effect, we use the broadcaster's alsa volume as a form of interprocess
# communication (IPC). It allows the broadcaster's server process to set the volume and the
# broadcaster's queue process can read it.
#
# We tried porting the broadcasters volume state store from this (ab)use of alsa to a sqlite3
# backed state store. With sqlite3, setting the volume took anywhere from 33% - 1000% as long
# as with alsa, and occasionally resulted in `sqlite3.OperationalError: database is locked`
# errors: https://gist.github.com/dasl-/3858c6473aa434f1487372f0a188ca05
class VolumeController:

    # Anything higher than 0 dB may result in clipping.
    __LIMITED_MAX_VOL_VAL = 0

    # amixer output: ; type=INTEGER,access=rw---R--,values=1,min=-10239,max=400,step=0
    # These values are in millibels.
    GLOBAL_MIN_VOL_VAL = -10239
    GLOBAL_MAX_VOL_VAL = 400

    # gets a perceptual loudness %
    # returns a float in the range [0, 100]
    def get_vol_pct(self):
        mb_level = self.get_vol_millibels()
        if mb_level <= self.GLOBAL_MIN_VOL_VAL:
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
        mb_level = round(VolumeController.pct_to_millibels(vol_pct))
        subprocess.check_output(('amixer', 'cset', 'numid=1', '--', str(mb_level)))

    # increments volume percentage by the specified increment. The increment should be a float in the range [0, 100]
    # Returns the new volume percent, which will be a float in the range [0, 100]
    def increment_vol_pct(self, inc = 1):
        old_vol_pct = self.get_vol_pct()
        new_vol_pct = old_vol_pct + inc
        new_vol_pct = max(0, new_vol_pct)
        new_vol_pct = min(100, new_vol_pct)
        self.set_vol_pct(new_vol_pct)
        return new_vol_pct

    # Return volume in millibels. Returns an integer in the range [self.GLOBAL_MIN_VOL_VAL, 0]
    def get_vol_millibels(self):
        res = subprocess.check_output(('amixer', 'cget', 'numid=1')).decode("utf-8")
        m = re.search(r" values=(-?\d+)", res, re.MULTILINE)
        if m is None:
            return self.GLOBAL_MIN_VOL_VAL

        mb_level = int(m.group(1))
        mb_level = max(self.GLOBAL_MIN_VOL_VAL, mb_level)
        mb_level = min(0, mb_level)
        return mb_level

    # Map the volume from [0, 100] to [0, 1]
    @staticmethod
    def normalize_vol_pct(vol_pct):
        vol_pct_normalized = vol_pct / 100
        vol_pct_normalized = max(0, vol_pct_normalized)
        vol_pct_normalized = min(1, vol_pct_normalized)
        return vol_pct_normalized

    # input: [0, 100]
    # output: [self.GLOBAL_MIN_VOL_VAL, 0]
    @staticmethod
    def pct_to_millibels(vol_pct):
        if (vol_pct <= 0):
            mb_level = VolumeController.GLOBAL_MIN_VOL_VAL
        else:
            # get the decibel adjustment required for the human perceived loudness %.
            # see: http://www.sengpielaudio.com/calculator-levelchange.htm
            mb_level = 1000 * math.log(vol_pct / 100, 2)

        mb_level = max(VolumeController.GLOBAL_MIN_VOL_VAL, mb_level)
        mb_level = min(VolumeController.__LIMITED_MAX_VOL_VAL, mb_level)
        return mb_level
