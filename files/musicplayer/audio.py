import random
import time

from .audio_output import choose_audio_device
from .equalizer import Equalizer
from .logger import get_logger
from .sdl_runtime import (
    AUDIO_S16SYS,
    MIX_INIT_FLAC,
    MIX_INIT_MP3,
    MIX_INIT_OGG,
    MIX_INIT_OPUS,
    MIX_MAX_VOLUME,
    SDL_AUDIO_ALLOW_FREQUENCY_CHANGE,
    SDL_AUDIO_ALLOW_SAMPLES_CHANGE,
)

AUDIO_CONFIGS = (
    (44100, 1024),
    (48000, 1024),
    (44100, 2048),
    (48000, 2048),
    (22050, 1024),
    (16000, 512),
)


class AudioPlayer:
    def __init__(self, runtime, tracks, settings):
        self.runtime = runtime
        self.tracks = tracks
        self.settings = settings
        self.index = -1
        self.music = None
        self.started = False
        self.started_at = 0.0
        self.position_base = 0.0
        self.paused_at = 0.0
        self.error = ""
        self.output_device = "System / Bluetooth"
        self.available_decoders = 0
        self.equalizer = Equalizer(runtime, settings)
        self.output_warning = ""
        self.audio_ready = False
        self.sample_rate = 0

    def initialize(self):
        flags = MIX_INIT_FLAC | MIX_INIT_MP3 | MIX_INIT_OGG | MIX_INIT_OPUS
        if self.runtime.Mix_Init:
            self.available_decoders = self.runtime.Mix_Init(flags)
            get_logger().info(
                "SDL_mixer decoders requested=0x%x available=0x%x",
                flags, self.available_decoders,
            )
            if not self.available_decoders & MIX_INIT_FLAC:
                self.output_warning = "FLAC decoder unavailable; other formats still work"
        devices = self.runtime.audio_devices()
        selected = choose_audio_device(devices, self.settings.get("audio_output"))
        if self.settings.get("audio_output") == "usb" and not selected:
            self.output_warning = "USB DAC not detected; using system audio"
        attempts = []
        if selected:
            self.audio_ready = self._open_audio(selected, attempts)
            if self.audio_ready:
                self.output_device = selected
            else:
                self.output_warning = "USB DAC could not open; using system audio"
        if not self.audio_ready:
            self.audio_ready = self._open_audio(None, attempts)
        if not self.audio_ready:
            detail = attempts[-1] if attempts else self.runtime.error()
            self.output_warning = "Audio unavailable; disconnect/reconnect output and restart"
            self.error = self.output_warning
            get_logger().error("audio initialization unavailable attempts=%s", attempts)
            return False
        spec = self.runtime.mixer_spec()
        self.sample_rate = spec[0] if spec else 44100
        self.equalizer.set_sample_rate(self.sample_rate)
        get_logger().info(
            "audio output=%s mode=%s devices=%s spec=%s",
            self.output_device, self.settings.get("audio_output"), devices, spec,
        )
        if self.equalizer.sync():
            get_logger().info(
                "equalizer preset=%s active=%s", self.equalizer.preset, self.equalizer.installed
            )
        else:
            get_logger().warning("equalizer unavailable on this Python/SDL_mixer runtime")
        self.set_volume(int(self.settings.get("volume")))
        return True

    def _open_audio(self, device, attempts):
        encoded = device.encode("utf-8") if device else None
        allowed_changes = SDL_AUDIO_ALLOW_FREQUENCY_CHANGE | SDL_AUDIO_ALLOW_SAMPLES_CHANGE
        for frequency, buffer_size in AUDIO_CONFIGS:
            if self.runtime.Mix_OpenAudioDevice:
                result = self.runtime.Mix_OpenAudioDevice(
                    frequency, AUDIO_S16SYS, 2, buffer_size, encoded, allowed_changes
                )
            else:
                result = self.runtime.Mix_OpenAudio(
                    frequency, AUDIO_S16SYS, 2, buffer_size
                )
            if result == 0:
                get_logger().info(
                    "audio open succeeded device=%s frequency=%d buffer=%d",
                    device or "default", frequency, buffer_size,
                )
                return True
            error = self.runtime.error()
            attempts.append("%s %d/%d: %s" % (
                device or "default", frequency, buffer_size, error,
            ))
            get_logger().warning("audio open failed: %s", attempts[-1])
        return False

    def close(self):
        self.stop()
        self.equalizer.uninstall()
        if self.audio_ready:
            self.runtime.Mix_CloseAudio()
            self.audio_ready = False
        if self.runtime.Mix_Quit:
            self.runtime.Mix_Quit()

    @property
    def current(self):
        if 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None

    def play(self, index):
        if not self.audio_ready:
            self.error = "Audio unavailable; restart after changing Bluetooth or DAC"
            return False
        if not self.tracks:
            return False
        index %= len(self.tracks)
        self.stop()
        track = self.tracks[index]
        music = self.runtime.Mix_LoadMUS(track.path.encode("utf-8"))
        if not music:
            self.error = "Cannot decode %s: %s" % (track.title, self.runtime.error())
            get_logger().error(
                "decode failed at index=%d format=%s: %s",
                index, track.extension, self.runtime.error(),
            )
            return False
        if self.runtime.Mix_PlayMusic(music, 0) != 0:
            self.runtime.Mix_FreeMusic(music)
            self.error = "Cannot play %s: %s" % (track.title, self.runtime.error())
            get_logger().error(
                "playback start failed at index=%d format=%s: %s",
                index, track.extension, self.runtime.error(),
            )
            return False
        self.music = music
        self.index = index
        self.started = True
        self.started_at = time.monotonic()
        self.position_base = 0.0
        self.paused_at = 0.0
        self.error = ""
        self.settings.set("last_track", track.path)
        get_logger().info("playing index=%d format=%s", index, track.extension)
        return True

    def stop(self):
        if self.music:
            self.runtime.Mix_HaltMusic()
            self.runtime.Mix_FreeMusic(self.music)
        self.music = None
        self.started = False

    def fade_stop(self, steps=10, delay=0.05):
        if not self.music:
            return
        volume = max(0, min(100, int(self.settings.get("volume"))))
        for step in range(steps - 1, -1, -1):
            self.runtime.Mix_VolumeMusic(round(volume * step * MIX_MAX_VOLUME / (steps * 100.0)))
            time.sleep(delay)
        self.stop()
        self.runtime.Mix_VolumeMusic(round(volume * MIX_MAX_VOLUME / 100.0))
        get_logger().info("playback stopped by sleep timer")

    def toggle_pause(self):
        if not self.music:
            return False
        if self.runtime.Mix_PausedMusic():
            self.runtime.Mix_ResumeMusic()
            self.started_at = time.monotonic()
            get_logger().info("playback resumed")
            return False
        else:
            self.position_base = self.position()
            self.runtime.Mix_PauseMusic()
            self.paused_at = self.position_base
            get_logger().info("playback paused")
            return True

    def position(self):
        if not self.music:
            return 0.0
        if self.runtime.Mix_GetMusicPosition:
            native = self.runtime.Mix_GetMusicPosition(self.music)
            if native >= 0:
                return native
        if self.runtime.Mix_PausedMusic():
            return self.paused_at
        return self.position_base + max(0.0, time.monotonic() - self.started_at)

    def duration(self):
        if self.music and self.runtime.Mix_MusicDuration:
            value = self.runtime.Mix_MusicDuration(self.music)
            if value > 0:
                return value
        return 0.0

    def seek(self, delta):
        if not self.music or not self.runtime.Mix_SetMusicPosition:
            self.error = "Seek is unavailable on this firmware mixer"
            return False
        target = max(0.0, self.position() + delta)
        duration = self.duration()
        if duration:
            target = min(target, max(0.0, duration - 0.5))
        if self.runtime.Mix_SetMusicPosition(target) != 0:
            self.error = "This decoder does not support seeking"
            return False
        self.position_base = target
        self.started_at = time.monotonic()
        self.paused_at = target
        self.error = ""
        return True

    def set_volume(self, volume):
        volume = max(0, min(100, volume))
        self.settings.set("volume", volume)
        if self.audio_ready:
            self.runtime.Mix_VolumeMusic(round(volume * MIX_MAX_VOLUME / 100.0))

    def next_index(self, forward=True, automatic=False):
        if not self.tracks:
            return -1
        repeat = self.settings.get("repeat")
        if automatic and repeat == "one" and self.index >= 0:
            return self.index
        if self.settings.get("shuffle") and len(self.tracks) > 1:
            return random.choice([index for index in range(len(self.tracks)) if index != self.index])
        candidate = self.index + (1 if forward else -1)
        if 0 <= candidate < len(self.tracks):
            return candidate
        if repeat == "all" or not automatic:
            return candidate % len(self.tracks)
        return -1

    def advance(self, forward=True, automatic=False):
        target = self.next_index(forward, automatic)
        if target < 0:
            self.stop()
            return False
        return self.play(target)

    def update(self):
        if self.audio_ready and self.started and self.music and not self.runtime.Mix_PausedMusic() and not self.runtime.Mix_PlayingMusic():
            self.advance(True, automatic=True)
