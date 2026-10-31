# Sky Huddle character pack v1

Ava, Pip and Gus, based on the approved group-logo design. Cute full-body pixel-art characters, one transparent PNG per person.

## Files and IDs

| Agent ID in the app | Character | PNG |
|---|---|---|
| atc | Ava — Air Traffic Control | ava.png |
| pilot | Pip — Pilot | pip.png |
| ground | Gus — Ground Operations | gus.png |

All three are original RGBA PNGs, 1080 × 1457 pixels, with transparent backgrounds. They are larger masters, **not native 40 × 54 pixel files**. Display each on the existing 40 × 54 pixel canvas. Use nearest-neighbour rendering and preserve alpha. The matching aspect ratio makes them suitable for the current layout.

Pose: static idle. No walk, talk, blink or reaction frames are included. Existing wrapper bobbing can continue; a PNG does not automatically provide the old procedural eye-blink animation.

## Add through GitHub

1. Copy this ui/assets/characters directory into the existing repository, preserving that folder path.
2. In VS Code, review and stage the new character files, write a commit message, and push a feature branch.
3. Open a pull request. Dafeng can review and merge it, then pull the shared branch before integrating.
4. Commit the PNGs, manifest and this README. The preview and generation notes are optional supporting files.

Suggested branch: yizhuo/character-assets
Suggested commit: Add Ava, Pip and Gus character assets

## Integration notes for Dafeng

The current app builds 20 × 27 logical sprites at 2× scale, yielding 40 × 54 canvas pixels. Keep the existing actor placement and display footprint.

ui/replay.py embeds the replay as an HTML string. Relative PNG paths will not automatically resolve inside the Streamlit component. Use the same base64/data-URL pattern already used for backdrop.png:

    character_pngs = {
        agent_id: "data:image/png;base64," + base64.b64encode(
            (HERE / "assets" / "characters" / filename).read_bytes()
        ).decode()
        for agent_id, filename in {
            "atc": "ava.png", "pilot": "pip.png", "ground": "gus.png"
        }.items()
    }
    sprites = "const SKY_CHARACTER_PNGS = " + json.dumps(character_pngs) + ";\n" + sprites

Then extend the existing drawSprite function in ui/_sprites.js to draw these PNGs for atc/pilot/ground on the 40 × 54 canvas:

- Cache one Image object per agent.
- Draw after the image is loaded.
- Set canvas width = 40 and height = 54.
- Set context.imageSmoothingEnabled = false before context.drawImage(image, 0, 0, 40, 54).
- Clear the canvas before redrawing.
- Keep the current procedural sprites for mod/custom and as the image-error fallback.
- Treat the new PNGs as idle art; skip procedural blinking for them until matching blink frames exist.

This is an integration guide, not an applied patch. It leaves Dafeng's current source files untouched.

## Review

Open the included character-preview.html in a browser. It shows the characters at the actual 40 × 54 display size and at 4× size, on a checkerboard transparency background.

Generation method and exact prompts are recorded in GENERATION_PROMPTS.md at the package root.

