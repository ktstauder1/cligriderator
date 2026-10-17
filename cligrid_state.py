#!/usr/bin/env python3
"""Pure pane activity classification and best-effort process/repository details."""

import math
import re
from pathlib import Path

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_WAITING = "waiting"
STATE_EXITED = "exited"
STATE_FAILED = "failed"

SHELL_COMMANDS: frozenset[str] = frozenset({"bash", "zsh", "sh", "fish", "dash", "tmux"})
BUSY_COMMANDS: frozenset[str] = frozenset({
    "codex", "claude", "node", "npm", "npx", "python", "python3", "uv", "aider", "gemini",
})

_BARE_PROMPT = r"^\s*>\s*$"
WAITING_PATTERNS: tuple[str, ...] = (
    # Confirmation choices appear both as abbreviated hints and full words.
    r"\(\s*y\s*/\s*n\s*\)",
    r"\[\s*y\s*/\s*n\s*\]",
    r"\byes\s*/\s*no\b",
    r"\bdo you want to proceed\b",
    # Agent permission menus may prefix the selected option with a cursor.
    r"^\s*[❯>›]?\s*\d+[.)]\s+\S",
    # Paused CLIs request either a specific key or any key.
    r"\bpress\s+enter\b",
    r"\bpress\s+any\s+key\b",
    # Word boundaries avoid treating words such as 'allowed' as requests.
    r"\boverwrite\s*\?",
    r"\ballow\b",
    r"\bcontinue\s*\?",
    r"\bare you sure\b",
    # Explicit blocking messages need attention even without a question mark.
    r"\bwaiting for\b",
    # Shell continuation prompts are excluded separately by the classifier.
    _BARE_PROMPT,
)


def tail_lines(text, n=6) -> str:
    """Return the last n lines without a trailing newline, or empty for n <= 0."""
    return "\n".join(text.splitlines()[-n:]) if n > 0 else ""


def last_prompt_line(text) -> str:
    """Return the last non-empty line stripped of whitespace, or an empty string."""
    return next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")


def classify_state(text, foreground_cmd=None, exited=False, exit_status=None,
                   output_age=None) -> str:
    """Return the pane state using exit, prompt, output age, then command priority."""
    if exited:
        return STATE_FAILED if exit_status not in (0, None) else STATE_EXITED
    lines = [line for line in text.splitlines() if line.strip()][-3:]
    for pattern in WAITING_PATTERNS:
        if pattern == _BARE_PROMPT and foreground_cmd in SHELL_COMMANDS:
            continue
        if any(re.search(pattern, line, re.IGNORECASE) for line in lines):
            return STATE_WAITING
    if output_age is not None and output_age <= 1.5:
        return STATE_RUNNING
    if foreground_cmd in SHELL_COMMANDS:
        return STATE_IDLE
    if foreground_cmd:
        return STATE_RUNNING
    return STATE_IDLE


def state_badge(state) -> str:
    """Return the short badge label, or an empty string for idle/unknown states."""
    return {STATE_RUNNING: "run", STATE_WAITING: "wait", STATE_EXITED: "end",
            STATE_FAILED: "fail"}.get(state, "")


def state_rank(state) -> int:
    """Return attention priority: waiting 3, failed 2, running 1, otherwise 0."""
    return {STATE_WAITING: 3, STATE_FAILED: 2, STATE_RUNNING: 1}.get(state, 0)


def needs_input(state) -> bool:
    """Return whether the pane is waiting for user input."""
    return state == STATE_WAITING


def git_branch(path) -> str | None:
    """Read a branch or detached SHA, including worktree and submodule gitdirs."""
    try:
        directory = Path(path).expanduser().resolve()
        if directory.is_file():
            directory = directory.parent
        for candidate in (directory, *directory.parents):
            try:
                gitdir = candidate / ".git"
                if gitdir.is_file():
                    pointer = gitdir.read_text(encoding="utf-8").strip()
                    if not pointer.startswith("gitdir: "):
                        return None
                    gitdir = candidate / pointer[len("gitdir: "):]
                head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                continue
            prefix = "ref: refs/heads/"
            if head.startswith(prefix):
                return head[len(prefix):] or None
            if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", head):
                return head[:7]
            return None
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    return None


def elapsed_text(seconds) -> str:
    """Return whole seconds, minutes, or hours/minutes; invalid durations return '-'."""
    if seconds is None or seconds < 0 or not math.isfinite(seconds):
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return "%ds" % seconds
    minutes = seconds // 60
    if minutes < 60:
        return "%dm" % minutes
    return "%dh%dm" % divmod(minutes, 60)


def foreground_command(pid) -> str | None:
    """Return the terminal foreground process group's command from /proc, else None."""
    try:
        pid = int(pid)
        if pid <= 0:
            return None
        stat = Path("/proc/%d/stat" % pid).read_text(encoding="utf-8")
        # comm can contain spaces and ')', so only its final delimiter is reliable.
        closing = stat.rindex(")")
        tpgid = int(stat[closing + 1:].split()[5])
        if tpgid <= 0:
            return None
        return Path("/proc/%d/comm" % tpgid).read_text(encoding="utf-8").strip() or None
    except Exception:
        # Processes can vanish or become unreadable between the two /proc reads.
        return None
