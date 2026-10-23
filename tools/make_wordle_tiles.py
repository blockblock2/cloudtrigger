"""Make examples/wordle-tiles.gif: every Wordle tile as one frame of a GIF.

Upload the GIF to Scratch (Choose a Sprite -> Upload Sprite) and each frame
becomes a costume, numbered like this:

  costume 1        empty tile
  costumes 2-27    typed letter A-Z (white tile)
  costumes 28-53   gray   A-Z  (not in the word)
  costumes 54-79   yellow A-Z  (in the word, wrong place)
  costumes 80-105  green  A-Z  (right place)

  costume number = (colour * 26) + letter + 1
      colour: typed 0, gray 1, yellow 2, green 3      letter: a=1 ... z=26

    python tools/make_wordle_tiles.py
"""
import os
import string

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.join(os.path.dirname(__file__), "..", "examples")
SIZE = 80            # Scratch shows bitmaps at half size: 40 x 40 on the stage
RADIUS = 8
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

STYLES = [  # (name, fill, border, letter colour)
    ("typed", "#ffffff", "#878a8c", "#1a1a1b"),
    ("gray", "#787c7e", "#787c7e", "#ffffff"),
    ("yellow", "#c9b458", "#c9b458", "#ffffff"),
    ("green", "#6aaa64", "#6aaa64", "#ffffff"),
]


def tile(fill, border, letter="", ink="#ffffff"):
    # Solid page colour behind the rounded corners: GIF frames with transparency can
    # leave bits of earlier frames behind when Scratch splits them.
    img = Image.new("RGB", (SIZE, SIZE), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, SIZE - 3, SIZE - 3], RADIUS, fill=fill, outline=border, width=4)
    if letter:
        font = ImageFont.truetype(FONT, 46)
        d.text((SIZE / 2, SIZE / 2 + 1), letter.upper(), font=font, fill=ink, anchor="mm")
    return img


def frames():
    out = [tile("#ffffff", "#d3d6da")]
    for _, fill, border, ink in STYLES:
        for letter in string.ascii_lowercase:
            out.append(tile(fill, border, letter, ink))
    return out


def build():
    imgs = frames()
    assert len(imgs) == 105
    # One shared palette so every frame keeps exactly the same colours.
    sheet = Image.new("RGB", (SIZE * 15, SIZE * 7), "#ffffff")
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % 15) * SIZE, (i // 15) * SIZE))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in imgs]
    gif = os.path.join(HERE, "wordle-tiles.gif")
    pal[0].save(gif, save_all=True, append_images=pal[1:], duration=400, loop=0,
                optimize=False, disposal=1)
    sheet.save(os.path.join(HERE, "wordle-tiles-preview.png"))
    print("wrote", os.path.normpath(gif), "with", len(imgs), "frames")


if __name__ == "__main__":
    build()
