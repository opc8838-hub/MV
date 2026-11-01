"""Shared streaming RGB video I/O, fixed framing, typography and review sheets.

Inputs are local paths supplied by the caller; generated artifacts go to explicit
output paths. Requires an ffmpeg build with libx264, located through FFMPEG or PATH.
"""
import argparse
import json
import math
from os import environ
from pathlib import Path
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PAPER = (238, 235, 228)
RED = (255, 59, 31)
INK = (17, 17, 17)


def ffmpeg():
    value = environ.get('FFMPEG') or shutil.which('ffmpeg')
    if not value:
        raise RuntimeError('Install ffmpeg with libx264; set FFMPEG to its executable or add it to PATH.')
    return str(value)


def run(args):
    return subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], check=True)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def resolve(base, path):
    return (Path(base) / path).resolve()


def protect_inputs(output, inputs):
    if Path(output).resolve() in {Path(p).resolve() for p in inputs}:
        raise ValueError('Output must be different from every input file')


def font(size, weight=800, path=None):
    f = ImageFont.truetype(str(path or ROOT / 'fonts' / 'Outfit-VF.ttf'), max(1, int(size)))
    if not path:
        f.set_variation_by_axes([weight])
    return f


def text(img, value, xy=None, size=None, fill=INK, anchor='mm', font_path=None):
    im = Image.fromarray(np.uint8(np.clip(img, 0, 255)))
    w, h = im.size
    xy = xy or (w / 2, h / 2)
    size = size or int(w * .18)
    f = font(size, path=font_path)
    while f.getlength(value) > w * .9 and size > 5:
        size -= 1
        f = font(size, path=font_path)
    ImageDraw.Draw(im).text(xy, value, font=f, fill=fill, anchor=anchor)
    return np.asarray(im).copy()


def paper(w, h, seed=0):
    y, x = np.mgrid[-1:1:complex(h), -1:1:complex(w)]
    light = 1 - .075 * (x*x + y*y)
    noise = np.random.default_rng(seed).normal(0, 1.2, (h, w, 1))
    return np.uint8(np.clip(np.array(PAPER) * light[..., None] + noise, 0, 255))


def grain(img, seed=0, amount=2):
    n = np.random.default_rng(seed).normal(0, amount, (*img.shape[:2], 1))
    return np.uint8(np.clip(img.astype(np.float32) + n, 0, 255))


def crop916(img, w, h, x_offset=0):
    """One fixed crop: x_offset is a fraction of source width; no tracking/zoom."""
    ih, iw = img.shape[:2]
    ratio = w / h
    cw, ch = min(iw, int(ih * ratio)), min(ih, int(iw / ratio))
    x = int(np.clip((iw - cw) / 2 + x_offset * iw, 0, iw - cw))
    y = (ih - ch) // 2
    return cv2.resize(img[y:y+ch, x:x+cw], (w, h), interpolation=cv2.INTER_LANCZOS4)


def read_exact(pipe, n):
    chunks = bytearray()
    while len(chunks) < n:
        chunk = pipe.read(n - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


class Reader:
    """Decode only a requested interval; ffmpeg performs one fixed 9:16 crop."""
    def __init__(self, path, start=0, count=1, w=360, h=640, fps=25, x_offset=0):
        if start < 0 or count < 1 or abs(x_offset) > 1:
            raise ValueError('start >= 0, count >= 1 and x_offset within [-1, 1] required')
        self.w, self.h, self.count, self.index = w, h, count, 0
        ratio = w / h
        vf = (f'fps={fps},crop=w=trunc(min(iw\\,ih*{ratio})/2)*2:'
              f'h=trunc(min(ih\\,iw/{ratio})/2)*2:'
              f'x=max(0\\,min(iw-ow\\,(iw-ow)/2+iw*{x_offset})):y=(ih-oh)/2,'
              f'scale={w}:{h}:flags=lanczos')
        self.log = tempfile.TemporaryFile()
        self.p = subprocess.Popen([ffmpeg(), '-v', 'error', '-ss', str(start), '-threads', '1', '-i', str(path),
                                   '-an', '-vf', vf, '-frames:v', str(count), '-f', 'rawvideo',
                                   '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE, stderr=self.log)

    def read(self):
        raw = read_exact(self.p.stdout, self.w * self.h * 3)
        if len(raw) != self.w * self.h * 3:
            self.log.seek(0)
            detail = self.log.read().decode(errors='replace')
            raise RuntimeError(f'Source ended before requested frame {self.index}/{self.count}. {detail}')
        self.index += 1
        return np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3).copy()

    def close(self):
        self.p.stdout.close()
        if self.p.poll() is None:
            self.p.terminate()
        self.p.wait()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Writer:
    """Bounded-memory H.264 encoder, explicit BT.709 matrix and limited-range tags."""
    def __init__(self, path, w, h, fps=25):
        if min(w, h, fps) <= 0 or w % 2 or h % 2:
            raise ValueError('Even positive width/height and positive fps required')
        self.w, self.h = w, h
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.log = tempfile.TemporaryFile()
        self.p = subprocess.Popen([ffmpeg(), '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{w}x{h}', '-r', str(fps), '-i', '-', '-an', '-vf',
            'scale=in_range=pc:out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int',
            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
            '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-threads', '2', '-crf', '17', '-preset', 'medium',
            '-movflags', '+faststart', str(path)], stdin=subprocess.PIPE, stderr=self.log)

    def write(self, frame):
        if frame.shape != (self.h, self.w, 3):
            raise ValueError(f'Frame shape {frame.shape} does not match encoder')
        try:
            self.p.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
        except BrokenPipeError:
            self.log.seek(0)
            raise RuntimeError(self.log.read().decode(errors='replace')) from None

    def __enter__(self):
        return self

    def __exit__(self, exc, *_):
        try:
            self.p.stdin.close()
        except BrokenPipeError:
            pass
        rc = self.p.wait()
        self.log.seek(0)
        detail = self.log.read().decode(errors='replace')
        self.log.close()
        if rc and not exc:
            raise RuntimeError(detail)


def duration(path):
    """Probe without requiring a separately installed ffprobe executable."""
    import re
    p = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True)
    m = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', p.stderr.decode(errors='replace'))
    if not m:
        raise ValueError('Cannot read media duration')
    a, b, c = map(float, m.groups())
    return 3600*a + 60*b + c


class Beats:
    def __init__(self, data=None, bpm=120):
        data = data or {}
        self.bpm = float(data.get('bpm', bpm))
        if self.bpm <= 0:
            raise ValueError('bpm must be positive')
        self.points = data.get('beats', [])
        if any(b <= a for a, b in zip(self.points, self.points[1:])):
            raise ValueError('beats must be strictly increasing')

    def sec(self, beat):
        if beat < 0:
            raise ValueError('Beat indices start at zero')
        if not self.points:
            return beat * 60 / self.bpm
        i = math.floor(beat)
        if i + 1 < len(self.points):
            return self.points[i] + (beat-i) * (self.points[i+1]-self.points[i])
        return self.points[-1] + (beat-len(self.points)+1)*60/self.bpm


def contact_sheet(video, out, fps=25, step=.25, w=90, h=160, every_frame=False):
    """Paged review images, capped at 100 thumbs per PNG."""
    count = round(duration(video) * fps)
    stride = 1 if every_frame else max(1, round(step*fps))
    canvas, page, slot = None, 0, 0
    out = Path(out)
    with Reader(video, count=count, w=w, h=h, fps=fps) as reader:
        for i in range(count):
            frame = reader.read()
            if i % stride:
                continue
            if slot == 0:
                canvas = Image.new('RGB', (w*10, (h+20)*10), PAPER)
            tile = Image.fromarray(frame)
            x, y = slot % 10 * w, slot // 10 * (h+20)
            canvas.paste(tile, (x, y))
            ImageDraw.Draw(canvas).text((x+2, y+h), f'{i/fps:.2f}s #{i}', fill=INK, font=font(10, 500))
            slot += 1
            if slot == 100:
                canvas.save(out.with_name(f'{out.stem}-{page:02d}.png'))
                page += 1
                slot = 0
    if slot:
        canvas.crop((0, 0, w*10, math.ceil(slot/10)*(h+20))).save(out.with_name(f'{out.stem}-{page:02d}.png'))


def video_args(parser):
    parser.add_argument('--width', type=int, default=360, help='Even preview width; use 1080 for final')
    parser.add_argument('--height', type=int, default=640, help='Even preview height; use 1920 for final')
    parser.add_argument('--fps', type=int, default=25)


def video_options(cfg, args):
    """Config dimensions default; explicit CLI options override them."""
    import sys
    return tuple(getattr(args,key) if any(v==f'--{key}' or v.startswith(f'--{key}=') for v in sys.argv)
                 else cfg.get(key,getattr(args,key)) for key in ('width','height','fps'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Generate timestamped review contact sheets from a local video.')
    p.add_argument('video', type=Path)
    p.add_argument('--out', type=Path, required=True, help='PNG prefix; pages are numbered automatically')
    p.add_argument('--every-frame', action='store_true', help='Show every encoded frame')
    p.add_argument('--fps', type=int, default=25)
    a = p.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet(a.video, a.out, fps=a.fps, every_frame=a.every_frame)
