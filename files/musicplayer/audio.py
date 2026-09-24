import ctypes
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

MUSIC_FINISHED_CALLBACK = ctypes.CFUNCTYPE(None)


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
        self.music_finished = False
        self.finished_callback = None
        self.last_state_log = 0.0

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
        self._install_finished_callback()
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

    def _install_finished_callback(self):
        hook = getattr(self.runtime, "Mix_HookMusicFinished", None)
        if not hook:
            return

        @MUSIC_FINISHED_CALLBACK
        def finished():
            self.music_finished = True

        self.finished_callback = finished
        hook(ctypes.cast(finished, ctypes.c_void_p))

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
        hook = getattr(self.runtime, "Mix_HookMusicFinished", None)
        if hook and self.finished_callback:
            hook(None)
        self.finished_callback = None
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
        self.music_finished = False
        self.started_at = time.monotonic()
        self.position_base = 0.0
        self.paused_at = 0.0
        self.error = ""
        self.settings.set("last_track", track.path)
        get_logger().info(
            "playback started index=%d title=%r format=%s tracks=%d duration=%.3f repeat=%s shuffle=%s",
            index, track.title, track.extension, len(self.tracks), self.duration(),
            self.settings.get("repeat"), self.settings.get("shuffle"),
        )
        return True

    def stop(self):
        if self.music:
            track = self.current
            get_logger().info(
                "playback stopping index=%d title=%r position=%.3f duration=%.3f",
                self.index, track.title if track else "", self.position(), self.duration(),
            )
            self.runtime.Mix_HaltMusic()
            self.runtime.Mix_FreeMusic(self.music)
        self.music = None
        self.started = False
        self.music_finished = False

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
            get_logger().info("automatic navigation repeats current track index=%d", self.index)
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
        get_logger().info(
            "playback advance from=%d target=%d automatic=%s repeat=%s shuffle=%s",
            self.index, target, automatic, self.settings.get("repeat"), self.settings.get("shuffle"),
        )
        if target < 0:
            self.stop()
            return False
        return self.play(target)

    def update(self):
        if not self.audio_ready or not self.started or not self.music:
            return
        now = time.monotonic()
        if now - self.last_state_log >= 10.0:
            self.last_state_log = now
            track = self.current
            get_logger().info(
                "playback state index=%d title=%r position=%.3f duration=%.3f playing=%s paused=%s "
                "finished=%s repeat=%s shuffle=%s",
                self.index, track.title if track else "", self.position(), self.duration(),
                bool(self.runtime.Mix_PlayingMusic()), bool(self.runtime.Mix_PausedMusic()),
                self.music_finished, self.settings.get("repeat"), self.settings.get("shuffle"),
            )
        finished = self.music_finished
        if not getattr(self.runtime, "Mix_HookMusicFinished", None):
            finished = not self.runtime.Mix_PausedMusic() and not self.runtime.Mix_PlayingMusic()
        if finished:
            self.music_finished = False
            track = self.current
            get_logger().info(
                "playback finished index=%d title=%r position=%.3f duration=%.3f",
                self.index, track.title if track else "", self.position(), self.duration(),
            )
            self.advance(True, automatic=True)
