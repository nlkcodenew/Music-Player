from .sdl_runtime import (
    SDL_CONTROLLERAXISMOTION,
    SDL_CONTROLLERBUTTONDOWN,
    SDL_CONTROLLERBUTTONUP,
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
    11: "up",
    12: "down",
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
    82: "up",
    81: "down",
}


class InputState:
    def __init__(self):
        self.held = set()
        self.edges = []

    def _set(self, action, down):
        if not action:
            return
        if down and action not in self.held:
            self.edges.append(action)
            self.held.add(action)
        elif not down:
            self.held.discard(action)

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
        elif event_type in (SDL_JOYBUTTONDOWN, SDL_JOYBUTTONUP):
            self._set(JOYSTICK_BUTTONS.get(event.jbutton.button), event_type == SDL_JOYBUTTONDOWN)
        elif event_type == SDL_JOYHATMOTION:
            value = event.jhat.value
            self._set("up", bool(value & 0x01))
            self._set("right", bool(value & 0x02))
            self._set("down", bool(value & 0x04))
            self._set("left", bool(value & 0x08))

    def poll(self):
        edges = self.edges
        self.edges = []
        return edges

