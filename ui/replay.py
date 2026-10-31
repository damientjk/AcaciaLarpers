"""Build the pixel-art replay page for one audit log.

    from ui.replay import replay_html
    import streamlit.components.v1 as components
    components.html(replay_html(log), height=1250, scrolling=True)
"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def replay_html(log: dict) -> str:
    template = (HERE / "replay_template.html").read_text()
    sprites = (HERE / "_sprites.js").read_text()
    data = json.dumps(log).replace("</", "<\\/")  # keep the JSON from closing the script tag
    return template.replace("%%SPRITES%%", sprites).replace("__SKY_LOG__", data)


if __name__ == "__main__":
    # python ui/replay.py fixtures/sample_logs/demo_consensus.json  -> writes ui/replay_demo.html
    import sys
    src = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "fixtures/sample_logs/demo_consensus.json")
    out = HERE / "replay_demo.html"
    out.write_text(replay_html(json.loads(src.read_text())))
    print("wrote", out)
