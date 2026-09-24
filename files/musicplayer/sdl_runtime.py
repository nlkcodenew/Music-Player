import ctypes
import glob
import os
from ctypes import POINTER, Structure, Union, c_char_p, c_double, c_int, c_int16, c_int32, c_uint8, c_uint16, c_uint32, c_void_p

from .diagnostics import LIBRARIES, library_candidates


SDL_INIT_AUDIO = 0x00000010
SDL_INIT_VIDEO = 0x00000020
SDL_INIT_JOYSTICK = 0x00000200
SDL_INIT_GAMECONTROLLER = 0x00002000
SDL_WINDOW_FULLSCREEN = 0x00000001
SDL_WINDOW_SHOWN = 0x00000004
SDL_RENDERER_SOFTWARE = 0x00000001
SDL_RENDERER_ACCELERATED = 0x00000002
SDL_RENDERER_PRESENTVSYNC = 0x00000004
SDL_QUIT = 0x100
SDL_KEYDOWN = 0x300
SDL_KEYUP = 0x301
SDL_JOYHATMOTION = 0x602
SDL_JOYBUTTONDOWN = 0x603
SDL_JOYBUTTONUP = 0x604
SDL_CONTROLLERAXISMOTION = 0x650
SDL_CONTROLLERBUTTONDOWN = 0x651
SDL_CONTROLLERBUTTONUP = 0x652
AUDIO_S16SYS = 0x8010
MIX_MAX_VOLUME = 128
MIX_INIT_FLAC = 0x00000001
MIX_INIT_MP3 = 0x00000008
MIX_INIT_OGG = 0x00000010
MIX_INIT_OPUS = 0x00000040


class SDL_Rect(Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


class SDL_Color(Structure):
    _fields_ = [("r", c_uint8), ("g", c_uint8), ("b", c_uint8), ("a", c_uint8)]


class SDL_DisplayMode(Structure):
    _fields_ = [("format", c_uint32), ("w", c_int), ("h", c_int), ("refresh_rate", c_int), ("driverdata", c_void_p)]


class SDL_Keysym(Structure):
    _fields_ = [("scancode", c_int), ("sym", c_int32), ("mod", c_uint16), ("unused", c_uint32)]


class SDL_KeyboardEvent(Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("windowID", c_uint32),
        ("state", c_uint8), ("repeat", c_uint8), ("padding2", c_uint8),
        ("padding3", c_uint8), ("keysym", SDL_Keysym),
    ]


class SDL_ControllerButtonEvent(Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int32),
        ("button", c_uint8), ("state", c_uint8), ("padding1", c_uint8),
        ("padding2", c_uint8),
    ]


class SDL_ControllerAxisEvent(Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int32),
        ("axis", c_uint8), ("padding1", c_uint8), ("padding2", c_uint8),
        ("padding3", c_uint8), ("value", c_int16), ("padding4", c_uint16),
    ]


class SDL_JoyButtonEvent(Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int32),
        ("button", c_uint8), ("state", c_uint8), ("padding1", c_uint8),
        ("padding2", c_uint8),
    ]


class SDL_JoyHatEvent(Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("which", c_int32),
        ("hat", c_uint8), ("value", c_uint8), ("padding1", c_uint8),
        ("padding2", c_uint8),
    ]


class SDL_Event(Union):
    _fields_ = [
        ("type", c_uint32), ("key", SDL_KeyboardEvent),
        ("cbutton", SDL_ControllerButtonEvent), ("caxis", SDL_ControllerAxisEvent),
        ("jbutton", SDL_JoyButtonEvent), ("jhat", SDL_JoyHatEvent),
        ("padding", c_uint8 * 56),
    ]


class SDL_Surface(Structure):
    _fields_ = [
        ("flags", c_uint32), ("format", c_void_p), ("w", c_int),
        ("h", c_int), ("pitch", c_int), ("pixels", c_void_p),
    ]


def _load(paths, key):
    errors = []
    for candidate in library_candidates(paths, LIBRARIES[key]):
        try:
            return ctypes.CDLL(candidate)
        except OSError as error:
            errors.append("%s: %s" % (candidate, error))
    raise RuntimeError("cannot load %s\n%s" % (key, "\n".join(errors)))


def _bind(library, name, argtypes=None, restype=c_int, required=True):
    try:
        function = getattr(library, name)
    except AttributeError:
        if required:
            raise RuntimeError("missing symbol %s" % name)
        return None
    function.argtypes = argtypes
    function.restype = restype
    return function


class SDLRuntime:
    def __init__(self, paths):
        self.paths = paths
        self.sdl = _load(paths, "sdl2")
        self.ttf = _load(paths, "sdl2_ttf")
        self.mixer = _load(paths, "sdl2_mixer")
        self.controllers = []
        self.joysticks = []
        self._bind_functions()

    def _bind_functions(self):
        sdl = self.sdl
        self.SDL_Init = _bind(sdl, "SDL_Init", [c_uint32])
        self.SDL_Quit = _bind(sdl, "SDL_Quit", [], None)
        self.SDL_GetError = _bind(sdl, "SDL_GetError", [], c_char_p)
        self.SDL_GetCurrentDisplayMode = _bind(sdl, "SDL_GetCurrentDisplayMode", [c_int, POINTER(SDL_DisplayMode)])
        self.SDL_GetNumAudioDevices = _bind(sdl, "SDL_GetNumAudioDevices", [c_int], required=False)
        self.SDL_GetAudioDeviceName = _bind(sdl, "SDL_GetAudioDeviceName", [c_int, c_int], c_char_p, required=False)
        self.SDL_CreateWindow = _bind(sdl, "SDL_CreateWindow", [c_char_p, c_int, c_int, c_int, c_int, c_uint32], c_void_p)
        self.SDL_DestroyWindow = _bind(sdl, "SDL_DestroyWindow", [c_void_p], None)
        self.SDL_CreateRenderer = _bind(sdl, "SDL_CreateRenderer", [c_void_p, c_int, c_uint32], c_void_p)
        self.SDL_DestroyRenderer = _bind(sdl, "SDL_DestroyRenderer", [c_void_p], None)
        self.SDL_SetRenderDrawColor = _bind(sdl, "SDL_SetRenderDrawColor", [c_void_p, c_uint8, c_uint8, c_uint8, c_uint8])
        self.SDL_RenderClear = _bind(sdl, "SDL_RenderClear", [c_void_p])
        self.SDL_RenderFillRect = _bind(sdl, "SDL_RenderFillRect", [c_void_p, POINTER(SDL_Rect)])
        self.SDL_RenderCopy = _bind(sdl, "SDL_RenderCopy", [c_void_p, c_void_p, POINTER(SDL_Rect), POINTER(SDL_Rect)])
        self.SDL_RenderPresent = _bind(sdl, "SDL_RenderPresent", [c_void_p], None)
        self.SDL_CreateTextureFromSurface = _bind(sdl, "SDL_CreateTextureFromSurface", [c_void_p, POINTER(SDL_Surface)], c_void_p)
        self.SDL_DestroyTexture = _bind(sdl, "SDL_DestroyTexture", [c_void_p], None)
        self.SDL_FreeSurface = _bind(sdl, "SDL_FreeSurface", [POINTER(SDL_Surface)], None)
        self.SDL_PollEvent = _bind(sdl, "SDL_PollEvent", [POINTER(SDL_Event)])
        self.SDL_Delay = _bind(sdl, "SDL_Delay", [c_uint32], None)
        self.SDL_NumJoysticks = _bind(sdl, "SDL_NumJoysticks", [])
        self.SDL_IsGameController = _bind(sdl, "SDL_IsGameController", [c_int])
        self.SDL_GameControllerOpen = _bind(sdl, "SDL_GameControllerOpen", [c_int], c_void_p)
        self.SDL_GameControllerClose = _bind(sdl, "SDL_GameControllerClose", [c_void_p], None)
        self.SDL_JoystickOpen = _bind(sdl, "SDL_JoystickOpen", [c_int], c_void_p)
        self.SDL_JoystickClose = _bind(sdl, "SDL_JoystickClose", [c_void_p], None)

        self.TTF_Init = _bind(self.ttf, "TTF_Init", [])
        self.TTF_Quit = _bind(self.ttf, "TTF_Quit", [], None)
        self.TTF_OpenFont = _bind(self.ttf, "TTF_OpenFont", [c_char_p, c_int], c_void_p)
        self.TTF_CloseFont = _bind(self.ttf, "TTF_CloseFont", [c_void_p], None)
        self.TTF_RenderUTF8_Blended = _bind(self.ttf, "TTF_RenderUTF8_Blended", [c_void_p, c_char_p, SDL_Color], POINTER(SDL_Surface))
        self.TTF_SizeUTF8 = _bind(self.ttf, "TTF_SizeUTF8", [c_void_p, c_char_p, POINTER(c_int), POINTER(c_int)])

        self.Mix_Init = _bind(self.mixer, "Mix_Init", [c_int], required=False)
        self.Mix_Quit = _bind(self.mixer, "Mix_Quit", [], None, required=False)
        self.Mix_OpenAudio = _bind(self.mixer, "Mix_OpenAudio", [c_int, c_uint16, c_int, c_int])
        self.Mix_OpenAudioDevice = _bind(
            self.mixer, "Mix_OpenAudioDevice",
            [c_int, c_uint16, c_int, c_int, c_char_p, c_int], required=False,
        )
        self.Mix_CloseAudio = _bind(self.mixer, "Mix_CloseAudio", [], None)
        self.Mix_LoadMUS = _bind(self.mixer, "Mix_LoadMUS", [c_char_p], c_void_p)
        self.Mix_FreeMusic = _bind(self.mixer, "Mix_FreeMusic", [c_void_p], None)
        self.Mix_PlayMusic = _bind(self.mixer, "Mix_PlayMusic", [c_void_p, c_int])
        self.Mix_HaltMusic = _bind(self.mixer, "Mix_HaltMusic", [])
        self.Mix_PauseMusic = _bind(self.mixer, "Mix_PauseMusic", [], None)
        self.Mix_ResumeMusic = _bind(self.mixer, "Mix_ResumeMusic", [], None)
        self.Mix_PausedMusic = _bind(self.mixer, "Mix_PausedMusic", [])
        self.Mix_PlayingMusic = _bind(self.mixer, "Mix_PlayingMusic", [])
        self.Mix_VolumeMusic = _bind(self.mixer, "Mix_VolumeMusic", [c_int])
        self.Mix_SetMusicPosition = _bind(self.mixer, "Mix_SetMusicPosition", [c_double], required=False)
        self.Mix_GetMusicPosition = _bind(self.mixer, "Mix_GetMusicPosition", [c_void_p], c_double, required=False)
        self.Mix_MusicDuration = _bind(self.mixer, "Mix_MusicDuration", [c_void_p], c_double, required=False)
        self.Mix_SetPostMix = _bind(
            self.mixer, "Mix_SetPostMix", [c_void_p, c_void_p], None, required=False
        )

    def error(self):
        value = self.SDL_GetError()
        return value.decode("utf-8", "replace") if value else "unknown SDL error"

    def open_inputs(self):
        for index in range(max(0, self.SDL_NumJoysticks())):
            if self.SDL_IsGameController(index):
                controller = self.SDL_GameControllerOpen(index)
                if controller:
                    self.controllers.append(controller)
                    continue
            joystick = self.SDL_JoystickOpen(index)
            if joystick:
                self.joysticks.append(joystick)

    def close_inputs(self):
        for controller in self.controllers:
            self.SDL_GameControllerClose(controller)
        for joystick in self.joysticks:
            self.SDL_JoystickClose(joystick)
        self.controllers = []
        self.joysticks = []

    def audio_devices(self):
        if not self.SDL_GetNumAudioDevices or not self.SDL_GetAudioDeviceName:
            return []
        devices = []
        for index in range(max(0, self.SDL_GetNumAudioDevices(0))):
            value = self.SDL_GetAudioDeviceName(index, 0)
            if value:
                name = value.decode("utf-8", "replace")
                if name not in devices:
                    devices.append(name)
        return devices


def font_candidates(paths):
    candidates = [
        os.path.join(paths.app_dir, "assets", "fallback.ttf"),
        os.path.join(paths.sdcard_path, "System", "resources", "DejaVuSans.ttf"),
        os.path.join(paths.sdcard_path, "App", "PyUI", "fonts", "BeVietnamPro-Regular.ttf"),
        os.path.join(paths.sdcard_path, "spruce", "Font Files", "Noto.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    candidates.extend(glob.glob("/usr/trimui/res/*.ttf"))
    return [candidate for candidate in candidates if os.path.isfile(candidate)]
