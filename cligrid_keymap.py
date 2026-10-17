"""Keymap merge and conflict detection. No GTK.

`merge` folds a user override onto DEFAULT_KEYMAP. Empty values unbind.
`conflicts` reports unknown actions and prefix-key collisions so the
shortcuts editor can refuse a broken map before it is written.
"""
from __future__ import annotations


def merge(defaults, user):
    """Return defaults with user overrides. Empty values drop the binding."""
    out = dict(defaults)
    if not isinstance(user, dict):
        return out
    for raw_key, raw_action in user.items():
        key = str(raw_key or "").strip()
        action = str(raw_action or "").strip()
        if not key:
            continue
        if not action:
            out.pop(key, None)
            continue
        out[key] = action
    return out


def invert(keymap):
    """Map each action id to the keys that fire it, in first-seen order."""
    grouped = {}
    if not isinstance(keymap, dict):
        return grouped
    for key, action in keymap.items():
        act = str(action or "").strip()
        if not act:
            continue
        grouped.setdefault(act, []).append(str(key))
    return grouped


def known_ids(action_ids, max_panes=20):
    """Every action id the editor may bind, including focus.1 .. focus.N."""
    ids = {str(name) for name in (action_ids or ()) if name}
    for n in range(1, int(max_panes) + 1):
        ids.add("focus.%d" % n)
    return ids


def diff(defaults, merged):
    """Return the override dict that `merge(defaults, …)` would recreate.

    Keys present in defaults but missing from merged are stored as empty
    strings so they unbind. Keys that still match a default are omitted.
    """
    out = {}
    defaults = defaults if isinstance(defaults, dict) else {}
    merged = merged if isinstance(merged, dict) else {}
    for key, action in defaults.items():
        if key not in merged:
            out[key] = ""
        elif merged[key] != action:
            out[key] = merged[key]
    for key, action in merged.items():
        if key not in defaults:
            out[key] = action
    return out


def parse_fields(fields):
    """Build a keymap from (action, keys-text) rows.

    Duplicate keys keep the first binding and report the rest. Empty tokens
    are ignored. Returns (keymap, conflict-rows).
    """
    built = {}
    rows = []
    for action, text in fields or ():
        act = str(action or "").strip()
        if not act:
            continue
        for token in str(text or "").split():
            key = token.strip()
            if not key:
                continue
            if key in built and built[key] != act:
                rows.append((key, act, "already bound to %s" % built[key]))
                continue
            built[key] = act
    return built, rows


def lookup(keymap, key):
    """Return the action for a key name, trying the raw name then case variants."""
    if not isinstance(keymap, dict) or not key:
        return None
    if key in keymap:
        return keymap[key]
    lowered = key.lower()
    if lowered in keymap:
        return keymap[lowered]
    uppered = key.upper()
    if uppered != key and uppered in keymap:
        return keymap[uppered]
    return None


def resolve_shortcut(keymap, key, ctrl, shift, has_selection):
    """Pick a grid action for a key press, or None to leave the key to the pane.

    Ctrl+Shift looks up the keymap. Ctrl+C copies only when text is selected, so
    interrupt still reaches the terminal. Ctrl+V always pastes. A Ctrl press
    whose key name is already shifted (Z, Q, …) still matches the keymap,
    because GTK3 on COSMIC/Wayland often drops SHIFT_MASK.
    """
    if not key:
        return None
    keymap = keymap if isinstance(keymap, dict) else {}
    if ctrl and shift:
        return lookup(keymap, key)
    if not ctrl:
        return None
    folded = key.lower()
    if folded == "c":
        return "copy" if has_selection else None
    if folded == "v":
        return "paste"
    if key != folded:
        return lookup(keymap, key)
    return None


def conflicts(keymap, known_actions, prefix_keys=()):
    """Return (key, action, reason) tuples for a broken map.

    A key that is also a prefix key collides: the first press would fire the
    action instead of waiting for the second chord.
    """
    rows = []
    known = set(known_actions or ())
    reserved = {str(k) for k in (prefix_keys or ()) if k}
    if not isinstance(keymap, dict):
        return rows
    for key, action in keymap.items():
        act = str(action or "").strip()
        if not act:
            continue
        if known and act not in known:
            rows.append((str(key), act, "unknown action"))
        elif str(key) in reserved:
            rows.append((str(key), act, "collides with the prefix key"))
    return rows
