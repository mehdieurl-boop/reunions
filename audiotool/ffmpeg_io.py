"""Entrées / sorties audio via ffmpeg (décodage en flux, encodage des exports)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

_FFMPEG: str | None = None
_FFPROBE: str | None = None


class FFmpegMissing(RuntimeError):
    pass


def _find(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    try:  # solution de repli : binaire fourni par le paquet pip imageio-ffmpeg
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if name == "ffmpeg":
            return exe
        cand = Path(exe).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
        return str(cand) if cand.exists() else None
    except Exception:
        return None


def ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _find("ffmpeg")
    if not _FFMPEG:
        raise FFmpegMissing(
            "ffmpeg est introuvable. Installez-le (macOS : brew install ffmpeg — "
            "Windows : winget install Gyan.FFmpeg) ou lancez : pip install imageio-ffmpeg"
        )
    return _FFMPEG


def ffprobe() -> str | None:
    global _FFPROBE
    if _FFPROBE is None:
        _FFPROBE = _find("ffprobe")
    return _FFPROBE


def probe(path: str) -> dict:
    """Durée, canaux, fréquence d'échantillonnage du fichier source."""
    pp = ffprobe()
    if pp:
        out = subprocess.run(
            [pp, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=channels,sample_rate:format=duration", "-of", "json", path],
            capture_output=True, text=True,
        )
        try:
            d = json.loads(out.stdout)
            st = (d.get("streams") or [{}])[0]
            return {
                "channels": int(st.get("channels", 1)),
                "sample_rate": int(st.get("sample_rate", 48000)),
                "duration": float(d.get("format", {}).get("duration", 0.0)),
            }
        except Exception:
            pass
    # repli : ffmpeg -i lit les métadonnées sur stderr
    out = subprocess.run([ffmpeg(), "-i", path], capture_output=True, text=True).stderr
    dur = 0.0
    if "Duration:" in out:
        h, m, s = out.split("Duration:")[1].split(",")[0].strip().split(":")
        dur = int(h) * 3600 + int(m) * 60 + float(s)
    return {"channels": 2 if "stereo" in out else 1, "sample_rate": 48000, "duration": dur}


def decode_stream(path: str, sr: int, channels: int, start: float | None = None,
                  duration: float | None = None):
    """Générateur de blocs float32 (n, channels) décodés par ffmpeg."""
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-map", "a:0", "-f", "f32le", "-acodec", "pcm_f32le",
            "-ac", str(channels), "-ar", str(sr), "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            bufsize=10 ** 7)
    frame = 4 * channels
    block = frame * sr          # ~1 s
    try:
        rest = b""
        while True:
            data = proc.stdout.read(block)
            if not data:
                break
            data = rest + data
            usable = len(data) - len(data) % frame
            rest = data[usable:]
            arr = np.frombuffer(data[:usable], dtype="<f4")
            yield arr.reshape(-1, channels).astype(np.float32, copy=True)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait()


class RawWriter:
    """Écrit un WAV float32 temporaire à partir de blocs numpy."""

    def __init__(self, out_path: str, sr: int, channels: int):
        cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
               "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
               "-c:a", "pcm_f32le", out_path]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=10 ** 7)

    def write(self, chunk: np.ndarray):
        self.proc.stdin.write(np.ascontiguousarray(chunk, dtype="<f4").tobytes())

    def close(self):
        try:
            self.proc.stdin.close()
        finally:
            self.proc.wait()


def encode(src_wav: str, out_path: str, gain_db: float, *, mono: bool = False,
           sr: int | None = None, codec: str = "auto", bitrate: str = "192k",
           ceiling_db: float = -1.0, trim_silence: bool = False,
           segment_minutes: int = 0) -> list[str]:
    """Gain final + limiteur + conversion de format. Renvoie les fichiers écrits."""
    af = [f"volume={gain_db:.2f}dB"]
    if trim_silence:
        af.append("silenceremove=stop_periods=-1:stop_duration=1.2:"
                  "stop_threshold=-45dB:stop_silence=0.4")
    limit = 10 ** (ceiling_db / 20)
    af.append(f"alimiter=limit={limit:.4f}:attack=5:release=60:level=disabled")

    ext = Path(out_path).suffix.lower()
    if codec == "auto":
        codec = {".mp3": "libmp3lame", ".m4a": "aac", ".flac": "flac",
                 ".wav": "pcm_s16le"}.get(ext, "pcm_s16le")
    if codec in ("libmp3lame", "aac"):
        # un codec avec perte restitue des crêtes plus hautes que le PCM encodé
        # (jusqu'à ~2,5 dB sur du matériel dense) : on garde la marge en amont
        af[-1] = af[-1].replace(f"limit={limit:.4f}",
                                f"limit={10 ** ((ceiling_db - 2.5) / 20):.4f}")

    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin",
           "-i", src_wav, "-af", ",".join(af)]
    if mono:
        cmd += ["-ac", "1"]
    if sr:
        cmd += ["-ar", str(sr)]
    cmd += ["-c:a", codec]
    if codec in ("libmp3lame", "aac"):
        cmd += ["-b:a", bitrate]

    if segment_minutes and segment_minutes > 0:
        stem, suffix = Path(out_path).stem, Path(out_path).suffix
        pattern = str(Path(out_path).with_name(f"{stem}_partie%02d{suffix}"))
        cmd += ["-f", "segment", "-segment_time", str(segment_minutes * 60),
                "-reset_timestamps", "1", pattern]
        subprocess.run(cmd, check=True, capture_output=True)
        d = Path(out_path).parent
        return sorted(str(p) for p in d.glob(f"{stem}_partie*{suffix}"))

    cmd += [out_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg: {res.stderr[-500:]}")
    return [out_path]


def check_environment() -> str:
    try:
        exe = ffmpeg()
    except FFmpegMissing as e:
        return str(e)
    v = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout
    return "ok " + v.splitlines()[0] if v else "ok"


if __name__ == "__main__":
    print(check_environment(), file=sys.stderr)
