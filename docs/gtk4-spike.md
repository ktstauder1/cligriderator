# Cli Griderator: GTK4 / VTE 3.91 spike (4.3.0)

The grid still runs **Gtk 3.0 + Vte 2.91**. This note is the feature-detect
hook and the breakage list, not a port. `cligrid doctor`'s `gi` row reports
whether the Gtk 4 and Vte 3.91 typelibs sit on disk; their absence is not a
failure.

## Probe

`cligrid_doctor.gtk_next_typelibs()` looks for `Gtk-4.0.typelib` and
`Vte-3.91.typelib` on `GI_TYPELIB_PATH` and the usual system directories.
The running process never `require_version("Gtk", "4.0")`: mixing 3 and 4 in
one interpreter is undefined.

Debian/Ubuntu packages to try later: `gir1.2-gtk-4.0`, `gir1.2-vte-3.91`
(name may still be `gir1.2-vte-2.91` on some releases — the typelib version
is the source of truth). Homebrew: `gtk4` and a VTE build with
`-Dvapi=true -Dgir=true` that emits 3.91.

## GTK3 APIs this tree uses that GTK4 removed

| Call site class | GTK3 | GTK4 replacement |
| --- | --- | --- |
| Layout | `Gtk.Box.pack_start` / `pack_end` | `append` / `prepend`; packing flags are gone |
| Container | `Gtk.Overlay.add`, `widget.add(child)` | `set_child` |
| Events | `Gtk.EventBox`, `add_events`, `*-event` signals | `Gtk.EventController*` / `Gtk.Gesture*` |
| Menus | `Gtk.Menu`, `Gtk.MenuItem`, `AccelLabel` | `Gio.Menu` + `Gtk.PopoverMenu` |
| Dialogs | `Gtk.Dialog.run()` (nested main loop) | `present()` + `response` signal |
| Buttons | `set_relief`, `set_image`, `set_always_show_image` | child widget; no relief |
| A11y | `get_accessible().set_name()` | `set_accessible_name()` |
| Header | `Gtk.HeaderBar.pack_start` | still present; packing API changed |
| CSS | `#define-color`, `.class` on GTK3 nodes | GTK4 widget CSS nodes renamed |
| Drawing | `Gdk.Window`, `Gdk.EventKey.keyval` | `Gdk.Surface`, `Gdk.KeyEvent` |

VTE 3.91 keeps `spawn_async` but the GIR namespace is `Vte-3.91`. Color,
scrollback and hyperlink setters exist; confirm `set_word_char_exceptions`
and `match_add_regex` against the 3.91 docs before a port.

## Suggested first slice (not done)

1. Keep GTK3 as the production path.
2. A `cligrid_gtk.py` shim with `pack`, `set_child`, `accessible_name`,
   `menu_item` — one file, two implementations, tests against 3.0.
3. Replace `Gtk.Dialog.run` with `show` + response so a later GTK4 dialog
   does not nest a main loop.
4. Broadway and `--self-test` must pass on 3.0 after each shim swap.

Native macOS/Windows signing and a live hour-long 20-pane soak are still
outside this spike.
