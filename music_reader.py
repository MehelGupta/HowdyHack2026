"""
music_reader.py - standalone music helper for the Lofi Fish app.

What it does
  * loads a song (mp3 / ogg / wav), finds its length, tempo (BPM) and beats
  * plays / pauses it, and LOOPS it seamlessly
  * changes pitch and speed while it plays (tape style: they move together)
  * tracks beats quietly in the background so the animation can read them later

Needs:  pip3 install pygame numpy

------------------------------------------------------------------------
Quick start in the game
------------------------------------------------------------------------
  reader = MusicReader("music/song.mp3")     # once, before the game loop
  reader.toggle()                            # play / pause button

  # inside the game loop, ONCE per frame:
  reader.update()                            # keeps loop + beat tracking going

  # then read whatever you need (nothing is ever printed):
  reader.just_beat          True only on the frame a beat hit
  reader.total_beats        beats since the song started (keeps counting through loops)
  reader.beat_in_loop       beats so far in the current pass of the song
  reader.loops_played       how many times the song has looped
  reader.beat_phase()       0.0 on the beat -> 1.0 just before the next
  reader.beat_frame(n)      animation frame 0..n-1 that changes on every beat
  reader.time_since_beat()  real seconds since the last beat
  reader.time_to_next_beat()
  reader.beat_history       last 128 beats as (total_beat_number, song_position)

Pitch / speed (all work while playing, the song keeps its place):
  reader.lower_pitch()  reader.raise_pitch()   move by reader.pitch_step semitones
  reader.pitch_step = 4                        change the step size
  reader.set_semitones(-5)  reader.reset_pitch()
  reader.faster()  reader.slower()             move by reader.speed_step percent
  reader.speed_step = 15                       change the step size
  reader.set_speed(1.25)                       jump straight to 1.25x

------------------------------------------------------------------------
Debug in the terminal (nothing prints unless you ask):
  python3 music_reader.py music/yoursong.mp3 [num_frames]
Type h + Enter while it plays to see the commands.
------------------------------------------------------------------------
"""

import os
import time
from collections import deque

import numpy as np
import pygame

# ---------------------------------------------------------------------------
# Beat detection (pure numpy - works on any array of samples)
# ---------------------------------------------------------------------------

HOP = 512      # samples between analysis frames
WINDOW = 1024  # samples per analysis frame
MIN_BPM = 60
MAX_BPM = 160


def detect_beats(samples, sample_rate):
    """
    samples: numpy array, shape (n,) or (n, channels)
    returns: (bpm, beat_times_in_seconds)

    1. Measure how much the sound "jumps" between tiny frames (spectral flux).
    2. Find the repeating gap between jumps (autocorrelation) = tempo.
    3. Slide a beat grid of that spacing over the song and keep the best fit.
    Works best on steady-tempo music, which is most lofi.
    """
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    peak = np.abs(x).max()
    if peak == 0 or len(x) < WINDOW * 4:
        return 0.0, np.array([])
    x = x / peak

    # 1) onset strength
    frames = np.lib.stride_tricks.sliding_window_view(x, WINDOW)[::HOP]
    mags = np.abs(np.fft.rfft(frames * np.hanning(WINDOW), axis=1))
    mags = np.log1p(mags * 10)
    flux = np.maximum(mags[1:] - mags[:-1], 0).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(43) / 43, mode="same")  # remove slow trend
    flux = np.maximum(flux, 0)
    if flux.max() == 0:
        return 0.0, np.array([])
    flux /= flux.max()

    fps = sample_rate / HOP  # analysis frames per second

    # 2) tempo from autocorrelation
    n = len(flux)
    f = np.fft.rfft(flux, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    lo = int(fps * 60 / MAX_BPM)
    hi = int(fps * 60 / MIN_BPM)
    hi = min(hi, n - 2)
    if hi <= lo + 1:
        return 0.0, np.array([])
    lags = np.arange(lo, hi + 1)
    bpms = 60 * fps / lags
    # gently prefer tempos near 90 BPM (typical lofi) to avoid half/double errors
    weight = np.exp(-0.5 * (np.log2(bpms / 90) / 0.7) ** 2)
    best = lags[np.argmax(ac[lags] * weight)]
    a, b, c = ac[best - 1], ac[best], ac[best + 1]
    denom = a - 2 * b + c
    period = best + (0.5 * (a - c) / denom if denom != 0 else 0)  # in frames
    bpm = 60 * fps / period

    # 3) best phase for the beat grid
    smooth = np.convolve(flux, np.ones(3) / 3, mode="same")
    best_phase, best_score = 0.0, -1.0
    for phase in np.arange(0, period, 0.5):
        idx = np.round(np.arange(phase, n, period)).astype(int)
        idx = idx[idx < n]
        score = smooth[idx].sum()
        if score > best_score:
            best_phase, best_score = phase, score
    beat_times = np.arange(best_phase, n, period) / fps
    beat_times = beat_times + (WINDOW / 2) / sample_rate  # center of the frame
    return float(bpm), beat_times


# ---------------------------------------------------------------------------
# Pitch / speed shifting (pure numpy)
# ---------------------------------------------------------------------------

def resample(samples, factor):
    """
    Play `samples` back `factor` times as fast (linear interpolation).
      factor < 1  -> lower pitch AND slower (like a slowing tape)
      factor > 1  -> higher pitch AND faster
    samples: int16 array, shape (n,) or (n, channels). Returns int16 array.
    """
    samples = np.asarray(samples)
    n = len(samples)
    if n < 2 or factor == 1.0:
        return np.ascontiguousarray(samples)
    out_len = int((n - 1) / factor) + 1
    pos = np.arange(out_len, dtype=np.float64) * factor
    i0 = pos.astype(np.int64)
    i1 = np.minimum(i0 + 1, n - 1)
    frac = (pos - i0).astype(np.float32)
    if samples.ndim == 2:
        frac = frac[:, None]
    a = samples[i0].astype(np.float32)
    b = samples[i1].astype(np.float32)
    out = a + (b - a) * frac
    return np.ascontiguousarray(np.rint(out).clip(-32768, 32767).astype(np.int16))


# ---------------------------------------------------------------------------
# MusicReader
# ---------------------------------------------------------------------------

class MusicReader:
    # If beats feel slightly early/late against what you hear, nudge this
    # (in seconds). Positive = beats happen later.
    LATENCY = 0.0

    # Pitch limits in semitones (12 = one octave) -> speed 0.5x to 2x
    MIN_SEMITONES = -12
    MAX_SEMITONES = 12

    def __init__(self, path=None, loop=True):
        self.path = None
        self.loop = loop                 # restart the song when it ends
        self.length = 0.0                # seconds of the ORIGINAL song
        self.base_bpm = 0.0              # tempo at normal speed
        self.beat_times = np.array([])   # beat times on the ORIGINAL timeline

        # step sizes you can change any time (in code or from the terminal)
        self.pitch_step = 3.0            # semitones per lower_pitch()/raise_pitch()
        self.speed_step = 10.0           # percent per faster()/slower()

        self.semitones = 0.0             # 0 = normal, negative = lower
        self.started = False
        self.paused = False

        # beat tracking you can read any time (filled in by update())
        self.just_beat = False
        self.total_beats = 0
        self.beat_history = deque(maxlen=128)   # (total_beat_number, song_position)

        self._samples = None             # decoded song, int16
        self._freq = 44100
        self._channel = None
        self._rendered = None            # song rendered at the current pitch
        self._rendered_semitones = None
        self._full_sound = None          # pygame Sound of the rendered song
        self._pos = 0.0                  # song position (sec, NOT wrapped) at the anchor
        self._clock = None               # time.monotonic() at the anchor; None = not running
        self._dirty = False              # pitch changed while paused

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
        if path:
            self.load(path)

    # ---- loading ----------------------------------------------------------
    def load(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Music file not found: {path}")
        self.stop()
        self.path = path

        sound = pygame.mixer.Sound(path)
        self.length = sound.get_length()
        self._freq = pygame.mixer.get_init()[0]
        self._samples = pygame.sndarray.array(sound)
        del sound
        self.base_bpm, self.beat_times = detect_beats(self._samples, self._freq)
        self._rendered = self._full_sound = self._rendered_semitones = None

    @property
    def title(self):
        return os.path.splitext(os.path.basename(self.path))[0] if self.path else "No music"

    # ---- pitch and speed --------------------------------------------------
    @property
    def pitch(self):
        """Multiplier for pitch AND speed. 1.0 = normal, 0.5 = octave down, half speed."""
        return 2.0 ** (self.semitones / 12.0)

    speed = pitch  # same thing: in this version they always move together

    @property
    def bpm(self):
        """Tempo you actually hear right now."""
        return self.base_bpm * self.pitch

    @property
    def play_length(self):
        """How long one pass of the song lasts at the current pitch."""
        return self.length / self.pitch

    def set_semitones(self, semitones):
        """Set pitch in semitones: 0 normal, -3 lower, +3 higher. Works while playing."""
        semitones = max(self.MIN_SEMITONES, min(self.MAX_SEMITONES, float(semitones)))
        if semitones == self.semitones:
            return self.semitones
        here = self._unwrapped()            # read position at the OLD pitch first
        was_running = self.started and not self.paused
        self.semitones = semitones
        if self.started:
            self._stop_channel()
            if was_running:
                self._start_sound(here)     # carry on from the same spot
            else:
                self._pos, self._clock = here, None
                self._dirty = True          # rebuild when the user unpauses
        return self.semitones

    def lower_pitch(self, semitones=None):
        """Lower pitch (and slow down). Default amount is self.pitch_step."""
        return self.set_semitones(self.semitones - (self.pitch_step if semitones is None else semitones))

    def raise_pitch(self, semitones=None):
        return self.set_semitones(self.semitones + (self.pitch_step if semitones is None else semitones))

    def reset_pitch(self):
        return self.set_semitones(0.0)

    def set_speed(self, multiplier):
        """Jump straight to a multiplier: 1.0 normal, 1.25 faster, 0.8 slower."""
        return self.set_semitones(12.0 * np.log2(max(0.01, float(multiplier))))

    def faster(self, percent=None):
        """Speed up (and raise pitch). Default amount is self.speed_step percent."""
        pct = self.speed_step if percent is None else percent
        return self.set_speed(self.pitch * (1 + pct / 100.0))

    def slower(self, percent=None):
        pct = self.speed_step if percent is None else percent
        return self.set_speed(self.pitch / (1 + pct / 100.0))

    # ---- playback ---------------------------------------------------------
    def _stop_channel(self):
        if self._channel is not None:
            self._channel.stop()
            self._channel = None

    def _render(self):
        """Render the whole song at the current pitch (cached until pitch changes)."""
        if self._rendered is None or self._rendered_semitones != self.semitones:
            self._rendered = resample(self._samples, self.pitch)
            self._rendered_semitones = self.semitones
            self._full_sound = pygame.sndarray.make_sound(self._rendered)
        return self._rendered

    def _start_sound(self, song_sec):
        """Start playing from song_sec (seconds, may be past the end if looping)."""
        rendered = self._render()
        wrapped = song_sec % self.length if self.loop and self.length > 0 else song_sec
        idx = int(wrapped / self.pitch * self._freq)
        idx = max(0, min(idx, len(rendered) - 2))
        if idx == 0:
            sound = self._full_sound
        else:
            sound = pygame.sndarray.make_sound(np.ascontiguousarray(rendered[idx:]))
        self._channel = sound.play()
        if self.loop and self._channel is not None:
            self._channel.queue(self._full_sound)   # next pass starts with no gap
        self._pos = song_sec
        self._clock = time.monotonic()
        self._dirty = False

    def _keep_looping(self):
        """Queue the next pass once the previous queued one has started."""
        if (
            self.loop
            and self.started
            and not self.paused
            and self._channel is not None
            and self._channel.get_queue() is None
        ):
            self._channel.queue(self._full_sound)

    def play(self):
        """Start from the beginning."""
        if self._samples is None:
            return
        self._stop_channel()
        self.total_beats = 0
        self.just_beat = False
        self.beat_history.clear()
        self.started, self.paused = True, False
        self._start_sound(0.0)

    def pause(self):
        if self.started and not self.paused:
            self._pos = self._unwrapped()
            self._clock = None
            if self._channel is not None:
                self._channel.pause()
            self.paused = True

    def unpause(self):
        if not self.started:
            self.play()
        elif self.paused:
            if self._dirty or self._channel is None:
                self.paused = False
                self._start_sound(self._pos)
            else:
                self._channel.unpause()
                self._clock = time.monotonic()
                self.paused = False

    def toggle(self):
        """Hook this to the pause/play button."""
        if self.is_playing:
            self.pause()
        else:
            self.unpause()

    def stop(self):
        self._stop_channel()
        self.started, self.paused = False, False
        self._pos, self._clock = 0.0, None
        self._dirty = False
        self.just_beat = False

    @property
    def is_playing(self):
        return (
            self.started
            and not self.paused
            and self._channel is not None
            and self._channel.get_busy()
        )

    @property
    def finished(self):
        """Only ever True when loop is off and the song ended."""
        return (
            not self.loop
            and self.started
            and not self.paused
            and (self._channel is None or not self._channel.get_busy())
        )

    def _unwrapped(self):
        """Song seconds since the start, counting every loop (original-song time)."""
        if not self.started:
            return 0.0
        if self._clock is None:
            return self._pos
        t = self._pos + (time.monotonic() - self._clock) * self.pitch
        return t if self.loop else min(t, self.length)

    def position(self):
        """Seconds into the current pass of the original song."""
        self._keep_looping()
        t = self._unwrapped()
        return t % self.length if self.loop and self.length > 0 else t

    @property
    def loops_played(self):
        """How many times the song has fully played and restarted."""
        if not (self.loop and self.length > 0):
            return 0
        return int(self._unwrapped() // self.length)

    # ---- beats ------------------------------------------------------------
    def beat_number(self):
        """Beats so far in the current pass of the song (0 before the first beat)."""
        t = self.position() - self.LATENCY * self.pitch
        return int(np.searchsorted(self.beat_times, t, side="right"))

    @property
    def beat_in_loop(self):
        return self.beat_number()

    def update(self):
        """
        Call ONCE per frame in your game loop. Keeps the music looping and
        updates just_beat / total_beats / beat_history. Prints nothing.
        """
        self.just_beat = False
        if not self.is_playing or len(self.beat_times) == 0:
            return
        absolute = self.loops_played * len(self.beat_times) + self.beat_number()
        if absolute > self.total_beats:
            self.total_beats = absolute
            self.just_beat = True
            self.beat_history.append((absolute, self.position()))

    def beat_phase(self):
        """
        0.0 right as a beat hits, rising to 1.0 just before the next one.
        For animation: bob = 1 - beat_phase(), or sin(phase * pi).
        """
        if self.base_bpm <= 0 or len(self.beat_times) == 0:
            return 0.0
        period = 60.0 / self.base_bpm
        t = self.position() - self.LATENCY * self.pitch
        return ((t - self.beat_times[0]) % period) / period

    def beat_period(self):
        """Real seconds between beats at the current pitch."""
        return 60.0 / self.bpm if self.bpm > 0 else 0.0

    def time_since_beat(self):
        """Real seconds since the last beat."""
        return self.beat_phase() * self.beat_period()

    def time_to_next_beat(self):
        """Real seconds until the next beat."""
        return (1.0 - self.beat_phase()) * self.beat_period()

    def beat_frame(self, num_frames, beats_per_frame=1, mode="loop"):
        """
        Which animation frame to show. It changes exactly when a beat hits.
          num_frames       how many frames you have (len(fish_frames))
          beats_per_frame  1 = new frame every beat, 2 = every other beat...
          mode             "loop"     0,1,2,0,1,2...
                           "pingpong" 0,1,2,1,0,1,2...
        Uses total_beats, so it keeps going smoothly across song loops.
        Call update() each frame first.
        """
        if num_frames <= 1:
            return 0
        step = self.total_beats // max(1, int(beats_per_frame))
        if mode == "pingpong":
            cycle = 2 * (num_frames - 1)
            k = step % cycle
            return k if k < num_frames else cycle - k
        return step % num_frames

    # ---- info / debugging -------------------------------------------------
    @staticmethod
    def format_time(seconds):
        s = int(seconds)
        return f"{s // 60}:{s % 60:02d}"

    def info(self):
        return {
            "title": self.title,
            "length": f"{self.format_time(self.length)} ({self.length:.1f}s)",
            "bpm_normal": round(self.base_bpm, 1),
            "beats_in_song": len(self.beat_times),
            "loop": self.loop,
        }

    def status(self):
        """One-line summary of the current state (for debugging)."""
        state = "paused" if self.paused else ("playing" if self.is_playing else "stopped")
        return (
            f"{state} | pitch {self.semitones:+.1f} st (x{self.pitch:.2f}) | "
            f"{self.bpm:.1f} BPM | pos {self.format_time(self.position())}/"
            f"{self.format_time(self.length)} | loop {self.loops_played} | "
            f"total beats {self.total_beats} | steps: pitch {self.pitch_step:g} st, speed {self.speed_step:g}%"
        )

    def debug_info(self):
        """Audio details - paste this to whoever is helping if pitch isn't working."""
        init = pygame.mixer.get_init()
        return {
            "mixer (freq, format, channels)": init,
            "pygame": pygame.version.ver,
            "samples dtype/shape": (str(self._samples.dtype), self._samples.shape) if self._samples is not None else None,
            "rendered shape": self._rendered.shape if self._rendered is not None else None,
            "rendered at semitones": self._rendered_semitones,
            "channel": self._channel,
            "channel busy": self._channel.get_busy() if self._channel is not None else None,
        }


# ---------------------------------------------------------------------------
# Run this file directly to test a song without the game
# ---------------------------------------------------------------------------

HELP = """
Commands (type, then Enter). Nothing prints on its own.
  d / u          lower / raise pitch by the pitch step (default 3 semitones)
  step <n>       set the pitch step, e.g.  step 5
  semi <n>       jump to n semitones, e.g.  semi -6   (0 = normal)
  faster / slower   change speed by the speed step (default 10 %)
  sstep <n>      set the speed step in percent, e.g.  sstep 25
  speed <x>      jump to a speed multiplier, e.g.  speed 1.25
  r              reset pitch and speed to normal
  p              pause / play         loop    turn looping on / off
  b              print every beat (on/off) - for checking beat timing
  s              show status          i       audio debug info
  h              this help            q       quit
"""


def _terminal_commands(q):
    """Reads typed commands in the background so the music keeps running."""
    while True:
        try:
            q.put(input().strip().lower())
        except EOFError:
            return


def _run_command(reader, cmd, state):
    """Returns False to quit."""
    parts = cmd.split()
    if not parts:
        return True
    word, arg = parts[0], parts[1] if len(parts) > 1 else None
    try:
        if word in ("q", "quit"):
            return False
        elif word in ("h", "help", "?"):
            print(HELP)
            return True
        elif word in ("d", "down"):
            reader.lower_pitch()
        elif word in ("u", "up"):
            reader.raise_pitch()
        elif word == "step" and arg:
            reader.pitch_step = abs(float(arg))
        elif word in ("semi", "pitch") and arg:
            reader.set_semitones(float(arg))
        elif word == "faster":
            reader.faster()
        elif word == "slower":
            reader.slower()
        elif word == "sstep" and arg:
            reader.speed_step = abs(float(arg))
        elif word == "speed" and arg:
            reader.set_speed(float(arg))
        elif word in ("r", "reset"):
            reader.reset_pitch()
        elif word in ("p", "pause"):
            reader.toggle()
        elif word == "loop":
            reader.loop = not reader.loop
        elif word == "b":
            state["show_beats"] = not state["show_beats"]
            print(f"  beat printing {'ON' if state['show_beats'] else 'OFF'}")
            return True
        elif word in ("i", "info"):
            for k, v in reader.debug_info().items():
                print(f"  {k}: {v}")
            return True
        elif word in ("s", "status"):
            pass
        elif len(parts) == 1:
            reader.set_speed(float(word))   # a bare number = speed multiplier
        else:
            print("  ?? type h for the command list")
            return True
    except ValueError:
        print("  ?? that needs a number, type h for the command list")
        return True
    print("  " + reader.status())
    return True


if __name__ == "__main__":
    import queue
    import sys
    import threading

    if len(sys.argv) < 2:
        print("Usage: python3 music_reader.py path/to/song.mp3 [num_frames]")
        sys.exit(1)

    num_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    pygame.init()
    reader = MusicReader(sys.argv[1])
    for key, value in reader.info().items():
        print(f"{key}: {value}")
    print(HELP)

    commands = queue.Queue()
    threading.Thread(target=_terminal_commands, args=(commands,), daemon=True).start()

    reader.unpause()
    print("  " + reader.status())
    state = {"show_beats": False}
    clock = pygame.time.Clock()
    running = True
    try:
        while running:
            clock.tick(120)
            pygame.event.pump()
            reader.update()                 # <- this is what your game loop does

            while not commands.empty():
                if not _run_command(reader, commands.get(), state):
                    running = False

            if state["show_beats"] and reader.just_beat:
                print(
                    f"  beat {reader.total_beats:4d} (loop {reader.loops_played}) "
                    f"-> frame {reader.beat_frame(num_frames)}"
                )
    except KeyboardInterrupt:
        pass
    reader.stop()
    pygame.quit()
