import sys
import types

# Navigation tests inspect requested actions without accessing a real keyboard.
class Keyboard:
    def press(self, key):
        pass

    def release(self, key):
        pass

keyboard = types.ModuleType('pynput.keyboard')
keyboard.Controller = Keyboard
pynput = types.ModuleType('pynput')
pynput.keyboard = keyboard
sys.modules['pynput'] = pynput
sys.modules['pynput.keyboard'] = keyboard
