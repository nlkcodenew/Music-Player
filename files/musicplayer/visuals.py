import math
import struct
import time

try:
    import audioop
except ImportError:
    audioop = None

BAND_COUNT = 14
FFT_SIZE = 256
TAP_INTERVAL = 0.07
BEAT_COOLDOWN = 0.35
BEAT_RATIO = 1.35


def _mono_samples(pcm, count):
    if not pcm:
        return [0.0] * count
    if audioop is not None:
        try:
            mono = audioop.tomono(pcm, 2, 0.5, 0.5)
        except Exception:
            mono = pcm
    else:
        mono = pcm
    frames = len(mono) // 2
    if frames <= 0:
        return [0.0] * count
    stride = max(1, frames // count)
    out = []
    for i in range(count):
        index = (i * stride) % frames
        value = struct.unpack_from("<h", mono, index * 2)[0]
        out.append(value / 32768.0)
    return out


def _fft_magnitudes(samples):
    n = len(samples)
    windowed = []
    for i, s in enumerate(samples):
        w = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / n)
        windowed.append(complex(s * w, 0.0))
    a = windowed[:]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wlen = complex(math.cos(ang), math.sin(ang))
        for i in range(0, n, length):
            w = 1.0 + 0.0j
            half = length // 2
            for k in range(half):
                u = a[i + k]
                v = a[i + k + half] * w
                a[i + k] = u + v
                a[i + k + half] = u - v
                w *= wlen
        length *= 2
    scale = 2.0 / n
    return [abs(c) * scale for c in a[: n // 2]]


def _log_band_edges(band_count, bin_count):
    edges = []
    for i in range(band_count + 1):
        frac = i / band_count
        edge = 1 + int((bin_count - 1) * (math.exp(frac * 2.4) - 1.0) / (math.exp(2.4) - 1.0))
        edges.append(min(bin_count, max(1, edge)))
    return edges


class SpectrumAnalyser:
    PEAK_FALL = 0.045

    def __init__(self, sample_rate=44100, bands=BAND_COUNT):
        self.sample_rate = max(8000, int(sample_rate or 44100))
        self.bands = max(4, min(24, int(bands or BAND_COUNT)))
        self.levels = [0.0] * self.bands
        self.peaks = [0.0] * self.bands
        self.rms = 0.0
        self.last_beat = 0.0
        self._last_tap = 0.0
        self._bass_history = []

    def set_sample_rate(self, sample_rate):
        self.sample_rate = max(8000, int(sample_rate))
        self.reset()

    def reset(self):
        self.levels = [0.0] * self.bands
        self.peaks = [0.0] * self.bands
        self.rms = 0.0
        self.last_beat = 0.0
        self._last_tap = 0.0
        self._bass_history = []

    def _rms_of(self, pcm):
        if not pcm:
            return 0.0
        if audioop is not None:
            try:
                return min(1.0, audioop.rms(pcm, 2) / 32768.0)
            except Exception:
                pass
        frames = len(pcm) // 2
        if frames <= 0:
            return 0.0
        step = max(1, frames // 256)
        total = 0.0
        used = 0
        for i in range(0, frames, step):
            value = struct.unpack_from("<h", pcm, i * 2)[0] / 32768.0
            total += value * value
            used += 1
        if used <= 0:
            return 0.0
        return min(1.0, math.sqrt(total / used))

    def offer(self, pcm):
        now = time.monotonic()
        try:
            instant = self._rms_of(pcm)
        except Exception:
            return
        self.rms = 0.65 * self.rms + 0.35 * instant
        if now - self._last_tap < TAP_INTERVAL:
            return
        self._last_tap = now
        try:
            samples = _mono_samples(pcm, FFT_SIZE)
            mags = _fft_magnitudes(samples)
            edges = _log_band_edges(self.bands, len(mags))
            targets = []
            for b in range(self.bands):
                lo = edges[b]
                hi = max(lo + 1, edges[b + 1])
                band = mags[lo:hi]
                energy = sum(band) / max(1, len(band)) if band else 0.0
                targets.append(min(1.0, energy * 6.0))
            for i, target in enumerate(targets):
                current = self.levels[i]
                if target > current:
                    self.levels[i] = target
                else:
                    self.levels[i] = current * 0.62 + target * 0.38
                if self.levels[i] >= self.peaks[i]:
                    self.peaks[i] = self.levels[i]
                else:
                    self.peaks[i] = max(0.0, self.peaks[i] - self.PEAK_FALL)
            bass = (self.levels[0] + self.levels[1]) / 2.0
            self._bass_history.append(bass)
            if len(self._bass_history) > 14:
                self._bass_history.pop(0)
            if len(self._bass_history) >= 5:
                avg = sum(self._bass_history[:-1]) / max(1, len(self._bass_history) - 1)
                if bass > 0.22 and avg > 0.02 and bass > avg * BEAT_RATIO:
                    if now - self.last_beat > BEAT_COOLDOWN:
                        self.last_beat = now
        except Exception:
            pass

    def snapshot(self):
        now = time.monotonic()
        beat = (now - self.last_beat) < 0.16
        return (tuple(self.levels), self.rms, beat)

    def snapshot_peaks(self):
        return tuple(self.peaks)

    def decay(self):
        self.levels = [v * 0.7 for v in self.levels]
        self.peaks = [v * 0.85 for v in self.peaks]
        self.rms *= 0.7