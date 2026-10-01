import time

from .sdl_runtime import (
    SDL_CONTROLLERAXISMOTION,
    SDL_CONTROLLERBUTTONDOWN,
    SDL_CONTROLLERBUTTONUP,
    SDL_JOYAXISMOTION,
    SDL_JOYBUTTONDOWN,
    SDL_JOYBUTTONUP,
    SDL_JOYHATMOTION,
    SDL_KEYDOWN,
    SDL_KEYUP,
)


CONTROLLER_BUTTONS = {
    0: "b",
    1: "a",
    2: "y",
    3: "x",
    4: "select",
    6: "start",
    9: "l1",
    10: "r1",
    11: "prev",
    12: "next",
    13: "left",
    14: "right",
}

JOYSTICK_BUTTONS = {
    0: "b",
    1: "a",
    2: "y",
    3: "x",
    4: "l1",
    5: "r1",
    6: "l1",
    7: "r1",
    8: "select",
    9: "start",
}

KEYBOARD_SCANCODES = {
    40: "a",
    41: "b",
    44: "start",
    42: "select",
    27: "x",
    28: "y",
    75: "l1",
    78: "r1",
    80: "left",
    79: "right",
    82: "stick_up",
    81: "stick_down",
}

STICK_DEADZONE = 8000
STICK_INITIAL_DELAY = 0.35
STICK_REPEAT_INTERVAL = 0.20


class InputState:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.held = set()
        self.edges = []
        self.stick_held = None
        self.stick_repeat_at = 0.0

    def _set(self, action, down):
        if not action:
            return
        if down and action not in self.held:
            self.edges.append(action)
            self.held.add(action)
        elif not down:
            self.held.discard(action)

    def _stick(self, direction):
        if direction == self.stick_held:
            return
        if self.stick_held:
            self.held.discard(self.stick_held)
        self.stick_held = direction
        if direction:
            self.edges.append(direction)
            self.held.add(direction)
            try:
                now = self.clock()
            except Exception:
                now = 0.0
            self.stick_repeat_at = now + STICK_INITIAL_DELAY

    @staticmethod
    def _stick_direction(value):
        if value < -STICK_DEADZONE:
            return "stick_up"
        if value > STICK_DEADZONE:
            return "stick_down"
        return None

    def feed(self, event):
        event_type = event.type
        if event_type in (SDL_KEYDOWN, SDL_KEYUP):
            if event.key.repeat:
                return
            self._set(KEYBOARD_SCANCODES.get(event.key.keysym.scancode), event_type == SDL_KEYDOWN)
        elif event_type in (SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP):
            self._set(CONTROLLER_BUTTONS.get(event.cbutton.button), event_type == SDL_CONTROLLERBUTTONDOWN)
        elif event_type == SDL_CONTROLLERAXISMOTION:
            if event.caxis.axis == 4:
                self._set("l2", event.caxis.value > 8000)
            elif event.caxis.axis == 5:
                self._set("r2", event.caxis.value > 8000)
            elif event.caxis.axis == 1:
                self._stick(self._stick_direction(event.caxis.value))
        elif event_type in (SDL_JOYBUTTONDOWN, SDL_JOYBUTTONUP):
            self._set(JOYSTICK_BUTTONS.get(event.jbutton.button), event_type == SDL_JOYBUTTONDOWN)
        elif event_type == SDL_JOYAXISMOTION:
            if event.jaxis.axis == 1:
                self._stick(self._stick_direction(event.jaxis.value))
        elif event_type == SDL_JOYHATMOTION:
            value = event.jhat.value
            self._set("prev", bool(value & 0x01))
            self._set("right", bool(value & 0x02))
            self._set("next", bool(value & 0x04))
            self._set("left", bool(value & 0x08))

    def poll(self):
        try:
            now = self.clock()
        except Exception:
            now = 0.0
        if self.stick_held and now >= self.stick_repeat_at:
            self.edges.append(self.stick_held)
            self.stick_repeat_at = now + STICK_REPEAT_INTERVAL
        edges = self.edges
        self.edges = []
        return edges
