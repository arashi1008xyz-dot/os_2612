"""Pythonで描く小さなアイコン。HTML・CSS・JavaScriptは使用しない。"""
from functools import lru_cache
from io import BytesIO
import base64
from PIL import Image, ImageDraw

TEAL = "#258B8B"


@lru_cache(maxsize=16)
def icon(name):
    image = Image.new("RGBA", (128, 128), (255, 255, 255, 0))
    d = ImageDraw.Draw(image)
    def line(points, width=5):
        d.line(points, fill=TEAL, width=width, joint="curve")
    def rect(box):
        d.rounded_rectangle(box, radius=2, outline=TEAL, width=4)
    if name in ("book", "manga"):
        line([(12, 105), (12, 27), (30, 22), (49, 23), (64, 30), (79, 23), (99, 22), (116, 27), (116, 105), (97, 100), (79, 101), (64, 108), (48, 101), (30, 100), (12, 105)])
        line([(64, 30), (64, 108)], 4)
        if name == "book":
            for x in (25, 36, 47, 80, 91, 102):
                line([(x, 37), (x, 89)], 4)
        else:
            for box in ((22, 34, 53, 49), (22, 57, 37, 90), (43, 57, 54, 70), (43, 77, 54, 91),
                        (74, 34, 87, 48), (94, 34, 106, 48), (74, 56, 106, 70), (74, 77, 93, 91), (99, 77, 107, 91)):
                rect(box)
    elif name in ("anime", "drama"):
        rect((14, 31, 112, 92))
        if name == "anime":
            line([(43, 13), (62, 31), (82, 13)], 4)
        line([(64, 94), (64, 108)], 4)
        line([(43, 109), (85, 109)], 4)
    elif name == "movie":
        rect((18, 48, 111, 107))
        line([(18, 48), (12, 27), (106, 10), (111, 32), (18, 48)])
        for x in (30, 55, 80):
            line([(x, 24), (x + 12, 37)], 4)
    elif name == "other":
        d.ellipse((15, 17, 112, 111), outline=TEAL, width=5)
        for x in (40, 64, 88):
            d.ellipse((x - 4, 59, x + 4, 67), fill=TEAL)
    elif name == "record":
        line([(25, 112), (100, 16)], 5)
        line([(33, 93), (35, 66), (48, 40), (74, 21), (107, 12), (103, 43), (84, 68), (59, 83), (33, 93)])
        for x, y in ((48, 67), (61, 51), (76, 34)):
            line([(x, y), (x + 17, y - 2)], 4)
    elif name == "home":
        line([(12, 59), (64, 15), (116, 59)], 6)
        line([(28, 50), (28, 111), (51, 111), (51, 77), (77, 77), (77, 111), (100, 111), (100, 50)], 5)
    elif name == "stats":
        for box in ((20, 70, 36, 111), (56, 22, 72, 111), (92, 47, 108, 111)):
            rect(box)
    elif name == "search":
        d.ellipse((16, 13, 88, 85), outline=TEAL, width=6)
        line([(78, 76), (114, 112)], 7)
    return image


def button_label(name, label):
    buffer = BytesIO()
    icon(name).save(buffer, "PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"![{label}](data:image/png;base64,{encoded}) {label}"
