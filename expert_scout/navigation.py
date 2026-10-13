"""Use the inherited obstacle rules without sending keys from navigation."""
from modules.auv.navigator.navigator import Navigator


class Navigation(Navigator):
    def _clear_motion_keys(self):
        for key in self._movement_keys:
            self._movement_keys[key] = False
