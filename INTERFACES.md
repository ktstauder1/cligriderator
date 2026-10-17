# Cli Griderator 4.0 interfaces

Contract for the new modules. Written before implementation so that parallel
workers produce compatible code and the main file stays the single owner of the
window, the panes, and the socket. Since 4.3 `cligrid_keymap.py` owns keymap
merge and conflict detection; `cligrid_control.py` also carries the request,
pattern and backlog bounds and the destructive-verb guard. The stylesheet and
CLI still live in `cligrid.py`.

Rules for every module below:

- Pure Python 3.12 standard library only. No `gi`, no GTK, no VTE import.
- No global mutable state except module constants and the documented classes.
- Every public function has a docstring stating what it returns.
- Ship a `unittest` file next to the module: `test_<module>.py`, runnable as
  `/usr/bin/python3 test_<module>.py`. Test edge cases, not just the happy path.
- Do not edit `cligrid.py`, `cligrid_art.py`, `README.md`, or `ROADMAP.md`.
- Style matches the existing code: four spaces, double quotes, line length
  under 100, comments that explain why rather than what.

## cligrid_state.py (worker: state)

Per pane activity classification, used for the title strip badge, the header
aggregate, notifications, and jump-to-attention.

    STATE_IDLE = "idle"       # shell sitting at a prompt
    STATE_RUNNING = "running" # a program is working
    STATE_WAITING = "waiting" # blocked on the user (confirmation, y/n, menu)
    STATE_EXITED = "exited"   # child ended cleanly
    STATE_FAILED = "failed"   # child ended with a non-zero status

    WAITING_PATTERNS: tuple[str, ...]   # regexes, matched case-insensitively
    SHELL_COMMANDS: frozenset[str]      # bash, zsh, sh, fish, dash, tmux
    BUSY_COMMANDS: frozenset[str]       # codex, claude, node, npm, python3, ...

    def tail_lines(text, n=6) -> str
    def last_prompt_line(text) -> str
    def classify_state(text, foreground_cmd=None, exited=False, exit_status=None,
                       output_age=None) -> str
    def state_badge(state) -> str          # "", "run", "wait", "end", "fail"
    def state_rank(state) -> int           # waiting 3, failed 2, running 1, else 0
    def needs_input(state) -> bool
    def git_branch(path) -> str | None     # read .git/HEAD, no subprocess
    def elapsed_text(seconds) -> str       # "12s", "4m", "1h20m", "-"
    def foreground_command(pid) -> str | None  # /proc, best effort

Classification order, first match wins:

1. `exited` and `exit_status not in (0, None)` gives failed; `exited` alone
   gives exited.
2. A waiting pattern in the last three non-empty lines gives waiting.
3. `output_age` at or below 1.5 seconds gives running.
4. `foreground_cmd` in SHELL_COMMANDS gives idle.
5. A non-empty `foreground_cmd` gives running.
6. Otherwise idle.

Waiting patterns must catch the real prompts this machine sees: `(y/n)`,
`[y/N]`, "Do you want to proceed", "Yes/No", a numbered menu line such as
`❯ 1. Yes`, "Press Enter", "press any key", "Overwrite?", "Allow", "Continue?",
"Are you sure", "Waiting for", ">" at end of an otherwise empty line only when
the pane is not a plain shell. Keep the tuple readable and comment each group.

## cligrid_layout.py (worker: layout)

Grid geometry, replacing the hardwired three column layout inside `cligrid.py`.

    SUBCOLS = 6
    SHAPES: dict[str, tuple[int, int]]  # name -> (columns, rows per screen)

    def shape_names() -> list[str]        # sorted, always includes "auto"
    def normalize_shape(name) -> str      # unknown name falls back to "auto"
    def shape_for(count, name="auto") -> tuple[int, int]   # columns, total rows
    def cells(count, shape="auto", groups=None) -> list[dict]
    def neighbor(count, pos, direction, shape="auto", groups=None) -> int
    def short_rows(count, shape="auto") -> int   # rows visible without scrolling

`cells` returns one entry per visible cell in reading order:

    {"col": int, "row": int, "span": int, "rowspan": int, "panes": [positions]}

`span` is in SUBCOLS units, so 6 columns of equal width means span 2, and
`rowspan` is how many rows the cell covers (1 for every cell except the master
pane). The last row stretches to fill the width, as today. `panes` holds more
than one position only when `groups` says those panes share a cell, which is the
tabbed stack.

Invariants the tests must assert for every shape and every count from 1 to 20:

- every position appears in exactly one cell's `panes` list;
- for every row that any cell covers, the sum of `span` over the cells covering
  that row is exactly SUBCOLS;
- `row` plus `rowspan` never exceeds `shape_for(count, name)[1]`.

`groups` is a list of position lists, for example `[[0, 1], [2]]`. Positions
inside one group share one cell; every position must appear exactly once.
Invalid groups raise `ValueError`.

Shapes to support at minimum: `auto` (current behaviour, three per row, 2x2 for
four), `1xN` and `Nx1` up to 6, `2x2`, `2x3`, `3x2`, `3x3`, `4x2`, and `master`.
`master` puts the first pane alone in a full-height left cell spanning 3 of the
6 subcolumns with `rowspan` equal to the row count; the remaining panes stack in
the right 3 subcolumns, one per row, so the row count is one less than the pane
count (a single pane in `master` is just the whole grid, rowspan 1).

## cligrid_workspace.py (worker: workspace)

Config schema 2 and workspace management. The file on disk today is schema 1:
top level `pane_count`, `panes`, and the global preference keys.

    SCHEMA_VERSION = 2
    GLOBAL_KEYS: tuple[str, ...]     # preferences that survive a switch
    WORKSPACE_KEYS: tuple[str, ...]  # pane_count, panes, layout, cwd, git_branch, sort

    def migrate(raw) -> dict          # schema 1 in, schema 2 out, idempotent
    def validate(cfg) -> dict         # clamps, repairs, returns a new dict
    def workspace_names(cfg) -> list[str]
    def active_workspace(cfg) -> dict
    def set_active(cfg, name) -> dict            # returns the config
    def add_workspace(cfg, name, panes=None, copy_from=None, layout=None) -> dict
    def remove_workspace(cfg, name) -> dict      # refuses to remove the last one
    def rename_workspace(cfg, name, new_name) -> dict
    def duplicate_workspace(cfg, name, new_name) -> dict
    def update_workspace(cfg, **fields) -> dict  # writes into the active workspace
    def slug(name) -> str                        # "Trade Desk" -> "trade-desk"

Schema 2 shape:

    {
      "version": 2,
      "active": "agents",
      "workspaces": [
        {"name": "agents", "pane_count": 6, "layout": "auto", "cwd": "~",
         "panes": [{"name": "g1", "cmd": "tmux new-session -A -s g1"}, ...]}
      ],
      "fit": "maximized", "font": "JetBrainsMono Nerd Font", ...
    }

`migrate` takes whatever `json.load` returned, including a file with none of the
new keys, and produces a valid schema 2 dict. The migrated workspace is named
after the `CLIGRID_WORKSPACE` environment variable when set, otherwise
`default`. `GLOBAL_KEYS` must cover: fit, font, font_size, min_font_size,
auto_font, min_cols, min_rows, scrollback, cursor_blink, banner, bell_alerts,
activity_marks, notify_desktop, notify_rules, quiet_hours, keymap, theme,
restore_on_start, log_level.

## cligrid_keymap.py (worker: keymap)

Pure merge and conflict detection for `config["keymap"]`. No GTK.

    def merge(defaults, user) -> dict
    def invert(keymap) -> dict                   # action -> keys, first-seen order
    def diff(defaults, merged) -> dict           # override dict merge() would rebuild
    def parse_fields(fields) -> (dict, list)     # (action, keys-text) rows
    def conflicts(keymap, known, prefix_keys=()) -> list[tuple]
    def known_ids(action_ids, max_panes=20) -> set

Empty user values unbind. Duplicate keys keep the first binding. A key that is
also a prefix key is reported so the shortcuts editor can refuse the map.

## cligrid_palette.py (worker: craft)

The command palette's matching half, and the one module here that no GTK
widgets appear in.

- `score(query, text)` returns `(score, indices)` for the best subsequence match
  or `None`. Bonuses for a word start, adjacency and matching case; a penalty
  for starting late. Bounded to 64 query characters and the first 400 of the
  text, so a keystroke over the whole palette stays under 3 ms.
- `rank(query, rows, limit=60, recents=())` copies the rows (never mutates
  them), scores each against its label and falls back to its hint, and orders by
  score then original position. With an empty query the recently chosen rows
  come first.
- `sections(rows)` groups ranked rows in `SECTION_ORDER`, then first-seen order.
- `highlight_spans(indices)` merges match indices into half-open runs for Pango
  markup.
- Rows are plain dicts with `label`, `hint` and `section` keys; the callback
  stays in the application and is attached to the `Gtk.ListBoxRow`.

## cligrid_control.py (worker: control)

Request parsing, the event log, and waiter bookkeeping for the socket protocol.
No socket objects: this module is the pure half, `cligrid.py` owns the I/O.

    VERBS: tuple[str, ...]
    def parse(line) -> dict
    def pane_positions(spec, count) -> list[int]     # "1,3,4-6" -> [1, 3, 4, 5, 6]
    def parse_wait(args) -> dict                     # {"pane", "pattern", "timeout"}
    def parse_events(args) -> dict                   # {"kinds": [...], "since": int}
    def format_event(event) -> str                   # one JSON line, trailing newline
    def event_kinds() -> list[str]

    class EventLog:
        def __init__(self, limit=500)
        def add(self, kind, **fields) -> dict   # stamps "seq" and "time"
        def since(self, seq) -> list[dict]
        def recent(self, limit=None) -> list[dict]
        def __len__(self)

Event kinds: boot, spawn, exit, bell, activity, focus, cwd, state, workspace,
layout, alert, error, reply.

`parse` returns `{"verb": str, "args": list[str], "error": str | None}`. An
unknown verb gives an error string that names the verb and suggests `help`.
`help` is a verb. Verbs to parse: the current fifteen (`show`, `raise`, `hide`,
`toggle`, `zoom`, `panes`, `windows`, `remove`, `close-window`, `restart`,
`reset`, `fresh`, `new`, `all`, `fill`, `run-all`, `fit`, `focus`, `swap`,
`status`, `quit`) plus `send`, `run`, `dump`, `wait`, `events`, `watch`,
`help`, `ws`, `workspace`, `layout`, `theme`, `doctor`, `rename`, `move`,
`palette`, `find`, `log`, `notify`, `keymap`, `state` and `version`.

`pane_positions` accepts `1,3,4-6`, `all`, the word `focused`, and whitespace.
Out of range positions set an error rather than silently dropping.

## cligrid_doctor.py (worker: tooling)

    def checks(config_path=None) -> list[dict]   # {"name", "ok", "detail", "fix"}
    def summary(rows) -> dict                    # {"ok": int, "failed": int}
    def report_text(rows) -> str                 # aligned plain text, no colour

Checks: python version, gi import of Gtk and Vte 2.91, tmux present and its
version, `fc-match` for the configured font, the config file parses, the icon
files exist under ~/.local/share/icons, the launcher exists at ~/bin/cligrid,
the desktop entry exists, the runtime directory is writable, and the session
type. Each row carries a one line `fix` when it fails.

## Tooling (worker: tooling)

- `install.sh`: idempotent, `set -euo pipefail`, takes `--prefix`, installs the
  launcher to `~/bin/cligrid`, the desktop entry, the icons at every size, and
  the man page; prints what changed; refuses to run as root.
- `cligrid.1`: man page covering the every verb from cligrid_control.VERBS.
- `pyproject.toml`: setuptools, flat `py-modules`, name `cligrid`, version
  from the same file, `[project.scripts] cligrid = "cligrid:main_entry"`,
  `readme` and homepage URL for pipx.
- `.github/workflows/ci.yml`: Python 3.12, `unittest discover`, `compileall`.
- `packaging/build-deb.sh`: builds `cligrid_4.0.0_all.deb` with `dpkg-deb`.

## Integration owned by the main file

`cligrid.py` keeps: the window, panes, VTE, CSS, the socket server, dialogs, and
the key handling. It imports the four modules above and contains no duplicated
copy of their logic.
