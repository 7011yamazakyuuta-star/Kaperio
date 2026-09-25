"""Package the approved, unchanged raster artwork into desktop icon formats."""
from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / 'static'


def build():
    with Image.open(STATIC / 'brand-source.png') as source:
        source = source.convert('RGBA')
        # Normalize transparent margins without recoloring or redrawing the artwork.
        bounds = source.getchannel('A').point(lambda a: 255 if a >= 128 else 0).getbbox()
        if not bounds:
            raise ValueError('Brand artwork is empty')
        artwork = source.crop(bounds)
        side = max(artwork.size)
        canvas = Image.new('RGBA', (side, side))
        canvas.alpha_composite(artwork, ((side - artwork.width) // 2, (side - artwork.height) // 2))
        master = Image.new('RGBA', (1024, 1024))
        master.alpha_composite(canvas.resize((944, 944), Image.Resampling.LANCZOS), (40, 40))
        for size in (64, 192, 512):
            master.resize((size, size), Image.Resampling.LANCZOS).save(STATIC / f'icon-{size}.png')
        master.save(STATIC / 'favicon.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
        master.save(STATIC / 'icon.icns')


if __name__ == '__main__':
    build()
