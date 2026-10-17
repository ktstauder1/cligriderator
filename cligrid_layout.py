"""Pure grid geometry in six integer subcolumns.

Shape names are columns x rows per screen, with overflow continuing downwards.
Four/five-column rows distribute remainder subcolumns to the leftmost cells.
Groups are compacted in order of their lowest pane position, preserving tab order
inside each group. Master uses the group containing pane zero as its left cell.
"""

SUBCOLS = 6
SHAPES: dict[str, tuple[int, int]] = {
    "auto": (3, 2),
    "master": (2, 2),
    **{f"1x{n}": (1, n) for n in range(1, 7)},
    **{f"{n}x1": (n, 1) for n in range(1, 7)},
    "2x2": (2, 2),
    "2x3": (2, 3),
    "3x2": (3, 2),
    "3x3": (3, 3),
    "4x2": (4, 2),
}


def _integer(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _count(count):
    return max(1, _integer(count, 1))


def shape_names() -> list[str]:
    """Return a fresh sorted list of supported names, including auto."""
    return sorted(SHAPES)


def normalize_shape(name) -> str:
    """Return name if supported, otherwise auto; matching is exact."""
    return name if isinstance(name, str) and name in SHAPES else "auto"


def shape_for(count, name="auto") -> tuple[int, int]:
    """Return (columns, total rows), coercing count to an integer of at least one."""
    count = _count(count)
    name = normalize_shape(name)
    if name == "master":
        return min(2, count), max(1, count - 1)
    columns = SHAPES[name][0]
    if name == "auto" and count == 4:
        columns = 2
    columns = min(columns, count)
    return columns, (count + columns - 1) // columns


def short_rows(count, shape="auto") -> int:
    """Return the visible row capacity, independent of the occupied row count.

    Auto, master and multi-axis shapes retain the current two-row capacity.
    Explicit 1xN/Nx1 shapes use max(2, N), allowing more rows before scrolling.
    """
    shape = normalize_shape(shape)
    columns, rows = SHAPES[shape]
    if shape not in ("auto", "master") and 1 in (columns, rows):
        return max(2, columns, rows)
    return 2


def _groups(count, groups):
    if groups is None:
        return [[pos] for pos in range(count)]
    if not isinstance(groups, list):
        raise ValueError("groups must be a list of nonempty position lists")
    seen = set()
    result = []
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError("each group must be a nonempty position list")
        for pos in group:
            if type(pos) is not int or not 0 <= pos < count or pos in seen:
                raise ValueError("group positions must be unique integers in range(count)")
            seen.add(pos)
        result.append(list(group))
    if len(seen) != count:
        raise ValueError("groups must include every position exactly once")
    return sorted(result, key=min)


def cells(count, shape="auto", groups=None) -> list[dict]:
    """Return reading-order cell dicts with col, row, span, rowspan and panes.

    Groups must partition the normalized pane positions or ValueError is raised.
    Geometry uses the number of groups; one group fills the grid even in master.
    """
    panes = _groups(_count(count), groups)
    shape = normalize_shape(shape)
    columns, rows = shape_for(len(panes), shape)
    if shape == "master" and len(panes) > 1:
        return [dict(col=0, row=0, span=3, rowspan=rows, panes=panes[0])] + [
            dict(col=3, row=pos - 1, span=3, rowspan=1, panes=group)
            for pos, group in enumerate(panes[1:], 1)
        ]
    result = []
    for start in range(0, len(panes), columns):
        row_groups = panes[start:start + columns]
        width, extra = divmod(SUBCOLS, len(row_groups))
        col = 0
        for index, group in enumerate(row_groups):
            span = width + (index < extra)
            result.append(dict(col=col, row=start // columns, span=span,
                               rowspan=1, panes=group))
            col += span
    return result


def neighbor(count, pos, direction, shape="auto", groups=None) -> int:
    """Return the neighboring cell's first tab, or pos at an edge/unknown direction.

    Movement probes just beyond the source edge at its perpendicular midpoint,
    using half-open cell bounds (as auto did). This accounts for master rowspan;
    moving right from master selects the middle right cell. Invalid positions
    are clamped to the normalized count, so the result is always in range.
    """
    count = _count(count)
    pos = max(0, min(count - 1, _integer(pos, 0)))
    grid = cells(count, shape, groups)
    source = next(cell for cell in grid if pos in cell["panes"])
    x = source["col"] + source["span"] / 2
    y = source["row"] + source["rowspan"] / 2
    if direction == "left":
        x = source["col"] - 0.5
    elif direction == "right":
        x = source["col"] + source["span"]
    elif direction == "up":
        y = source["row"] - 0.5
    elif direction == "down":
        y = source["row"] + source["rowspan"]
    else:
        return pos
    for cell in grid:
        if (cell["col"] <= x < cell["col"] + cell["span"]
                and cell["row"] <= y < cell["row"] + cell["rowspan"]):
            return cell["panes"][0]
    return pos
