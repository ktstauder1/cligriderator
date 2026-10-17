"""Match, rank, group, and highlight command palette rows without GTK."""

from functools import cache


SECTION_ORDER = ('Recent', 'Actions', 'Panes', 'Workspaces', 'Themes', 'Layouts')


def score(query, text):
    """Return the best subsequence score and original-text indices, or None.

    Search only the first 64 query characters and 400 text characters.
    Equal scores prefer the earliest indices. Memoised suffix searches take
    O(len(query) * len(text)) time and space, with query-bounded recursion.
    Character-wise case folding preserves indices into the original text.
    """
    query, text = query[:64], text[:400]
    if not query:
        return 0, []
    if len(query) > len(text):
        return None
    folded = [char.casefold() for char in text]
    size = len(text)

    @cache
    def search(q):
        # Exact scores start at each position; suffix indices identify the
        # best non-adjacent candidate at or after each position.
        exact = [None] * size
        following = [None] * size
        suffix = [None] * (size + 1)
        next_layer = search(q + 1) if q + 1 < len(query) else None
        needle = query[q].casefold()
        for i in range(size - 1, -1, -1):
            if folded[i] == needle:
                value = 10 + 12 * (i == 0 or not text[i - 1].isalnum())
                value += 3 * (query[q] == text[i])
                if q == 0:
                    value -= min(12, i)
                if next_layer is None:
                    exact[i] = value
                else:
                    next_scores, _, next_suffix = next_layer
                    best = next_suffix[i + 1]
                    if best is not None:
                        tail = next_scores[best]
                        if i + 1 < size and next_scores[i + 1] is not None:
                            adjacent = next_scores[i + 1] + 9
                            if adjacent >= tail:
                                best, tail = i + 1, adjacent
                        exact[i] = value + tail
                        following[i] = best
            best = suffix[i + 1]
            if exact[i] is not None and (best is None or exact[i] >= exact[best]):
                best = i
            suffix[i] = best
        return exact, following, suffix

    exact, _, suffix = search(0)
    position = suffix[0]
    if position is None:
        search.cache_clear()
        return None
    value = exact[position]
    indices = []
    for q in range(len(query)):
        indices.append(position)
        position = search(q)[1][position]
    search.cache_clear()
    return value, indices


def rank(query, rows, limit=60, recents=()):
    """Return copied rows ranked by label matches, falling back to hints."""
    if limit <= 0:
        return []
    if not query:
        recent_order = {}
        for label in recents:
            recent_order.setdefault(label, len(recent_order))
        ordered = sorted(rows, key=lambda row: recent_order.get(row['label'], len(recent_order)))
        return [dict(row, score=0, match=[],
                     section='Recent' if row['label'] in recent_order else row['section'])
                for row in ordered[:limit]]
    result = []
    for row in rows:
        matched = score(query, row['label'])
        if matched is not None:
            value, indices = matched
        else:
            matched = score(query, row['hint'])
            if matched is None:
                continue
            value, indices = matched[0], []
        result.append(dict(row, score=value, match=indices))
    result.sort(key=lambda row: -row['score'])
    return result[:limit]


def sections(rows):
    """Group ranked rows in standard section order, then first-seen order."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row['section'], []).append(row)
    names = [name for name in SECTION_ORDER if name in grouped]
    names.extend(name for name in grouped if name not in SECTION_ORDER)
    return [(name, grouped[name]) for name in names]


def highlight_spans(indices):
    """Merge match indices into sorted, half-open contiguous spans."""
    spans = []
    for index in sorted(set(indices)):
        if spans and index == spans[-1][1]:
            spans[-1] = (spans[-1][0], index + 1)
        else:
            spans.append((index, index + 1))
    return spans
