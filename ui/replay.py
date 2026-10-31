"""Build the pixel-art replay page for one audit log.

    from ui.replay import replay_html
    import streamlit.components.v1 as components
    components.html(replay_html(log), height=1250, scrolling=True)
"""
import base64
import json
from pathlib import Path

HERE = Path(__file__).parent


def replay_html(log: dict, autoplay: bool = False, live: dict | None = None, view: str = "huddle") -> str:
    """view: "airport" (scene only) or "huddle" (scene, log and candidates). live: {phase, lines, fake} while a
    run is in progress; the scene then shows who is thinking instead of a replay."""
    template = (HERE / "replay_template.html").read_text()
    sprites = (HERE / "_sprites.js").read_text()
    data = json.dumps(log).replace("</", "<\\/")  # keep the JSON from closing the script tag
    bd = HERE / "backdrop.png"
    backdrop = "data:image/png;base64," + base64.b64encode(bd.read_bytes()).decode() if bd.exists() else ""
    html = (template.replace("%%SPRITES%%", sprites).replace("%%BACKDROP%%", backdrop)
            .replace("__SKY_LOG__", data).replace("__SKY_LIVE__", json.dumps(live).replace("</", "<\\/"))
            .replace("__SKY_VIEW__", json.dumps(view)))
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
