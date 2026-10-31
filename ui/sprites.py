"""The procedural pixel characters from ui/_sprites.js, drawn in Python so Streamlit pages can show them
as images (brand mark, team cards, agent pages). Same 20 x 27 grid and colours as the replay."""
import functools
import io

OUT = "#1b1f3b"
PAL = {"atc": ("#e8b58a", "#2b4c8c", "#1f2a44", "#111827"), "pilot": ("#f6cfa8", "#f8fafc", "#1e3a8a", "#111827"),
       "ground": ("#c68a5c", "#4b5563", "#334155", "#7c4a1e"), "mod": ("#f2c9a6", "#efe6d2", "#1f2937", "#f8fafc")}


def grid(kind: str) -> list[list[str | None]]:
    W, H = 20, 27
    g = [[None] * W for _ in range(H)]

    def f(x, y, w, h, c):
        for j in range(y, y + h):
            for i in range(x, x + w):
                if 0 <= j < H and 0 <= i < W:
                    g[j][i] = c

    skin, shirt, pants, shoe = PAL[kind]
    f(4, 5, 12, 10, skin); f(5, 15, 10, 1, skin)
    f(8, 16, 4, 1, "#d9a27a")
    f(6, 17, 8, 1, shirt); f(7, 18, 6, 4, shirt); f(5, 18, 2, 4, shirt); f(13, 18, 2, 4, shirt)
    f(5, 22, 2, 1, skin); f(13, 22, 2, 1, skin)
    f(7, 22, 2, 3, pants); f(11, 22, 2, 3, pants); f(6, 25, 3, 1, shoe); f(11, 25, 3, 1, shoe)
    f(6, 9, 3, 3, "#fff"); f(11, 9, 3, 3, "#fff"); f(8, 10, 1, 2, OUT); f(13, 10, 1, 2, OUT)
    f(9, 13, 2, 1, "#8a3b2e"); f(5, 13, 1, 1, "#f29b9b"); f(14, 13, 1, 1, "#f29b9b")
    if kind == "atc":
        for a in [(4, 4, 12, 3, "#5a3a22"), (4, 7, 1, 5, "#5a3a22"), (15, 7, 1, 5, "#5a3a22"), (3, 7, 1, 8, "#5a3a22"),
                  (16, 7, 1, 8, "#5a3a22"), (5, 3, 10, 1, "#6b7280"), (4, 4, 1, 1, "#6b7280"), (15, 4, 1, 1, "#6b7280"),
                  (2, 9, 2, 4, "#374151"), (16, 9, 2, 4, "#374151"), (3, 13, 1, 2, "#374151"), (4, 14, 4, 1, "#374151"),
                  (8, 14, 1, 1, "#ef4444"), (8, 19, 2, 2, "#ffd447")]:
            f(*a)
    if kind == "pilot":
        for a in [(4, 1, 12, 4, "#1e3a8a"), (5, 0, 10, 1, "#1e3a8a"), (4, 5, 12, 1, "#f8fafc"), (3, 6, 14, 1, "#111827"),
                  (9, 2, 2, 2, "#ffd447"), (4, 7, 1, 3, "#3b2a1a"), (15, 7, 1, 3, "#3b2a1a"), (9, 17, 2, 5, "#1e3a8a"),
                  (6, 17, 2, 1, "#ffd447"), (12, 17, 2, 1, "#ffd447"), (5, 21, 2, 1, "#ffd447"), (13, 21, 2, 1, "#ffd447")]:
            f(*a)
    if kind == "ground":
        for a in [(5, 1, 10, 5, "#ffc83d"), (6, 0, 8, 1, "#ffc83d"), (9, 1, 2, 5, "#ffe083"), (3, 6, 14, 1, "#e0a800"),
                  (4, 7, 1, 2, "#7a4a24"), (15, 7, 1, 2, "#7a4a24"), (6, 17, 8, 1, "#ff7a1a"), (7, 18, 2, 4, "#ff7a1a"),
                  (11, 18, 2, 4, "#ff7a1a"), (7, 20, 6, 1, "#e5e7eb"), (5, 18, 2, 2, "#ff7a1a"), (13, 18, 2, 2, "#ff7a1a"),
                  (4, 15, 1, 7, "#ff4d1a"), (4, 14, 1, 1, "#ffe08a"), (15, 15, 1, 7, "#ff4d1a"), (15, 14, 1, 1, "#ffe08a")]:
            f(*a)
    if kind == "mod":
        hr = "#2a1c2e"
        for a in [(5, 2, 10, 1, hr), (4, 3, 12, 3, hr), (4, 6, 5, 2, hr), (11, 6, 5, 2, hr), (6, 8, 2, 1, hr),
                  (12, 8, 2, 1, hr), (3, 5, 1, 8, hr), (16, 5, 1, 8, hr), (4, 8, 1, 4, hr), (15, 8, 1, 4, hr),
                  (7, 3, 3, 1, "#4a3352"), (16, 13, 1, 1, "#e5e7eb"), (16, 14, 1, 1, "#cbd5e1"), (8, 17, 4, 1, "#111827"),
                  (9, 18, 2, 4, "#111827"), (8, 18, 1, 3, "#d6c9ad"), (11, 18, 1, 3, "#d6c9ad"), (15, 16, 2, 2, "#6b7280"),
                  (15, 16, 1, 1, "#e5e7eb"), (15, 18, 1, 4, "#374151")]:
            f(*a)
    o = [r[:] for r in g]  # auto outline, as in _sprites.js
    for y in range(H):
        for x in range(W):
            if not g[y][x] and any(0 <= y + dy < H and 0 <= x + dx < W and g[y + dy][x + dx] and g[y + dy][x + dx] != OUT
                                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                o[y][x] = OUT
    return o


@functools.lru_cache(maxsize=8)
def sprite_png(kind: str, scale: int = 8) -> bytes:
    from PIL import Image
    g = grid(kind)
    im = Image.new("RGBA", (20, 27), (0, 0, 0, 0))
    for y, row in enumerate(g):
        for x, c in enumerate(row):
            if c:
                im.putpixel((x, y), tuple(int(c[k:k + 2], 16) for k in (1, 3, 5)) + (255,) if len(c) == 7
                            else tuple(int(c[k] * 2, 16) for k in (1, 2, 3)) + (255,))
    buf = io.BytesIO()
    im.resize((20 * scale, 27 * scale), Image.NEAREST).save(buf, "PNG")
    return buf.getvalue()
