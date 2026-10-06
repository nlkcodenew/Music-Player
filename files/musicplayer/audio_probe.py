# -*- coding: utf-8 -*-
"""Subprocess probe for audio opening.

Some TrimUI firmwares combine the default ALSA device with a KV/AirPlay
loopback. Opening it with certain SDL/ALSA parameters can abort the whole
process with ``snd_mask_leave: Assertion ...``. That abort cannot be caught
in Python, so the parent process runs this probe first and only opens the
configuration that this probe managed to open.
"""

import os
import sys

from .paths import RuntimePaths
from .sdl_runtime import (
    MIX_INIT_FLAC,
    MIX_INIT_MP3,
    MIX_INIT_OGG,
    MIX_INIT_OPUS,
    SDL_INIT_AUDIO,
    SDLRuntime,
)


def probe(device, app_dir, only=None):
    paths = RuntimePaths.discover(app_dir=app_dir, environ=os.environ)
    runtime = SDLRuntime(paths)
    flags = MIX_INIT_FLAC | MIX_INIT_MP3 | MIX_INIT_OGG | MIX_INIT_OPUS
    try:
        if runtime.Mix_Init:
            runtime.Mix_Init(flags)
        if runtime.SDL_Init(SDL_INIT_AUDIO) != 0:
            print("FAIL_INIT")
            return 2
        encoded = device.encode("utf-8") if device and device != "default" else None
        from .audio import AUDIO_CONFIGS, AUDIO_S16SYS
        from .sdl_runtime import (
            SDL_AUDIO_ALLOW_FREQUENCY_CHANGE,
            SDL_AUDIO_ALLOW_SAMPLES_CHANGE,
        )
        allowed = SDL_AUDIO_ALLOW_FREQUENCY_CHANGE | SDL_AUDIO_ALLOW_SAMPLES_CHANGE
        configs = AUDIO_CONFIGS
        if only is not None:
            try:
                freq, buf = int(only[0]), int(only[1])
                configs = [config for config in configs if config == (freq, buf)] or AUDIO_CONFIGS
            except Exception:
                configs = AUDIO_CONFIGS
        for frequency, buffer_size in configs:
            if runtime.Mix_OpenAudioDevice:
                result = runtime.Mix_OpenAudioDevice(
                    frequency, AUDIO_S16SYS, 2, buffer_size, encoded, allowed
                )
            else:
                result = runtime.Mix_OpenAudio(frequency, AUDIO_S16SYS, 2, buffer_size)
            if result == 0:
                print("OK %d %d" % (frequency, buffer_size))
                try:
                    runtime.Mix_CloseAudio()
                    if runtime.Mix_Quit:
                        runtime.Mix_Quit()
                    runtime.SDL_Quit()
                except Exception:
                    pass
                os._exit(0)
            try:
                err = runtime.error()
            except Exception:
                err = "error"
            print("FAIL %d %d %s" % (frequency, buffer_size, err))
        return 2
    finally:
        try:
            runtime.SDL_Quit()
        except Exception:
            pass


def main(argv):
    if len(argv) < 3:
        print("usage: audio_probe.py <device> <app_dir> [freq buffer]")
        return 2
    only = None
    if len(argv) >= 5:
        only = (argv[3], argv[4])
    return probe(argv[1], argv[2], only)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
