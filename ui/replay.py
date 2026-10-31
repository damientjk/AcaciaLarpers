"""Build the pixel-art replay page for one audit log.

    from ui.replay import replay_html
    import streamlit.components.v1 as components
    components.html(replay_html(log), height=1250, scrolling=True)
"""
import base64
import functools
import io
import json
from pathlib import Path

HERE = Path(__file__).parent


CHARACTERS = {"atc": "ava.png", "pilot": "pip.png", "ground": "gus.png"}


@functools.lru_cache(maxsize=1)
def character_pngs() -> dict:
    """Yizhuo's 1080 x 1457 masters, shrunk once to 160 x 216 (4x the 40 x 54 seat) so each replay embeds a
    few KB instead of ~2 MB. Missing files or Pillow fall back to the procedural sprites."""
    try:
        from PIL import Image
    except ImportError:
        return {}
    out = {}
    for agent, name in CHARACTERS.items():
        p = HERE / "assets" / "characters" / name
        if p.exists():
            buf = io.BytesIO()
            Image.open(p).convert("RGBA").resize((160, 216), Image.LANCZOS).save(buf, "PNG", optimize=True)
            out[agent] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return out


def replay_html(log: dict, autoplay: bool = False) -> str:
    template = (HERE / "replay_template.html").read_text()
    sprites = ("const SKY_CHARACTER_PNGS = " + json.dumps(character_pngs()) + ";\n"
               + (HERE / "_sprites.js").read_text() + "\n" + (HERE / "_brain.js").read_text())
    data = json.dumps(log).replace("</", "<\\/")  # keep the JSON from closing the script tag
    bd = HERE / "backdrop.png"
    backdrop = "data:image/png;base64," + base64.b64encode(bd.read_bytes()).decode() if bd.exists() else ""
    html = (template.replace("%%SPRITES%%", sprites).replace("%%BACKDROP%%", backdrop)
            .replace("__SKY_LOG__", data))
    if autoplay:  # press Play once the page's own script has wired the buttons
        html = html.replace("</body>", "<script>document.getElementById('play').click();</script></body>", 1)
    return html


if __name__ == "__main__":
    # python ui/replay.py fixtures/sample_logs/demo_consensus.json  -> writes ui/replay_demo.html
    import sys
    src = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "fixtures/sample_logs/demo_consensus.json")
    out = HERE / "replay_demo.html"
    out.write_text(replay_html(json.loads(src.read_text())))
    print("wrote", out)
