"""Pure parsing and event bookkeeping for Cli Griderator's one-line protocol.

Legacy argument splitting follows CliGrid.dispatch. Runtime-dependent bounds
and actions remain the caller's responsibility; static usage messages use 1-20.
The empty selector result for ``focused`` asks the caller to resolve its active pane.
"""

from collections import deque
import json
import math
import re
import shlex
import time


_LEGACY = frozenset(
    "show raise hide toggle zoom panes windows remove close-window restart reset fresh new "
    "all fill run-all fit focus swap status quit layout".split()
)
VERBS: tuple[str, ...] = tuple(sorted(_LEGACY | frozenset(
    "send run dump wait events watch help ws workspace theme doctor rename move palette "
    "find log notify keymap state version stack".split()
)))
_EVENT_KINDS = (
    "boot", "spawn", "exit", "bell", "activity", "focus", "cwd", "state",
    "workspace", "layout", "alert", "error", "reply", "toast",
)
# Verbs that end sessions, drop panes or close the window. With the default
# `guard: "panes"` they are refused when the request comes from a process
# inside one of the grid's own panes (a coding agent, say) unless it carries
# --force straight after the verb.
GUARDED_VERBS = frozenset(("reset", "fresh", "new", "all", "fill", "run-all",
                           "remove", "close-window", "quit"))
GUARD_MODES = ("panes", "off")


def split_force(tokens) -> tuple[list, bool]:
    """(tokens without a --force directly after the verb, whether it was there).

    Only that position counts, so `all git push --force` still reaches the
    panes with its own --force intact.
    """
    tokens = list(tokens)
    if len(tokens) >= 2 and tokens[1] == "--force":
        del tokens[1]
        return tokens, True
    return tokens, False


def guard_refusal(verb, forced, from_pane, mode="panes") -> str | None:
    """The refusal text for a guarded verb, or None when it may run."""
    if mode != "panes" or verb not in GUARDED_VERBS or forced or not from_pane:
        return None
    return ("refused: %s came from inside a pane; run it from a terminal outside the "
            "grid, add --force after the verb, or set \"guard\": \"off\" in the config"
            % verb)


# Bounds the socket owner enforces. A request is one line; a wait pattern runs
# on the window's main thread every poll, so its size is capped as well.
MAX_REQUEST_BYTES = 64 * 1024
MAX_PATTERN_CHARS = 256
MAX_PENDING_BYTES = 1024 * 1024  # unread output a slow `events` reader may hold


def _legacy_error(verb, args):
    arg = args[0] if args else None
    usage = None
    if verb == "zoom" and arg not in (None, "toggle", "off"):
        usage = "zoom expects a pane number 1-20 or off"
    elif verb in ("panes", "windows") and arg is not None:
        usage = "panes expects a count from 1 to 20"
    elif verb in ("remove", "close-window") and arg is not None:
        usage = "remove expects a window number 1-20"
    elif verb == "restart" and arg is not None:
        usage = "restart expects a pane number 1-20"
    elif verb in ("reset", "fresh", "new") and arg is not None:
        usage = "reset expects a pane number 1-20, or no argument for every pane"
    elif verb == "focus":
        usage = "focus expects a pane number 1-20"
    elif verb == "swap":
        try:
            a, b = int(args[0]), int(args[1])
        except (ValueError, IndexError):
            return "swap expects two positions, e.g. swap 1 6"
        if not (1 <= a <= 20 and 1 <= b <= 20):
            return "swap positions are 1-20"
    if usage is not None:
        try:
            n = int(arg)
        except (TypeError, ValueError):
            return usage
        if verb == "focus" and not 1 <= n <= 20:
            return usage
        # Removal/reset use Python indexing today, including zero and negatives.
        # Tighter bounds depend on the live order, so the caller checks them.
        if verb in ("remove", "close-window", "restart", "reset", "fresh", "new"):
            if not -19 <= n <= 20:
                return usage
    return None


def parse(line) -> dict:
    """Return {verb, args, error}; errors omit the transport's trailing newline.

    Alias spellings are retained. Legacy commands keep whitespace tokens and
    ignored extra arguments. all/fill/run-all return their intact shell command
    as one argument so quoting and internal whitespace survive dispatch.
    New commands use shell-style quoting. Only wait/events/watch have a specified
    option grammar here; other new commands pass their arguments to the caller.
    """
    parts = line.split()
    verb = parts[0] if parts else "show"
    args = parts[1:]
    error = None
    if verb not in VERBS:
        error = "unknown command: %s; try help" % verb
    elif verb in ("all", "fill", "run-all"):
        # Preserve the old dispatcher's literal-space check as well as its payload.
        tail = line.split(None, 1)
        command = tail[1] if " " in line and len(tail) > 1 else ""
        args = [command] if command.strip() else []
        if not args:
            error = "all expects a command, e.g. all htop"
    elif verb in _LEGACY:
        error = _legacy_error(verb, args)
    else:
        try:
            args = shlex.split(line)[1:]
            if verb == "wait":
                parse_wait(args)
            elif verb in ("events", "watch"):
                parse_events(args)
        except ValueError as exc:
            error = str(exc)
    return {"verb": verb, "args": args, "error": error}


def _nonnegative_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("%s must be a non-negative integer" % name)
    return value


def pane_positions(spec, count) -> list[int]:
    """Return sorted unique 1-based positions, or [] for caller-resolved focused.

    Accept commas or whitespace between positions and either range direction.
    Raise ValueError for invalid syntax, count, or an out-of-range endpoint.
    """
    _nonnegative_integer(count, "pane count")
    if not isinstance(spec, str):
        raise ValueError("pane specification must be text")
    spec = spec.strip()
    if spec == "all":
        return list(range(1, count + 1))
    if spec == "focused":
        return []
    if not spec:
        raise ValueError("pane specification is empty")
    positions = set()
    for group in spec.split(","):
        group = re.sub(r"\s*-\s*", "-", group.strip())
        if not group:
            raise ValueError("empty pane position in specification")
        for token in group.split():
            if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", token):
                raise ValueError("invalid pane position: %s" % token)
            endpoints = [int(value) for value in token.split("-")]
            low, high = min(endpoints), max(endpoints)
            if low < 1 or high > count:
                raise ValueError("pane positions must be in 1-%d: %s" % (count, token))
            positions.update(range(low, high + 1))
    return sorted(positions)


def _wait_values(pane, pattern, timeout):
    try:
        pane = int(pane)
    except (TypeError, ValueError):
        raise ValueError("wait expects a pane number 1-20") from None
    if not 1 <= pane <= 20:
        raise ValueError("wait expects a pane number 1-20")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("wait expects a pattern")
    if len(pattern) > MAX_PATTERN_CHARS:
        raise ValueError("wait pattern is longer than %d characters" % MAX_PATTERN_CHARS)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError("invalid wait regex: %s" % exc) from None
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        raise ValueError("wait timeout must be a finite non-negative number") from None
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("wait timeout must be a finite non-negative number")
    return {"pane": pane, "pattern": pattern, "timeout": timeout}


def parse_wait(args) -> dict:
    """Return {pane, pattern, timeout} for N PATTERN [SECONDS] or named options.

    --until PATTERN and --timeout SECONDS may follow the pane in either order.
    The timeout defaults to 30 seconds. Invalid options or values raise ValueError.
    """
    if not args:
        raise ValueError("wait expects a pane number and pattern")
    values = {}
    i = 1
    while i < len(args):
        token = args[i]
        if token in ("--until", "--timeout"):
            key = "pattern" if token == "--until" else "timeout"
            i += 1
            if i == len(args):
                raise ValueError("wait expects a %s after %s" % (key, token))
            value = args[i]
        elif token.startswith("--"):
            raise ValueError("unknown wait option: %s" % token)
        else:
            key = "pattern" if "pattern" not in values else "timeout"
            value = token
        if key in values:
            raise ValueError("duplicate wait %s or extra argument" % key)
        values[key] = value
        i += 1
    return _wait_values(args[0], values.get("pattern"), values.get("timeout", 30.0))


def parse_events(args) -> dict:
    """Return {kinds: list, since: int}; accept --follow without adding a key.

    An empty kinds list means no filter. The socket owner handles following;
    unknown event kinds/options and invalid sequence values raise ValueError.
    """
    kinds = []
    since = 0
    i = 0
    while i < len(args):
        option = args[i]
        if option == "--follow":
            i += 1
            continue
        if option not in ("--kinds", "--since"):
            raise ValueError("unknown events option: %s" % option)
        i += 1
        if i == len(args):
            raise ValueError("events %s expects a value" % option)
        if option == "--kinds":
            for kind in args[i].split(","):
                kind = kind.strip()
                if kind not in _EVENT_KINDS:
                    raise ValueError("unknown event kind: %s" % kind)
                if kind not in kinds:
                    kinds.append(kind)
        else:
            try:
                since = int(args[i])
            except ValueError:
                raise ValueError("events --since expects a non-negative integer") from None
            _nonnegative_integer(since, "events --since")
        i += 1
    return {"kinds": kinds, "since": since}


def _safe_str(value):
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


def format_event(event) -> str:
    """Return one newline-terminated JSON line, falling back to str for bad values.

    Circular structures or invalid mapping keys fall back to a JSON string of
    the whole event. Even a broken __str__ gets a serializable placeholder.
    """
    try:
        return json.dumps(event, default=_safe_str, allow_nan=False) + "\n"
    except Exception:
        return json.dumps(_safe_str(event)) + "\n"


def event_kinds() -> list[str]:
    """Return a fresh list of the protocol's supported event kinds."""
    return list(_EVENT_KINDS)


class EventLog:
    """Bounded in-memory event history with sequence numbers starting at one."""

    def __init__(self, limit=500):
        """Initialize an empty log retaining at most limit entries; return None."""
        self._events = deque(maxlen=_nonnegative_integer(limit, "event limit"))
        self._seq = 0

    def add(self, kind, **fields) -> dict:
        """Append and return an event, overriding supplied seq/time with fresh stamps."""
        self._seq += 1
        event = dict(fields, kind=kind, seq=self._seq, time=time.time())
        self._events.append(event)
        return event

    def since(self, seq) -> list[dict]:
        """Return retained events strictly after seq, in oldest-first order."""
        return [event for event in self._events if event["seq"] > seq]

    def recent(self, limit=None) -> list[dict]:
        """Return the newest limit events in oldest-first order; None returns all."""
        events = list(self._events)
        if limit is None:
            return events
        _nonnegative_integer(limit, "recent limit")
        return events[-limit:] if limit else []

    def __len__(self):
        """Return the number of retained events."""
        return len(self._events)


class Waiter:
    """Pure regex/deadline bookkeeping; the caller owns polling and completion."""

    def __init__(self, pane, pattern, timeout=30.0, now=None):
        """Initialize from parse_wait fields and optional monotonic time; return None."""
        values = _wait_values(pane, pattern, timeout)
        self.pane = values["pane"]
        self.pattern = values["pattern"]
        self.timeout = values["timeout"]
        self._regex = re.compile(self.pattern)
        self.deadline = (time.monotonic() if now is None else now) + self.timeout

    def matches(self, pane, text):
        """Return whether text from the requested pane contains the regex pattern."""
        return pane == self.pane and self._regex.search(text) is not None

    def expired(self, now=None):
        """Return whether the monotonic deadline has been reached."""
        return (time.monotonic() if now is None else now) >= self.deadline
