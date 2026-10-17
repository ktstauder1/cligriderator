"""Schema 2 workspace management, independent of the terminal UI.

Operations return independent config dictionaries. Display names retain their
text; lookups also accept their CLI slug. Adding or copying does not switch the
active workspace. Unknown names and name collisions leave the config unchanged.
"""

from copy import deepcopy
import os
import re
import shlex
import unicodedata

SCHEMA_VERSION = 2
GLOBAL_KEYS = (
    "fit", "font", "font_size", "min_font_size", "auto_font", "min_cols",
    "min_rows", "scrollback", "cursor_blink", "banner", "bell_alerts",
    "activity_marks", "notify_desktop", "notify_rules", "quiet_hours", "keymap",
    "theme", "restore_on_start", "log_level", "prefix", "fill_cmd", "guard",
)
WORKSPACE_KEYS = ("pane_count", "panes", "layout", "cwd", "git_branch", "sort", "stack")
_SHAPES = frozenset(
    ("auto", "master", "2x2", "2x3", "3x2", "3x3", "4x2")
    + tuple(f"1x{n}" for n in range(1, 7))
    + tuple(f"{n}x1" for n in range(1, 7))
)


def slug(name) -> str:
    """Return a lowercase CLI slug, retaining Unicode letters and digits.

    Punctuation and whitespace become hyphens; empty slugs become "default".
    """
    text = unicodedata.normalize("NFKC", str(name)).casefold()
    return re.sub(r"[\W_]+", "-", text).strip("-") or "default"


def _name(value, fallback="default"):
    return value if isinstance(value, str) and value.strip() else fallback


def _count(value):
    try:
        return max(1, min(20, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 6


def _taken(panes):
    names = set()
    for pane in panes:
        if not isinstance(pane, dict):
            continue
        names.add(str(pane.get("name", "")))
        cmd = pane.get("cmd", "")
        if not isinstance(cmd, str):
            continue
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
        if not parts or os.path.basename(parts[0]) != "tmux":
            continue
        for flag in ("-s", "-t"):
            if flag in parts:
                index = parts.index(flag)
                if index + 1 < len(parts):
                    names.add(parts[index + 1])
    return names


def _panes(raw, count):
    source = raw if isinstance(raw, list) else []
    panes = []
    for index in range(count):
        # Reserve later names and command targets before filling a damaged slot.
        taken = _taken(panes + source[index:count])
        fallback = f"g{index + 1}"
        number = 1
        while fallback in taken:
            fallback = f"g{number}"
            number += 1
        pane = source[index] if index < len(source) else None
        pane = pane if isinstance(pane, dict) else {}
        name = _name(pane.get("name"), fallback)
        cmd = pane.get("cmd")
        if not isinstance(cmd, str):
            cmd = f"tmux new-session -A -s {shlex.quote(name)}"
        panes.append({"name": name, "cmd": cmd})
    return panes


def _workspace(raw, name):
    result = deepcopy(raw)
    result["name"] = name
    panes = result.get("panes")
    inferred = len(panes) if isinstance(panes, list) and panes else 6
    result["pane_count"] = _count(result.get("pane_count", inferred))
    result["panes"] = _panes(panes, result["pane_count"])
    layout = result.get("layout")
    result["layout"] = layout if isinstance(layout, str) and layout in _SHAPES else "auto"
    result["cwd"] = _name(result.get("cwd"), "~")
    if "git_branch" in result and not isinstance(result["git_branch"], (str, type(None))):
        result["git_branch"] = None
    if "sort" in result and not isinstance(result["sort"], str):
        result["sort"] = "manual"
    stack = result.get("stack")
    groups = []
    if isinstance(stack, list):
        for group in stack:
            if isinstance(group, list) and group:
                cleaned = []
                for item in group:
                    try:
                        index = int(item)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if 0 <= index < result["pane_count"]:
                        cleaned.append(index)
                if cleaned:
                    groups.append(cleaned)
    result["stack"] = groups
    return result


def _find(cfg, name):
    if not isinstance(name, str):
        return None
    for workspace in cfg["workspaces"]:
        if workspace["name"] == name or slug(workspace["name"]) == slug(name):
            return workspace
    return None


def validate(cfg) -> dict:
    """Return a repaired, independent schema 2 dict, including for damaged JSON.

    Preserve global preferences and unknown metadata. Duplicate workspace names
    receive numeric suffixes so repairing names never discards a workspace.
    """
    result = deepcopy(cfg) if isinstance(cfg, dict) else {}
    source = result.get("workspaces")
    if not isinstance(source, list) or not any(isinstance(item, dict) for item in source):
        source = [{key: result[key] for key in WORKSPACE_KEYS if key in result}]
        source[0]["name"] = _name(os.environ.get("CLIGRID_WORKSPACE"))
    workspaces = []
    taken = set()
    for item in source:
        if not isinstance(item, dict):
            continue
        base = _name(item.get("name"))
        name = base
        suffix = 2
        while slug(name) in taken:
            name = f"{base}-{suffix}"
            suffix += 1
        taken.add(slug(name))
        workspaces.append(_workspace(item, name))
    result["version"] = SCHEMA_VERSION
    result["workspaces"] = workspaces
    active = _find(result, result.get("active")) or workspaces[0]
    result["active"] = active["name"]
    # Workspace data has one owner in schema 2; stale top-level copies can drift.
    for key in WORKSPACE_KEYS:
        result.pop(key, None)
    return result


def migrate(raw) -> dict:
    """Return a valid schema 2 copy of schema 1 or schema 2 JSON, idempotently."""
    return validate(raw)


def workspace_names(cfg) -> list[str]:
    """Return stored display names in workspace order."""
    return [workspace["name"] for workspace in validate(cfg)["workspaces"]]


def active_workspace(cfg) -> dict:
    """Return an independent copy of the active workspace, repairing config first."""
    result = validate(cfg)
    return _find(result, result["active"])


def set_active(cfg, name) -> dict:
    """Return a config copy selecting name or its slug; unknown names are ignored."""
    result = validate(cfg)
    workspace = _find(result, name)
    if workspace is None:
        return deepcopy(cfg)
    result["active"] = workspace["name"]
    return result


def add_workspace(cfg, name, panes=None, copy_from=None, layout=None) -> dict:
    """Return a config copy with a new workspace, retaining the active selection.

    copy_from names a workspace to deep-copy. Explicit panes and layout override
    its values. Invalid names, missing sources and slug collisions are refused.
    """
    result = validate(cfg)
    if not isinstance(name, str) or not name.strip() or _find(result, name) is not None:
        return deepcopy(cfg)
    source = {}
    if copy_from is not None:
        source = _find(result, copy_from)
        if source is None:
            return deepcopy(cfg)
    source = deepcopy(source)
    if panes is not None:
        source["panes"] = deepcopy(panes)
        source["pane_count"] = len(panes) if isinstance(panes, list) else 6
    if layout is not None:
        source["layout"] = layout
    result["workspaces"].append(_workspace(source, name))
    return result


def remove_workspace(cfg, name) -> dict:
    """Return a config copy removing name; unknown or last workspaces are refused."""
    result = validate(cfg)
    workspace = _find(result, name)
    if workspace is None or len(result["workspaces"]) == 1:
        return deepcopy(cfg)
    result["workspaces"].remove(workspace)
    if result["active"] == workspace["name"]:
        result["active"] = result["workspaces"][0]["name"]
    return result


def rename_workspace(cfg, name, new_name) -> dict:
    """Return a renamed config copy, refusing missing sources or occupied slugs."""
    result = validate(cfg)
    workspace = _find(result, name)
    if (workspace is None or not isinstance(new_name, str) or not new_name.strip()
            or _find(result, new_name) is not None):
        return deepcopy(cfg)
    if result["active"] == workspace["name"]:
        result["active"] = new_name
    workspace["name"] = new_name
    return result


def duplicate_workspace(cfg, name, new_name) -> dict:
    """Return a config copy with an independent duplicate, refusing name collisions."""
    return add_workspace(cfg, new_name, copy_from=name)


def update_workspace(cfg, **fields) -> dict:
    """Return a config copy with recognized active workspace fields updated/repaired."""
    result = validate(cfg)
    workspace = _find(result, result["active"])
    workspace.update({key: deepcopy(value) for key, value in fields.items()
                      if key in WORKSPACE_KEYS})
    return validate(result)
