# Workspace design overhaul

Native GTK3/VTE redesign of the existing terminal workspace. The revised direction uses midnight blue, luminous white text, and a golden accent. Electric blue, orchid, turquoise, mint, gold, and coral distinguish the six repeating pane positions. Solid number badges, tinted title strips, and saturated top edges carry color throughout the workspace; the focused pane has a stronger tint and outline. The cleaner layout, 14px grid gaps, 18px outer spacing, and larger controls remain. Noto Sans is the available fallback for Inter.

The terminal ANSI palette, welcome-banner fallback colors, and Windows Terminal scheme use the revised colors. Each pane color exceeds 4.5:1 contrast against the terminal background (measured range: 6.73–12.26:1).

The command palette has a larger search field, more legible section spacing, and roomier result rows. A title-bar search button opens the existing command palette. Pane actions remain visible at reduced emphasis and brighten on focus or hover.

## Verification

- `/usr/bin/python3 -m unittest discover -q`: 298 tests passed, with local socket access enabled.
- GTK CssProvider accepted generated CSS for every built-in theme.
- `git diff --check`: passed.
- Native GTK preview: inspected six panes, focused and inactive pane styling, narrowed titles and paths, and the open command palette.
- Screenshots use sample output in actual VTE widgets; spawning, persistence, and the control socket were disabled in the preview.
- Live session workflows, 20-pane layouts, macOS/Windows rendering, and slow-motion transitions were not verified.

## Design review

Full review of the changed GTK workspace and palette styling; other dialogs retain their existing structure.

| Category | Evidence | Result |
| --- | --- | --- |
| Typography | UI font stack, pane labels, palette screenshot | Clear in inspected states |
| Surfaces | Header, pane CSS, native screenshots | Tinted headers, gradient badges, and layered focus glow |
| Animations | Existing color/opacity transitions | Timing unchanged; slow-motion behavior not verified |
| Icons | Existing GTK symbolic controls and new search button | Same icon family; larger pane targets |
| Performance | Stylesheet and widget changes | No new timers or dependencies; not profiled |

The current direction adds layered focus glow, gradient badges, fine edge highlights, and a softly lit title bar. Glow is concentrated on active and hovered controls, with opaque terminal surfaces for readable text. The command center includes a title and adjusts result height to keep its keyboard hints visible in short windows. Considered adding an always-visible sidebar but rejected it because it would reduce terminal columns. Existing alternate themes remain available.

Screenshots: [workspace](luminous-workspace.png), [command center](luminous-commands.png).

Changes remain uncommitted alongside pre-existing release work; the installed application has not been replaced.
