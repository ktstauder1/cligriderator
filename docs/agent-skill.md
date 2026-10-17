# Drive Cli Griderator from an agent

Use the `cligrid` CLI. Do not call `tmux` unless a cligrid verb cannot do the job.

## Observe (always allowed)

```
cligrid status          # JSON when piped; window, panes, rss_mb, states
cligrid state           # idle / running / waiting / exited / failed
cligrid dump N --lines K
cligrid find TEXT
cligrid wait N --until REGEX [--timeout SECONDS]
cligrid events --kinds bell,exit,state,wait
cligrid doctor
```

`dump` reaches tmux scrollback. `wait` patterns are at most 256 characters.

## Act on one pane

```
cligrid focus N
cligrid send N TEXT          # no newline unless --enter
cligrid run N COMMAND        # types the command and Enter
cligrid restart N            # reconnect; the tmux session is kept
```

## Destructive verbs (guarded)

`reset`, `fresh`, `new`, `all`, `fill`, `run-all`, `remove`, `close-window` and `quit` are refused when this process is running inside a grid pane (`CLIGRID=1`). That is the usual case for a coding agent.

To run one anyway:

```
cligrid reset --force 2
cligrid all --force htop
cligrid quit --force
```

`--force` must sit directly after the verb so `all git push --force` still reaches git. Prefer asking the person at the grid before using `--force`. Work in a pane survives `cligrid quit` without `--force`; it does not survive `reset` or `all`.

Set `"guard": "off"` in `~/.config/cligrid/config.json` only if every pane should be allowed to end sessions.

## Layout and workspaces

```
cligrid ws                  # list; current is marked
cligrid ws NAME
cligrid layout master
cligrid theme high-contrast
cligrid notify "done"
```

## Rules

- One verb per invocation. Do not chain shell `&&` through `cligrid all`.
- Never `tmux kill-session` by name guessed from a pane title.
- If `cligrid` prints `not running`, start it with `cligrid` and wait for `cligrid status`.
- `CLIGRID=1` and `CLIGRID_SLOT` are set in every pane; do not leak them into a relaunch of the grid itself.
