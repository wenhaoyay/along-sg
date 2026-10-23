"""Stitch the frames capture-readme.mjs took into the README's demo GIF.

    python scripts/frames-to-gif.py ../docs/images/.frames ../docs/images/demo.gif

Needs Pillow. The last frame is held so the result can be read before the
loop starts again; the frames folder is removed afterwards.
"""

import shutil
import sys
from pathlib import Path

from PIL import Image

source, target = Path(sys.argv[1]), Path(sys.argv[2])
paths = sorted(source.glob("*.png"))
if not paths:
    sys.exit(f"No frames in {source}")
frames = [
    Image.open(path).convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
    for path in paths
]
durations = [110] * len(frames)
durations[-1] = 2600
frames[0].save(
    target,
    save_all=True,
    append_images=frames[1:],
    duration=durations,
    loop=0,
    optimize=True,
    disposal=2,
)
shutil.rmtree(source)
print(f"{target}: {len(frames)} frames, {target.stat().st_size // 1024} KB")
