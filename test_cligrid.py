#!/usr/bin/env python3
"""Unit tests for Cli Griderator helpers. Run: python3 test_cligrid.py"""

import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import subprocess

import cligrid
import cligrid_art
import cligrid_control


class DecideChildExitActionTests(unittest.TestCase):
    def test_respawn_when_the_user_exits_a_pane(self):
        self.assertEqual(
            cligrid.decide_child_exit_action(quitting=False, pending_fresh=False),
            "respawn",
        )

    def test_ignore_while_the_app_is_quitting(self):
        self.assertEqual(
            cligrid.decide_child_exit_action(quitting=True, pending_fresh=False),
            "ignore",
        )

    def test_ignore_when_a_fresh_spawn_is_already_queued(self):
        self.assertEqual(
            cligrid.decide_child_exit_action(quitting=False, pending_fresh=True),
            "ignore",
        )

    def test_ignore_when_the_pane_never_started(self):
        self.assertEqual(
            cligrid.decide_child_exit_action(
                quitting=False, pending_fresh=False, spawned=False
            ),
            "ignore",
        )


class KittyThemeTests(unittest.TestCase):
    SAMPLE = """
# comment
foreground #c0caf5
background #1a1b26
color0  #15161e
color1  #f7768e
color2  #9ece6a
color3  #e0af68
color4  #7aa2f7
color5  #bb9af7
color6  #7dcfff
color7  #a9b1d6
color8  #414868
color9  #f7768e
color10 #9ece6a
color11 #e0af68
color12 #7aa2f7
color13 #bb9af7
color14 #7dcfff
color15 #c0caf5
cursor #c0caf5
cursor_text_color #1a1b26
selection_background #33467c
selection_foreground #c0caf5
font_family      JetBrainsMono Nerd Font
font_size        11.5
scrollback_lines  10000
copy_on_select        clipboard
window_padding_width 10
active_border_color  #7aa2f7
"""

    def test_parse_kitty_conf_reads_theme_and_terminal_prefs(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write(self.SAMPLE)
            path = fh.name
        try:
            theme = cligrid.parse_kitty_conf(path)
        finally:
            os.unlink(path)
        self.assertEqual(theme["foreground"], "#c0caf5")
        self.assertEqual(theme["background"], "#1a1b26")
        self.assertEqual(theme["palette"][4], "#7aa2f7")
        self.assertEqual(theme["palette"][15], "#c0caf5")
        self.assertEqual(theme["font_family"], "JetBrainsMono Nerd Font")
        self.assertEqual(theme["font_size"], 11)
        self.assertEqual(theme["scrollback"], 10000)
        self.assertTrue(theme["copy_on_select"])
        self.assertEqual(theme["padding"], 10)
        self.assertEqual(theme["accent"], "#7aa2f7")

    def test_parse_missing_file_returns_tokyo_night_defaults(self):
        theme = cligrid.parse_kitty_conf("/tmp/cligrid-missing-kitty.conf")
        self.assertEqual(theme["background"], "#1a1b26")
        self.assertEqual(len(theme["palette"]), 16)
        self.assertEqual(theme["accent"], "#7aa2f7")

    def test_css_uses_kitty_accent_not_a_hardcoded_gold(self):
        css = cligrid.build_css(cligrid.TOKYO_NIGHT)
        text = css.decode("utf-8")
        self.assertIn("#7aa2f7", text)
        self.assertIn("#1a1b26", text)
        self.assertNotIn("#c9a227", text)


class TmuxTargetTests(unittest.TestCase):
    def test_reads_session_from_new_session(self):
        self.assertEqual(cligrid.tmux_target("tmux new-session -A -s g3", "g1"), "g3")

    def test_returns_none_for_a_plain_shell(self):
        self.assertIsNone(cligrid.tmux_target("zsh"))


class SpawnHelperTests(unittest.TestCase):
    def test_env_list_strips_tmux_so_sessions_are_not_nested(self):
        old = os.environ.get("TMUX")
        os.environ["TMUX"] = "/tmp/tmux-1000/default,1,0"
        try:
            env = dict(item.split("=", 1) for item in cligrid.env_list(0))
        finally:
            if old is None:
                os.environ.pop("TMUX", None)
            else:
                os.environ["TMUX"] = old
        self.assertNotIn("TMUX", env)
        self.assertEqual(env["CLIGRID_SLOT"], "0")
        self.assertEqual(env["TERM"], "xterm-256color")

    def test_pane_argv_runs_tmux_directly(self):
        self.assertEqual(
            cligrid.pane_argv("tmux new-session -A -s g1"),
            ["tmux", "new-session", "-A", "-s", "g1"],
        )

    def test_pane_argv_keeps_a_shell_wrapper_for_compound_commands(self):
        self.assertEqual(
            cligrid.pane_argv("cd ~/src && exec zsh"),
            ["/bin/bash", "-lc", "cd ~/src && exec zsh"],
        )


class TmuxChromeTests(unittest.TestCase):
    def test_chrome_uses_literal_hex_so_tmux_does_not_print_bad_colour(self):
        options = dict(cligrid.tmux_chrome_options(cligrid.TOKYO_NIGHT))
        self.assertEqual(options["status"], "off")
        self.assertEqual(options["display-panes-colour"], "#292e42")
        self.assertEqual(options["display-panes-active-colour"], "#7aa2f7")
        for key, value in options.items():
            self.assertNotIn("#{", str(value), key)
            if "colour" in key or key.endswith("-style"):
                self.assertRegex(str(value), r"#[0-9a-fA-F]{6}")

    def test_griderator_chrome_follows_the_house_palette(self):
        theme = cligrid.theme_for("griderator", cligrid.TOKYO_NIGHT)
        options = dict(cligrid.tmux_chrome_options(theme))
        self.assertEqual(options["display-panes-active-colour"], theme["accent"])
        self.assertIn(theme["selection_bg"], options["message-style"])
        self.assertIn(theme["foreground"], options["message-style"])

    def test_new_session_gets_session_local_set_option_commands(self):
        argv = cligrid.with_tmux_chrome(
            ["tmux", "new-session", "-A", "-s", "g3", "htop"], cligrid.TOKYO_NIGHT)
        self.assertEqual(argv[:6], ["tmux", "new-session", "-A", "-s", "g3", "htop"])
        self.assertIn(";", argv)
        self.assertEqual(argv[argv.index("set-option") + 1], "status")
        self.assertIn("off", argv)
        self.assertNotIn("#{", " ".join(argv))

    def test_plain_shell_is_left_alone(self):
        self.assertEqual(cligrid.with_tmux_chrome(["zsh"]), ["zsh"])

    def test_apply_argv_uses_session_target_and_literal_colours(self):
        argv = cligrid.tmux_chrome_apply_argv("g4", cligrid.TOKYO_NIGHT)
        self.assertEqual(argv[0], "tmux")
        self.assertIn("-t", argv)
        self.assertIn("g4", argv)
        self.assertNotIn("#{", " ".join(argv))


class FillAllTests(unittest.TestCase):
    def test_plain_cli_stays_on_the_tmux_argv(self):
        cmd = cligrid.pane_cmd_for_cli("g3", "htop")
        self.assertEqual(cmd, "tmux new-session -A -s g3 htop")
        self.assertEqual(
            cligrid.pane_argv(cmd),
            ["tmux", "new-session", "-A", "-s", "g3", "htop"],
        )
        self.assertEqual(cligrid.tmux_target(cmd, "g1"), "g3")

    def test_compound_cli_runs_inside_the_session(self):
        cmd = cligrid.pane_cmd_for_cli("g1", "cd ~/src && nvim")
        self.assertEqual(cligrid.tmux_target(cmd), "g1")
        argv = cligrid.pane_argv(cmd)
        self.assertEqual(argv[:5], ["tmux", "new-session", "-A", "-s", "g1"])
        self.assertIn("bash", argv)
        self.assertIn("cd ~/src && nvim", argv)

    def test_empty_cli_is_a_plain_session(self):
        self.assertEqual(
            cligrid.pane_cmd_for_cli("g2", "  "),
            "tmux new-session -A -s g2",
        )


class PaneCountTests(unittest.TestCase):
    def test_default_is_six(self):
        self.assertEqual(cligrid.clamp_pane_count(None), 6)
        self.assertEqual(len(cligrid.normalize_panes(None, 6)), 6)

    def test_clamps_to_twenty(self):
        self.assertEqual(cligrid.clamp_pane_count(99), 20)
        self.assertEqual(cligrid.clamp_pane_count(0), 1)

    def test_extends_missing_panes_with_tmux_defaults(self):
        panes = cligrid.normalize_panes([{"name": "work", "cmd": "tmux new-session -A -s work"}], 8)
        self.assertEqual(len(panes), 8)
        self.assertEqual(panes[0]["name"], "work")
        self.assertEqual(panes[7]["name"], "g8")
        self.assertEqual(panes[7]["cmd"], "tmux new-session -A -s g8")

    def test_grid_rows_wrap_to_extra_rows(self):
        self.assertEqual(cligrid.grid_rows(3, 6), 2)
        self.assertEqual(cligrid.grid_rows(3, 20), 7)
        self.assertEqual(cligrid.grid_rows(1, 20), 20)

    def test_six_panes_in_grid_do_not_need_scroll(self):
        self.assertFalse(cligrid.needs_window_scroll(3, 2, 6))
        self.assertTrue(cligrid.needs_window_scroll(3, 2, 7))
        self.assertTrue(cligrid.needs_window_scroll(3, 2, 20))

    def test_drop_pane_config_keeps_neighbors(self):
        panes = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        leftover = cligrid.drop_pane_config(panes, 1)
        self.assertEqual([p["name"] for p in leftover], ["a", "c"])

    def test_cannot_drop_the_last_window(self):
        self.assertIsNone(cligrid.drop_pane_config([{"name": "only"}], 0))
        self.assertIsNone(cligrid.drop_pane_config([{"name": "a"}, {"name": "b"}], 9))

    def test_added_pane_skips_a_session_already_in_the_grid(self):
        panes = [{"name": "g8", "cmd": "tmux new-session -A -s g8 claude"}] + [
            cligrid.default_pane(i) for i in range(1, 7)]
        grown = cligrid.normalize_panes(panes, 8)
        self.assertEqual(grown[7], {"name": "g1", "cmd": "tmux new-session -A -s g1"})
        names = [pane["name"] for pane in grown]
        self.assertEqual(len(names), len(set(names)))

    def test_added_pane_avoids_sessions_named_only_in_a_command(self):
        grown = cligrid.normalize_panes([{"name": "work", "cmd": "tmux new-session -A -s g2"}], 2)
        self.assertEqual(grown[1]["name"], "g1")

    def test_default_name_keeps_its_position_when_free(self):
        self.assertEqual(cligrid.default_pane(4, {"g1", "g2"})["name"], "g5")


class GridLayoutTests(unittest.TestCase):
    def test_shape_follows_the_pane_count(self):
        self.assertEqual(cligrid.grid_shape(1), (1, 1))
        self.assertEqual(cligrid.grid_shape(2), (2, 1))
        self.assertEqual(cligrid.grid_shape(4), (2, 2))
        self.assertEqual(cligrid.grid_shape(5), (3, 2))
        self.assertEqual(cligrid.grid_shape(20), (3, 7))

    def test_every_row_fills_the_grid_width(self):
        for count in range(1, cligrid.MAX_PANES + 1):
            rows = {}
            for col, row, span in cligrid.grid_cells(count):
                rows.setdefault(row, []).append((col, span))
            for cells in rows.values():
                covered = sorted(c for col, span in cells for c in range(col, col + span))
                self.assertEqual(covered, list(range(cligrid.GRID_SUBCOLS)), "count %d" % count)

    def test_five_panes_stretch_the_second_row(self):
        self.assertEqual(
            cligrid.grid_cells(5),
            [(0, 0, 2), (2, 0, 2), (4, 0, 2), (0, 1, 3), (3, 1, 3)],
        )

    def test_focus_moves_by_geometry(self):
        self.assertEqual(cligrid.neighbor_position(5, 1, "down"), 4)
        self.assertEqual(cligrid.neighbor_position(5, 0, "down"), 3)
        self.assertEqual(cligrid.neighbor_position(5, 4, "up"), 2)
        self.assertEqual(cligrid.neighbor_position(5, 3, "right"), 4)
        self.assertEqual(cligrid.neighbor_position(5, 2, "right"), 2)
        self.assertEqual(cligrid.neighbor_position(1, 0, "left"), 0)


class RespawnBackoffTests(unittest.TestCase):
    def test_halts_after_repeated_quick_exits(self):
        self.assertEqual(
            cligrid.decide_child_exit_action(False, False, True, cligrid.MAX_QUICK_EXITS),
            "halt",
        )
        self.assertEqual(
            cligrid.decide_child_exit_action(False, False, True, cligrid.MAX_QUICK_EXITS - 1),
            "respawn",
        )

    def test_exit_text_reads_codes_and_signals(self):
        self.assertEqual(cligrid.exit_text(1 << 8), "with code 1")
        self.assertEqual(cligrid.exit_text(9), "on signal 9")


class ChromeColorTests(unittest.TestCase):
    def test_compact_path_keeps_the_last_two_parts(self):
        home = os.path.expanduser("~")
        self.assertEqual(cligrid.compact_path(home + "/Desktop/Folders/VibeCode/cligrid"),
                         "…/VibeCode/cligrid")
        self.assertEqual(cligrid.compact_path(home + "/.config"), "~/.config")
        self.assertEqual(cligrid.compact_path("/tmp"), "/tmp")

    def test_contrast_ratio_matches_wcag_extremes(self):
        self.assertAlmostEqual(cligrid.contrast_ratio("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(cligrid.contrast_ratio("#7aa2f7", "#7aa2f7"), 1.0)

    def test_chrome_text_is_readable_on_tokyo_night(self):
        c = cligrid.chrome_palette(cligrid.TOKYO_NIGHT)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["accent"], c["on_accent"]), 4.5)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["surface"], c["subtle"]), 4.5)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["red"], c["on_red"]), 4.5)

    def test_light_kitty_theme_gets_light_chrome_and_its_own_accent(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("background #fafafa\nforeground #383a42\ncolor4 #4078f2\ncolor1 #e45649\n")
            path = fh.name
        try:
            theme = cligrid.parse_kitty_conf(path)
        finally:
            os.unlink(path)
        self.assertEqual(theme["accent"], "#4078f2")
        c = cligrid.chrome_palette(theme)
        self.assertGreater(cligrid.luminance(c["surface"]), 0.5)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["accent"], c["on_accent"]), 4.5)
        css = cligrid.build_css(theme).decode()
        self.assertNotIn("#1a1b26", css)
        self.assertNotIn("#16161e", css)


class SignatureThemeTests(unittest.TestCase):
    """The grid ships its own palette and must not depend on kitty or a stock theme."""

    def theme(self):
        return cligrid.theme_for("griderator", cligrid.TOKYO_NIGHT)

    def test_griderator_is_the_default_theme(self):
        self.assertEqual(cligrid.DEFAULT_CONFIG["theme"], "griderator")
        self.assertEqual(cligrid_art.THEME_NAMES[0], "griderator")
        self.assertIsNotNone(cligrid_art.theme_preset("griderator"))

    def test_palette_is_sixteen_colours_and_shared_with_no_stock_theme(self):
        theme = self.theme()
        self.assertEqual(len(theme["palette"]), 16)
        self.assertEqual(theme["background"], "#15171b")
        mine = (theme["background"], theme["foreground"])
        for name in cligrid_art.THEME_NAMES[1:]:
            other = cligrid_art.THEME_PRESETS[name]
            self.assertNotEqual(mine, (other["background"], other["foreground"]))

    def test_every_pane_colour_reads_on_the_signature_background(self):
        theme = self.theme()
        for position in range(len(cligrid.PANE_COLOR_SLOTS)):
            colour = cligrid.pane_color(theme, position)
            self.assertGreaterEqual(cligrid.contrast_ratio(theme["background"], colour), 4.5)
            text = cligrid.text_on(colour, (theme["background"], theme["foreground"]))
            self.assertGreaterEqual(cligrid.contrast_ratio(colour, text), 4.5)

    def test_chrome_text_is_readable_on_the_signature_theme(self):
        c = cligrid.chrome_palette(self.theme())
        self.assertGreaterEqual(cligrid.contrast_ratio(c["accent"], c["on_accent"]), 4.5)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["surface"], c["subtle"]), 4.5)
        self.assertGreaterEqual(cligrid.contrast_ratio(c["red"], c["on_red"]), 4.5)

    def test_css_carries_the_signature_accent_not_tokyo_night(self):
        css = cligrid.build_css(self.theme()).decode()
        self.assertIn("#d8be86", css)
        self.assertIn("#15171b", css)
        stock = cligrid.build_css(cligrid.TOKYO_NIGHT).decode()
        self.assertNotIn("#d8be86", stock)
        self.assertIn("#7aa2f7", stock)


class ThemeVerbTests(unittest.TestCase):
    """An unknown name used to fall through to kitty and overwrite the setting."""

    def dispatch(self, args):
        return cligrid.CliGrid.dispatch_theme(object.__new__(cligrid.CliGrid), args)

    def test_unknown_name_lists_the_choices_and_changes_nothing(self):
        cligrid.set_active_theme("griderator")
        reply = self.dispatch(["set", "griderator"])
        self.assertIn("unknown theme set", reply)
        self.assertIn("griderator", reply)
        self.assertEqual(cligrid.active_theme_name(), "griderator")

    def test_list_marks_the_signature_theme_active(self):
        cligrid.set_active_theme("griderator")
        reply = self.dispatch(["list"])
        self.assertIn("griderator (active)", reply)
        self.assertIn("kitty", reply)


class ArtTests(unittest.TestCase):
    def test_logo_rows_share_one_width(self):
        self.assertEqual({len(row) for row in cligrid_art.LOGO}, {cligrid_art.LOGO_WIDTH})

    def test_banner_without_color_has_no_escapes(self):
        text = cligrid_art.banner(3, "g3", width=80, enabled=False)
        self.assertNotIn("\x1b[", text)
        self.assertIn(cligrid_art.LOGO[0], text)
        self.assertIn("pane 3", text)
        self.assertIn("session g3", text)

    def test_narrow_panes_get_the_one_line_wordmark(self):
        text = cligrid_art.banner(1, "g1", width=30, enabled=False)
        self.assertIn(cligrid_art.WORDMARK, text)
        self.assertNotIn(cligrid_art.LOGO[0], text)

    def test_gradient_hits_its_stops(self):
        stops = ("#000000", "#ffffff")
        self.assertEqual(cligrid_art.gradient_at(stops, 0), "#000000")
        self.assertEqual(cligrid_art.gradient_at(stops, 1), "#ffffff")
        self.assertEqual(cligrid_art.gradient_at(stops, 0.5), "#808080")

    def test_no_color_env_turns_color_off(self):
        class Terminal:
            def isatty(self):
                return True
        old = os.environ.pop("NO_COLOR", None)
        try:
            self.assertTrue(cligrid_art.color_enabled(Terminal()))
            os.environ["NO_COLOR"] = "1"
            self.assertFalse(cligrid_art.color_enabled(Terminal()))
        finally:
            os.environ.pop("NO_COLOR", None)
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_command_summary_looks_inside_tmux(self):
        self.assertEqual(cligrid_art.command_summary("tmux new-session -A -s g8 claude"), "claude")
        self.assertEqual(cligrid_art.command_summary("tmux new-session -A -s g2"), "shell")
        self.assertEqual(
            cligrid_art.command_summary(cligrid.pane_cmd_for_cli("g1", "cd ~/src && nvim")),
            "cd ~/src && nvim",
        )
        self.assertEqual(cligrid_art.command_summary("htop"), "htop")

    def test_status_summary_lists_each_pane(self):
        data = {
            "pane_count": 2, "font_size": 11,
            "headerbar_px": [1366, 45], "scroller_px": [1366, 603],
            "panes": [
                {"position": 1, "name": "g8", "cmd": "tmux new-session -A -s g8 claude",
                 "cols": 148, "rows": 27, "focused": True, "exited": False},
                {"position": 2, "name": "g2", "cmd": "htop",
                 "cols": 72, "rows": 16, "focused": False, "exited": True},
            ],
        }
        text = cligrid_art.format_status(data, enabled=False)
        self.assertIn("1366×648", text)
        self.assertIn("claude", text)
        self.assertIn("exited", text)
        self.assertNotIn("\x1b[", text)

    def test_help_lists_every_section(self):
        text = cligrid_art.help_text("3.2", enabled=False)
        for section in ("WINDOW", "PANES", "SESSIONS", "INFO"):
            self.assertIn(section, text)


class BannerSpawnTests(unittest.TestCase):
    def test_banner_runs_before_the_original_command(self):
        head, tail = cligrid_art.split_tmux_new_session(
            ["tmux", "new-session", "-A", "-s", "g3", "echo", "done"])
        argv = cligrid.with_banner(head, tail, ["echo", "BANNER"])
        self.assertEqual(argv[:5], ["tmux", "new-session", "-A", "-s", "g3"])
        result = subprocess.run(argv[5:], capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.stdout, "BANNER\ndone\n")

    def test_plain_session_gets_a_login_shell_after_the_banner(self):
        head, tail = cligrid_art.split_tmux_new_session(["tmux", "new-session", "-A", "-s", "g2"])
        argv = cligrid.with_banner(head, tail, ["echo", "BANNER"])
        self.assertIn('exec "${SHELL:-/bin/sh}" -l', argv[-1])

    def test_bundled_tmux_flags_are_left_alone(self):
        self.assertIsNone(cligrid_art.split_tmux_new_session(["tmux", "new-session", "-As", "g3"]))
        self.assertIsNone(cligrid_art.split_tmux_new_session(["htop"]))

    def test_pane_colors_follow_position(self):
        colors = [cligrid.pane_color(cligrid.TOKYO_NIGHT, i) for i in range(7)]
        self.assertEqual(colors[:6], ["#7aa2f7", "#bb9af7", "#7dcfff", "#9ece6a", "#e0af68", "#f7768e"])
        self.assertEqual(colors[6], colors[0])

    def test_css_has_a_tint_for_every_position(self):
        css = cligrid.build_css(cligrid.TOKYO_NIGHT).decode()
        for i in range(len(cligrid.PANE_COLOR_SLOTS)):
            self.assertIn(".pane.tint-%d" % i, css)


class AttentionTests(unittest.TestCase):
    def test_bell_in_the_focused_pane_of_a_watched_grid_does_nothing(self):
        self.assertEqual(cligrid.decide_bell(pane_focused=True, window_watched=True), (False, False))

    def test_bell_in_a_background_pane_pulses_it(self):
        self.assertEqual(cligrid.decide_bell(pane_focused=False, window_watched=True), (True, False))

    def test_bell_while_the_grid_is_behind_other_windows_notifies(self):
        self.assertEqual(cligrid.decide_bell(pane_focused=True, window_watched=False), (False, True))
        self.assertEqual(cligrid.decide_bell(pane_focused=False, window_watched=False), (True, True))

    def test_settings_switch_each_alert_off(self):
        self.assertEqual(
            cligrid.decide_bell(False, False, alerts_on=False, notify_on=False), (False, False))

    def test_notification_names_the_pane_and_its_command(self):
        home = os.path.expanduser("~")
        summary, body = cligrid.notification_text(
            3, "g3", "tmux new-session -A -s g3 claude", home + "/Desktop/Folders/VibeCode/cligrid")
        self.assertEqual(summary, "Pane 3 · g3")
        self.assertEqual(body, "claude rang its bell in …/VibeCode/cligrid")

    def test_tmux_clock_row_is_ignored(self):
        before = "~ ❯ make\nbuilding\n[g3] 0:bash  17:58\n"
        after = "~ ❯ make\nbuilding\n[g3] 0:bash  17:59\n"
        self.assertEqual(cligrid.without_status_line(before), cligrid.without_status_line(after))
        self.assertNotEqual(cligrid.without_status_line(before),
                            cligrid.without_status_line("~ ❯ make\ndone\n[g3] 0:bash  17:59\n"))

    def test_alert_styles_exist_for_every_position(self):
        css = cligrid.build_css(cligrid.TOKYO_NIGHT).decode()
        for i in range(len(cligrid.PANE_COLOR_SLOTS)):
            self.assertIn(".pane.tint-%d.alert.alert-on" % i, css)
            self.assertIn("button.tint-%d.activity" % i, css)


class QuietHoursTests(unittest.TestCase):
    def at(self, hour, minute=0):
        return datetime.datetime(2026, 9, 12, hour, minute)

    def test_no_window_never_suppresses(self):
        self.assertFalse(cligrid.in_quiet_hours(""))
        self.assertFalse(cligrid.in_quiet_hours(None))
        self.assertFalse(cligrid.in_quiet_hours("nonsense"))
        self.assertFalse(cligrid.in_quiet_hours("22:00"))

    def test_simple_window(self):
        self.assertTrue(cligrid.in_quiet_hours("09:00-17:00", self.at(12)))
        self.assertFalse(cligrid.in_quiet_hours("09:00-17:00", self.at(18)))
        self.assertFalse(cligrid.in_quiet_hours("09:00-17:00", self.at(8, 59)))

    def test_window_across_midnight(self):
        self.assertTrue(cligrid.in_quiet_hours("22:00-07:00", self.at(23, 30)))
        self.assertTrue(cligrid.in_quiet_hours("22:00-07:00", self.at(2)))
        self.assertFalse(cligrid.in_quiet_hours("22:00-07:00", self.at(12)))

    def test_malformed_times_are_ignored(self):
        self.assertFalse(cligrid.in_quiet_hours("25:00-07:00", self.at(3)))
        self.assertFalse(cligrid.in_quiet_hours("aa:bb-cc:dd", self.at(3)))

    def test_equal_bounds_mean_no_window(self):
        self.assertFalse(cligrid.in_quiet_hours("08:00-08:00", self.at(8)))


class NotifyRuleTests(unittest.TestCase):
    def test_patterns_from_a_string_and_a_list(self):
        self.assertEqual(len(cligrid.notification_patterns({"notify_on": "done"})), 1)
        self.assertEqual(len(cligrid.notification_patterns({"notify_on": ["done", "error"]})), 2)
        self.assertEqual(cligrid.notification_patterns({}), [])
        self.assertEqual(cligrid.notification_patterns(None), [])

    def test_a_broken_pattern_is_skipped_not_fatal(self):
        patterns = cligrid.notification_patterns({"notify_on": ["[", "ok"]})
        self.assertEqual(len(patterns), 1)
        self.assertTrue(patterns[0].search("this is OK"))

    def test_matching_is_case_insensitive(self):
        pattern = cligrid.notification_patterns({"notify_on": "build failed"})[0]
        self.assertTrue(pattern.search("BUILD FAILED after 12s"))


class ThemeChoiceTests(unittest.TestCase):
    def test_kitty_keeps_the_terminal_theme(self):
        base = dict(cligrid.TOKYO_NIGHT)
        self.assertIs(cligrid.theme_for("kitty", base), base)
        self.assertIs(cligrid.theme_for("", base), base)
        self.assertIs(cligrid.theme_for("nonsense", base), base)

    def test_a_preset_overrides_colours_but_keeps_terminal_prefs(self):
        base = dict(cligrid.TOKYO_NIGHT)
        theme = cligrid.theme_for("gruvbox-dark", base)
        self.assertEqual(theme["background"], "#282828")
        self.assertEqual(theme["font_size"], base["font_size"])
        self.assertEqual(theme["scrollback"], base["scrollback"])

    def test_the_default_theme_is_the_house_palette(self):
        self.assertEqual(cligrid.DEFAULT_CONFIG["theme"], "griderator")
        self.assertIsNotNone(cligrid_art.theme_preset("griderator"))

    def test_an_unknown_name_keeps_the_current_theme(self):
        original = cligrid.active_theme_name()
        self.addCleanup(cligrid.ACTIVE_THEME.__setitem__, "name", original)
        self.assertEqual(cligrid.set_active_theme("dracula"), "dracula")
        self.assertEqual(cligrid.active_theme_name(), "dracula")
        self.assertEqual(cligrid.set_active_theme("not-a-theme"), "dracula")

    def test_every_preset_has_a_full_sixteen_colour_palette(self):
        for name in cligrid_art.theme_names():
            preset = cligrid_art.theme_preset(name)
            if preset is None:
                continue
            self.assertEqual(len(preset["palette"]), 16, name)
            self.assertTrue(preset["background"].startswith("#"), name)
            self.assertTrue(preset["foreground"].startswith("#"), name)


class ConfigRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cligrid-config-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self._config_path = cligrid.CONFIG_PATH
        self._store = cligrid._STORE["cfg"]
        cligrid.CONFIG_PATH = os.path.join(self.dir, "config.json")
        cligrid._STORE["cfg"] = None

    def tearDown(self):
        cligrid.CONFIG_PATH = self._config_path
        cligrid._STORE["cfg"] = self._store

    def test_defaults_load_without_a_file(self):
        cfg = cligrid.load_config()
        self.assertEqual(cfg["pane_count"], cligrid.DEFAULT_PANE_COUNT)
        self.assertEqual(cfg["layout"], "auto")
        self.assertEqual(len(cfg["panes"]), cligrid.DEFAULT_PANE_COUNT)

    def test_schema_one_migrates_and_keeps_the_panes(self):
        with open(cligrid.CONFIG_PATH, "w") as handle:
            json.dump({"pane_count": 3, "font_size": 14,
                       "panes": [{"name": "work", "cmd": "htop"}]}, handle)
        cfg = cligrid.load_config()
        self.assertEqual(cfg["pane_count"], 3)
        self.assertEqual(cfg["font_size"], 14)
        self.assertEqual(cfg["panes"][0]["name"], "work")
        self.assertEqual(cfg["panes"][0]["cmd"], "htop")

    def test_save_writes_schema_two_and_round_trips(self):
        cfg = cligrid.load_config()
        cfg["layout"] = "2x2"
        cfg["stack"] = [[0, 1]]
        cfg["theme"] = "nord"
        cligrid.save_config(cfg)
        with open(cligrid.CONFIG_PATH) as handle:
            store = json.load(handle)
        self.assertEqual(store["version"], 2)
        self.assertEqual(store["active"], "default")
        again = cligrid.load_config()
        self.assertEqual(again["layout"], "2x2")
        self.assertEqual(again["stack"], [[0, 1]])
        self.assertEqual(again["theme"], "nord")

    def test_damaged_config_is_repaired_not_fatal(self):
        with open(cligrid.CONFIG_PATH, "w") as handle:
            handle.write("{ not json")
        cfg = cligrid.load_config()
        self.assertEqual(cfg["pane_count"], cligrid.DEFAULT_PANE_COUNT)

    def test_a_config_poisoned_by_a_leaked_panes_flag_heals_on_load(self):
        # `cligrid all --panes 1,3 <command>` used to save the flag into the
        # fill command and every pane command, so the grid came up all dead.
        with open(cligrid.CONFIG_PATH, "w") as handle:
            json.dump({
                "fill_cmd": "--panes 1 'bash -l'",
                "pane_count": 2,
                "panes": [
                    {"name": "g1", "cmd": "tmux new-session -A -s g1 --panes 1 'bash -l'"},
                    {"name": "g2", "cmd": "tmux new-session -A -s g2"},
                ],
            }, handle)
        cfg = cligrid.load_config()
        self.assertEqual(cfg["fill_cmd"], "bash -l")
        for pane in cfg["panes"]:
            self.assertNotIn("--panes", pane["cmd"])
        self.assertEqual(
            cligrid.pane_argv(cfg["panes"][0]["cmd"]),
            ["tmux", "new-session", "-A", "-s", "g1", "bash", "-l"],
        )
        self.assertEqual(
            cligrid.pane_cmd_for_cli("g1", cfg["fill_cmd"]),
            "tmux new-session -A -s g1 bash -l",
        )


class ClientArgumentTests(unittest.TestCase):
    def test_fill_arguments_keep_the_command_and_strip_the_pane_spec(self):
        command, spec = cligrid.split_fill_args(["--panes", "1,3", "htop", "-d", "5"])
        self.assertEqual(command, "htop -d 5")
        self.assertEqual(spec, "1,3")
        self.assertEqual(cligrid.split_fill_args(["htop"]), ("htop", ""))

    def test_fill_arguments_from_the_control_wire_still_lose_the_flag(self):
        # `all` reaches the window as one quoted payload, which is how the flag
        # used to end up inside every pane's command and kill the whole grid.
        payload = "all --panes 1,3 htop"
        args = cligrid_control.parse(payload)["args"]
        command, spec = cligrid.split_fill_args(args)
        self.assertEqual(spec, "1,3")
        self.assertNotIn("--panes", command)
        self.assertEqual(command, "htop")

    def test_a_quoted_payload_survives_the_wire(self):
        payload = "all --panes 1 'bash -l'"
        args = cligrid_control.parse(payload)["args"]
        command, spec = cligrid.split_fill_args(args)
        self.assertEqual(spec, "1")
        self.assertEqual(command, "bash -l")
        self.assertEqual(
            cligrid.pane_cmd_for_cli("g1", command),
            "tmux new-session -A -s g1 bash -l",
        )

    def test_an_equals_form_flag_is_stripped_too(self):
        command, spec = cligrid.split_fill_args(["--panes=2,4", "htop"])
        self.assertEqual(spec, "2,4")
        self.assertEqual(command, "htop")

    def test_a_stored_quoted_command_is_still_read_by_a_shell(self):
        cmd = cligrid.pane_cmd_for_cli("g1", "'bash -l'")
        argv = cligrid.pane_argv(cmd)
        self.assertEqual(argv[:5], ["tmux", "new-session", "-A", "-s", "g1"])
        self.assertIn("bash", argv)

    def test_a_stored_command_line_loses_a_leaked_flag(self):
        self.assertEqual(cligrid.strip_panes_flag("--panes 1 htop"), "htop")
        self.assertEqual(
            cligrid.strip_panes_flag("tmux new-session -A -s g1 --panes 1 bash"),
            "tmux new-session -A -s g1 bash",
        )

    def test_an_untouched_command_line_is_returned_verbatim(self):
        cmd = "tmux new-session -A -s g1 bash -lc 'cd ~/src && nvim'"
        self.assertEqual(cligrid.strip_panes_flag(cmd), cmd)

    def test_a_quoted_command_runs_inside_a_shell(self):
        cmd = cligrid.pane_cmd_for_cli("g1", "'bash -l'")
        argv = cligrid.pane_argv(cmd)
        self.assertEqual(argv[:5], ["tmux", "new-session", "-A", "-s", "g1"])
        self.assertIn("bash", argv)

    def test_wait_gets_a_timeout_that_outlives_its_own(self):
        self.assertEqual(cligrid.request_timeout("status"), 5)
        self.assertEqual(cligrid.request_timeout("wait 3 --until done --timeout 60"), 66)
        self.assertEqual(cligrid.request_timeout("wait 3 --until done"), 36)

    def test_event_lines_render_without_color(self):
        line = cligrid.format_event_line(
            json.dumps({"kind": "bell", "seq": 4, "time": 1700000000.0, "pane": "g3"}),
            out_color=False)
        self.assertIn("bell", line)
        self.assertIn("pane=g3", line)
        self.assertNotIn("\x1b[", line)

    def test_a_broken_event_line_passes_through(self):
        self.assertEqual(cligrid.format_event_line("not json", out_color=False), "not json")


class KeyHintTests(unittest.TestCase):
    def test_letters_and_symbols_read_as_chords(self):
        self.assertEqual(cligrid.key_hint("Z"), "Ctrl+Shift+Z")
        self.assertEqual(cligrid.key_hint("minus"), "Ctrl+Shift+-")
        self.assertEqual(cligrid.key_hint("Page_Up"), "Ctrl+Shift+Page_Up")

    def test_default_keymap_points_at_real_actions(self):
        from cligrid import CliGrid
        names = {name for name, _label, _hint, _cb in CliGrid.action_table(CliGrid.__new__(CliGrid))}
        for key, action in cligrid.DEFAULT_KEYMAP.items():
            self.assertIn(action, names | {"focus.%d" % n for n in range(1, 11)},
                          "keymap entry %s -> %s" % (key, action))

    def test_build_keymap_merges_overrides_and_unbinds(self):
        holder = type("H", (), {"config": {"keymap": {"Z": "quit", "Q": ""}}})()
        merged = cligrid.CliGrid.build_keymap(holder)
        self.assertEqual(merged["Z"], "quit")
        self.assertNotIn("Q", merged)
        self.assertEqual(merged["P"], "palette")

    def test_save_edited_keymap_rejects_a_prefix_collision(self):
        class Field:
            def __init__(self, text):
                self._text = text

            def get_text(self):
                return self._text

        holder = type("H", (), {"config": {"prefix": "space", "keymap": {}}})()
        holder.build_keymap = lambda: cligrid.DEFAULT_KEYMAP
        with unittest.mock.patch.object(cligrid, "save_config") as save:
            message = cligrid.CliGrid._save_edited_keymap(
                holder, {"zoom": Field("space")}, "space")
        self.assertIn("collides", message)
        save.assert_not_called()

    def test_save_edited_keymap_writes_a_diff(self):
        class Field:
            def __init__(self, text):
                self._text = text

            def get_text(self):
                return self._text

        holder = type("H", (), {"config": {"prefix": "space", "keymap": {}}})()
        holder.build_keymap = lambda: cligrid.keymap.merge(
            cligrid.DEFAULT_KEYMAP, holder.config["keymap"])
        fields = {action: Field(key) for key, action in cligrid.DEFAULT_KEYMAP.items()}
        fields["zoom"] = Field("F1")
        with unittest.mock.patch.object(cligrid, "save_config"):
            message = cligrid.CliGrid._save_edited_keymap(holder, fields, "space")
        self.assertEqual(message, "")
        self.assertEqual(holder.config["keymap"]["F1"], "zoom")
        self.assertEqual(holder.config["keymap"]["Z"], "")


class PaletteRenderTests(unittest.TestCase):
    """The renderer escapes labels and the classifier reads a refused verb.
    Both are pure logic, so they are tested without a window."""

    def test_markup_escapes_a_pane_name(self):
        text = cligrid.CliGrid.palette_markup(None, "Pane 1: <b>bold</b> & <", [], "#d8be86")
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;b&gt;", text)
        self.assertIn("&amp;", text)
        self.assertNotIn("<", text.replace("&lt;", "").replace("&amp;", ""))

    def test_markup_marks_the_matched_letters(self):
        self.assertEqual(
            cligrid.CliGrid.palette_markup(None, "Theme: Nord", [(0, 5)], "#d8be86"),
            '<span foreground="#d8be86" weight="bold">Theme</span>: Nord')

    def test_markup_without_a_match_is_plain_text(self):
        self.assertEqual(cligrid.CliGrid.palette_markup(None, "Zoom", [], "#fff"), "Zoom")

    def test_a_refused_reply_becomes_feedback(self):
        class Stub:
            def __init__(self):
                self.toasted = []

            def toast(self, text, **kwargs):
                self.toasted.append(text)

        stub = Stub()
        handler = cligrid.CliGrid.toast_reply
        self.assertTrue(handler(stub, "zoom expects a pane number 1-9 or off\n"))
        self.assertTrue(handler(stub, "cannot remove the last window\n"))
        self.assertTrue(handler(stub, "unknown command: bogus\n"))
        self.assertEqual(len(stub.toasted), 3)

    def test_a_working_reply_stays_quiet(self):
        class Stub:
            def __init__(self):
                self.toasted = []

            def toast(self, text, **kwargs):
                self.toasted.append(text)

        stub = Stub()
        handler = cligrid.CliGrid.toast_reply
        for reply in ("ok\n", "9\n", '{"layout": "auto"}\n', "g1\ng2\ng3\n", ""):
            self.assertFalse(handler(stub, reply), reply)
        self.assertEqual(stub.toasted, [])




class WorkspaceSaveControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (("CONFIG_DIR", self.tmp.name),
                              ("CONFIG_PATH", os.path.join(self.tmp.name, "config.json")),
                              ("_STORE", {"cfg": None})):
            patcher = patch.object(cligrid, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = object.__new__(cligrid.CliGrid)
        self.app.config = cligrid.load_config()
        self.app.toast = Mock()
        self.app.refresh_workspace_chip = Mock()
        self.app.save_state = Mock()

    def reload_store(self):
        cligrid._STORE["cfg"] = None
        return cligrid.read_store()

    def test_save_as_survives_reload_and_keeps_original(self):
        original = self.app.workspace_name()
        self.app.config["layout"] = "columns"
        self.assertTrue(self.app.save_workspace("Website project"))
        store = self.reload_store()
        self.assertIn(original, cligrid.workspace.workspace_names(store))
        active = cligrid.workspace.active_workspace(store)
        self.assertEqual(active["name"], "Website project")
        self.assertEqual(active["panes"], self.app.config["panes"])

    def test_rename_survives_reload_without_duplicate(self):
        original = self.app.workspace_name()
        self.assertTrue(self.app.save_workspace("Work", rename=True))
        store = self.reload_store()
        self.assertNotIn(original, cligrid.workspace.workspace_names(store))
        self.assertEqual(cligrid.workspace.active_workspace(store)["name"], "Work")
        self.assertEqual(self.app.config["workspace"], "Work")

    def test_duplicate_name_and_blank_are_rejected(self):
        self.assertTrue(self.app.save_workspace("Work"))
        self.assertTrue(self.app.save_workspace("Personal"))
        self.assertFalse(self.app.save_workspace("Work", rename=True))
        self.assertFalse(self.app.save_workspace("   "))
        self.assertEqual(self.app.workspace_name(), "Personal")

    def test_font_choice_is_applied_and_persisted(self):
        self.app.apply_font_all = Mock()
        self.app.autosize_font = Mock()
        self.app.update_status = Mock()
        self.app.font_size = 12
        self.app.set_terminal_font("Monospace")
        store = self.reload_store()
        self.assertEqual(store["font"], "Monospace")
        self.app.apply_font_all.assert_called_once_with(12)
        self.app.autosize_font.assert_called_once()
        self.assertEqual(self.app._metrics_cache, {})
        self.assertEqual(self.app._font_caps, {})

    def test_automatic_size_ignores_legacy_manual_setting(self):
        self.app.config["auto_font"] = False
        self.app.config["font_size"] = 48
        self.app.font_size = 48
        self.app.best_font_size = Mock(return_value=13)
        self.app.apply_font_all = Mock()
        self.app.autosize_font()
        self.app.apply_font_all.assert_called_once_with(13)

    def test_auto_size_responds_to_available_space_and_zoom(self):
        app = self.app
        app.scroller = Mock()
        app.scroller.get_allocation.return_value = Mock(width=800, height=600)
        pane = Mock()
        pane.header.get_allocated_height.return_value = 44
        app.order = [pane] * 6
        app.layout_shape = "auto"
        app.zoom = False
        app._font_caps = {}
        app.char_metrics_for = lambda size: (size * 0.6, size * 1.2)
        small = app.best_font_size()
        app.scroller.get_allocation.return_value = Mock(width=1800, height=1200)
        large = app.best_font_size()
        self.assertGreater(large, small)
        app.zoom = True
        self.assertGreaterEqual(app.best_font_size(), large)

    def test_pane_selector_scroll_is_bounded(self):
        adjustment = Mock()
        adjustment.get_lower.return_value = 0
        adjustment.get_upper.return_value = 800
        adjustment.get_page_size.return_value = 200
        adjustment.get_value.return_value = 550
        self.app.pill_scroll = Mock()
        self.app.pill_scroll.get_hadjustment.return_value = adjustment
        self.app.scroll_selector(120)
        adjustment.set_value.assert_called_with(600)
        self.app.scroll_selector(-1000)
        adjustment.set_value.assert_called_with(0)

    def test_pane_selector_maps_vertical_wheel_to_horizontal_scroll(self):
        self.app.scroll_selector = Mock()
        event = Mock(direction=cligrid.Gdk.ScrollDirection.DOWN)
        self.assertTrue(self.app.on_selector_scroll(None, event))
        self.app.scroll_selector.assert_called_once_with(40)

    def test_save_reports_disk_failure(self):
        with patch.object(cligrid, "write_store", side_effect=OSError("disk full")):
            self.assertFalse(self.app.save_workspace())
        self.assertEqual(self.app.toast.call_args.kwargs["kind"], "error")


class LifecycleTests(unittest.TestCase):
    def test_state_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "state.json")
            cligrid.write_json_atomic(path, {"a": 1})
            with open(path) as handle:
                self.assertEqual(json.load(handle), {"a": 1})
            self.assertFalse(os.path.exists(path + ".tmp"))
            with patch.object(cligrid.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    cligrid.write_json_atomic(path, {"a": 2})
            with open(path) as handle:
                self.assertEqual(json.load(handle), {"a": 1}, "a failed write must keep the old file")

    def test_log_is_trimmed_to_a_tail_on_a_line_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cligrid.log")
            with open(path, "w") as handle:
                for i in range(2000):
                    handle.write("line %04d and some padding text\n" % i)
            self.assertTrue(cligrid.trim_log(path, keep=4096))
            with open(path) as handle:
                lines = handle.read().splitlines()
            self.assertEqual(lines[0], "[cligrid: earlier log trimmed]")
            self.assertTrue(lines[1].startswith("line "), lines[1])
            self.assertEqual(lines[-1], "line 1999 and some padding text")
            self.assertLessEqual(os.path.getsize(path), 4096 + 64)
            self.assertFalse(cligrid.trim_log(path, keep=4096), "a small log is left alone")
            self.assertFalse(cligrid.trim_log(os.path.join(tmp, "missing.log")))

    def test_signal_handlers_use_glib_sources(self):
        app = Mock()
        with patch.object(cligrid.GLib, "unix_signal_add", return_value=1) as add, \
                patch.object(cligrid.signal, "signal") as legacy:
            cligrid.install_signal_handlers(app)
        self.assertEqual(sorted(call.args[1] for call in add.call_args_list),
                         sorted([cligrid.signal.SIGINT, cligrid.signal.SIGTERM]))
        legacy.assert_not_called()
        self.assertFalse(cligrid._on_signal(app))
        app.quit.assert_called_once()


class DumpTests(unittest.TestCase):
    """`dump` reaches scrollback through tmux; VTE only sees the screen."""

    def make_pane(self, cmd="tmux new-session -A -s g4", name="g4"):
        pane = cligrid.Pane.__new__(cligrid.Pane)
        pane.cmd = cmd
        pane.name = name
        pane.visible_text = Mock(return_value="screen 1\nscreen 2\n")
        pane.screen_text = Mock(return_value="screen 1\nscreen 2")
        return pane

    def test_capture_argv_reaches_back_into_history(self):
        self.assertEqual(
            cligrid.tmux_capture_argv("Build logs", 500),
            ["tmux", "capture-pane", "-p", "-J", "-t", "=Build logs", "-S", "-500"])

    def test_dump_prefers_tmux_history(self):
        pane = self.make_pane()
        history = "".join("line %d\n" % i for i in range(300)) + "\n\n"
        with patch.object(cligrid, "tmux_capture", return_value=history) as capture:
            text = pane.dump_text(200)
        capture.assert_called_once_with("g4", 200)
        rows = text.splitlines()
        self.assertEqual(len(rows), 200)
        self.assertEqual(rows[0], "line 100")
        self.assertEqual(rows[-1], "line 299")

    def test_dump_falls_back_to_the_screen_without_a_session(self):
        pane = self.make_pane(cmd="htop", name="monitor")
        with patch.object(cligrid, "tmux_capture", return_value=None) as capture:
            self.assertEqual(pane.dump_text(40), "screen 1\nscreen 2")
        capture.assert_called_once_with(None, 40)

    def test_dump_line_count_is_capped(self):
        pane = self.make_pane()
        with patch.object(cligrid, "tmux_capture", return_value="a\n") as capture:
            pane.dump_text(10 ** 9)
        self.assertEqual(capture.call_args.args[1], cligrid.MAX_DUMP_LINES)

    def test_capture_returns_none_when_tmux_fails(self):
        with patch.object(cligrid.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1, "", "no session")):
            self.assertIsNone(cligrid.tmux_capture("gone", 10))
        self.assertIsNone(cligrid.tmux_capture(None, 10))


class HighContrastThemeTests(unittest.TestCase):
    def test_preset_exists_and_reads_at_aaa_on_black(self):
        theme = cligrid.theme_for("high-contrast", cligrid.TOKYO_NIGHT)
        self.assertEqual(theme["background"], "#000000")
        self.assertGreaterEqual(cligrid.contrast_ratio(theme["background"], theme["foreground"]), 7)
        self.assertGreaterEqual(cligrid.contrast_ratio(theme["background"], theme["accent"]), 7)
        for position in range(len(cligrid.PANE_COLOR_SLOTS)):
            colour = cligrid.pane_color(theme, position)
            self.assertGreaterEqual(cligrid.contrast_ratio(theme["background"], colour), 4.5, colour)


class ClipboardHelperTests(unittest.TestCase):
    def test_terminal_selection_is_empty_without_a_selection(self):
        term = Mock()
        term.get_has_selection.return_value = False
        self.assertEqual(cligrid.terminal_selection(term), "")

    def test_terminal_selection_reads_vte_text(self):
        term = Mock()
        term.get_has_selection.return_value = True
        term.get_text_selected.return_value = "hello"
        self.assertEqual(cligrid.terminal_selection(term), "hello")

    def test_write_clipboard_sets_both_selections(self):
        clip, primary = Mock(), Mock()
        self.assertTrue(cligrid.write_clipboard(
            "hi", clipboard=clip, primary=primary, runner=lambda *a, **k: Mock(returncode=1)))
        clip.set_text.assert_called_with("hi", -1)
        primary.set_text.assert_called_with("hi", -1)

    def test_write_clipboard_falls_back_to_wl_copy(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs.get("input")))
            return Mock(returncode=0)

        self.assertTrue(cligrid.write_clipboard("hi", runner=runner))
        self.assertEqual(calls[0][0][:1], ["wl-copy"])
        self.assertEqual(calls[0][1], b"hi")

    def test_clipboard_text_prefers_gtk_then_wl_paste(self):
        clip = Mock()
        clip.wait_for_text.return_value = "from-gtk"
        self.assertEqual(cligrid.clipboard_text(clipboard=clip, runner=lambda *a, **k: None),
                         "from-gtk")
        clip.wait_for_text.return_value = None

        def runner(argv, **kwargs):
            self.assertEqual(argv[:1], ["wl-paste"])
            return Mock(returncode=0, stdout=b"from-wl")

        self.assertEqual(cligrid.clipboard_text(clipboard=clip, runner=runner), "from-wl")

    def test_paste_into_terminal_uses_paste_text(self):
        term = Mock()
        self.assertTrue(cligrid.paste_into_terminal(term, "abc"))
        term.paste_text.assert_called_with("abc")

    def test_paste_into_terminal_falls_back_to_feed_child(self):
        term = Mock()
        term.paste_text.side_effect = TypeError("no paste_text")
        self.assertTrue(cligrid.paste_into_terminal(term, "abc"))
        term.feed_child.assert_called()

    def test_copy_text_does_not_claim_primary(self):
        # VTE owns PRIMARY while text is highlighted. Claiming it ourselves
        # clears the highlight and drops the user back on the prompt.
        pane = cligrid.Pane.__new__(cligrid.Pane)
        pane.term = Mock()
        pane.term.get_has_selection.return_value = True
        pane.term.get_text_selected.return_value = "hello"
        pane._selection = ""
        clip, primary = Mock(), Mock()
        with patch.object(cligrid, "gtk_clipboards", return_value=(clip, primary)), \
                patch.object(cligrid, "write_clipboard", return_value=True) as write:
            self.assertTrue(pane.copy_text())
        self.assertEqual(write.call_args[0][0], "hello")
        self.assertIs(write.call_args.kwargs.get("clipboard"), clip)
        self.assertIsNone(write.call_args.kwargs.get("primary"))

    def test_copy_on_select_does_not_claim_primary(self):
        pane = cligrid.Pane.__new__(cligrid.Pane)
        pane._selection = ""
        term = Mock()
        term.get_has_selection.return_value = True
        term.get_text_selected.return_value = "hello"
        clip, primary = Mock(), Mock()
        with patch.object(cligrid, "THEME", {"copy_on_select": True}), \
                patch.object(cligrid, "gtk_clipboards", return_value=(clip, primary)), \
                patch.object(cligrid, "write_clipboard", return_value=True) as write:
            pane.on_selection(term)
        self.assertEqual(pane._selection, "hello")
        self.assertIsNone(write.call_args.kwargs.get("primary"))
        term.copy_clipboard_format.assert_not_called()

    def test_copy_text_uses_cached_selection_when_vte_clears_it(self):
        pane = cligrid.Pane.__new__(cligrid.Pane)
        pane.term = Mock()
        pane.term.get_has_selection.return_value = False
        pane._selection = "kept"
        with patch.object(cligrid, "write_clipboard", return_value=True) as write:
            self.assertTrue(pane.copy_text())
        self.assertEqual(write.call_args[0][0], "kept")

    def test_paste_text_feeds_clipboard_contents(self):
        pane = cligrid.Pane.__new__(cligrid.Pane)
        pane.term = Mock()
        with patch.object(cligrid, "clipboard_text", return_value="pasted"), \
                patch.object(cligrid, "paste_into_terminal", return_value=True) as paste:
            self.assertTrue(pane.paste_text())
        paste.assert_called_with(pane.term, "pasted")


class RemoveWindowWaiterTests(unittest.TestCase):
    def test_remove_window_answers_waiters_immediately(self):
        app = cligrid.CliGrid.__new__(cligrid.CliGrid)
        keep, gone = Mock(), Mock()
        app.panes = [keep, gone]
        app.order = [keep, gone]
        app.active = keep
        app.zoom = False
        app.config = {}
        app.detach_pane = Mock()
        app.after_count_change = Mock()
        app.poll_waiters = Mock()
        leftover = [{"name": "g1", "cmd": "tmux new-session -A -s g1"}]
        with patch.object(cligrid, "drop_pane_config", return_value=leftover), \
                patch.object(cligrid, "save_config"):
            self.assertTrue(app.remove_window(gone))
        app.poll_waiters.assert_called_once()
        app.detach_pane.assert_called_once_with(gone)


if __name__ == "__main__":
    unittest.main()
