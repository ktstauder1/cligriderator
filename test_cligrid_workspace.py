"""Workspace contract tests, runnable without GTK or VTE."""

import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

import cligrid_workspace as ws


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_schema_one_preserves_contents(self):
        raw = {
            "version": 1, "pane_count": 2,
            "panes": [{"name": "dev", "cmd": "vim"},
                      {"name": "shell", "cmd": "bash"}],
            "cwd": "/tmp/project", "font": "custom", "font_size": 14,
            "extra": {"keep": [1, 2]},
        }
        original = copy.deepcopy(raw)
        cfg = ws.migrate(raw)
        active = ws.active_workspace(cfg)
        self.assertEqual(cfg["version"], 2)
        for key in ("pane_count", "panes", "cwd"):
            self.assertEqual(active[key], raw[key])
        for key in ("font", "font_size", "extra"):
            self.assertEqual(cfg[key], raw[key])
        self.assertEqual(raw, original)

    def test_empty_defaults(self):
        cfg = ws.migrate({})
        self.assertEqual(ws.workspace_names(cfg), ["default"])
        active = ws.active_workspace(cfg)
        self.assertEqual(active["pane_count"], 6)
        self.assertEqual(active["panes"], [
            {"name": f"g{i}", "cmd": f"tmux new-session -A -s g{i}"}
            for i in range(1, 7)
        ])

    def test_migration_idempotent(self):
        first = ws.migrate({"pane_count": 2})
        with patch.dict(os.environ, {"CLIGRID_WORKSPACE": "changed"}):
            self.assertEqual(ws.migrate(first), first)

    def test_environment_names_migrated_workspace(self):
        with patch.dict(os.environ, {"CLIGRID_WORKSPACE": "Trade Desk"}):
            cfg = ws.migrate({})
        self.assertEqual(cfg["active"], "Trade Desk")
        self.assertEqual(ws.workspace_names(cfg), ["Trade Desk"])

    def test_add_collision_refused(self):
        cfg = ws.add_workspace(ws.migrate({}), "Trade Desk")
        self.assertEqual(ws.add_workspace(cfg, "trade-desk"), cfg)

    def test_last_workspace_not_removed(self):
        cfg = ws.migrate({})
        self.assertEqual(ws.remove_workspace(cfg, "default"), cfg)

    def test_padding_two(self):
        active = ws.active_workspace(ws.migrate({"pane_count": 2, "panes": []}))
        self.assertEqual(len(active["panes"]), 2)

    def test_count_twenty_one_clamped(self):
        active = ws.active_workspace(ws.migrate({"pane_count": 21}))
        self.assertEqual(active["pane_count"], 20)
        self.assertEqual(len(active["panes"]), 20)

    def test_count_lower_bound_and_trim(self):
        active = ws.active_workspace(ws.migrate({
            "pane_count": 0, "panes": [{"name": "keep", "cmd": "bash"}] * 3,
        }))
        self.assertEqual(active["pane_count"], 1)
        self.assertEqual(active["panes"], [{"name": "keep", "cmd": "bash"}])

    def test_damaged_fields_repaired(self):
        active = ws.active_workspace(ws.validate({
            "panes": "broken", "pane_count": None, "layout": "unknown",
        }))
        self.assertEqual(active["pane_count"], 6)
        self.assertEqual(len(active["panes"]), 6)
        self.assertEqual(active["layout"], "auto")

    def test_switch_preserves_exact_global_keys(self):
        expected = (
            "fit", "font", "font_size", "min_font_size", "auto_font", "min_cols",
            "min_rows", "scrollback", "cursor_blink", "banner", "bell_alerts",
            "activity_marks", "notify_desktop", "notify_rules", "quiet_hours",
            "keymap", "theme", "restore_on_start", "log_level", "prefix", "fill_cmd",
            "guard",
        )
        self.assertEqual(ws.GLOBAL_KEYS, expected)
        globals_ = {key: {"sentinel": [key]} for key in expected}
        cfg = ws.add_workspace(ws.migrate(globals_), "other", panes=[{"name": "x"}])
        switched = ws.set_active(cfg, "other")
        self.assertEqual(switched["active"], "other")
        self.assertEqual({key: switched[key] for key in expected}, globals_)
        self.assertEqual(cfg["active"], "default")

    def test_slug_spaces_punctuation_unicode(self):
        self.assertEqual(ws.slug("  Trade Desk!  "), "trade-desk")
        self.assertEqual(ws.slug("A__B / C..."), "a-b-c")
        self.assertEqual(ws.slug("Café 東京"), "café-東京")
        self.assertEqual(ws.slug("!!!"), "default")

    def test_unknown_active_ignored(self):
        cfg = ws.migrate({})
        self.assertEqual(ws.set_active(cfg, "missing"), cfg)

    def test_rename_collision_refused(self):
        cfg = ws.add_workspace(ws.migrate({}), "other")
        self.assertEqual(ws.rename_workspace(cfg, "default", "other"), cfg)

    def test_duplicate_collision_refused(self):
        cfg = ws.add_workspace(ws.migrate({}), "other")
        self.assertEqual(ws.duplicate_workspace(cfg, "default", "other"), cfg)

    def test_rename_active_preserves_text(self):
        cfg = ws.rename_workspace(ws.migrate({}), "default", "Trade Desk")
        self.assertEqual(cfg["active"], "Trade Desk")
        self.assertEqual(ws.workspace_names(cfg), ["Trade Desk"])
        self.assertEqual(ws.set_active(cfg, "trade-desk")["active"], "Trade Desk")

    def test_duplicate_is_independent(self):
        cfg = ws.migrate({"pane_count": 1, "panes": [{"name": "dev", "cmd": "vim"}]})
        result = ws.duplicate_workspace(cfg, "default", "copy")
        self.assertEqual(len(result["workspaces"]), 2)
        result["workspaces"][1]["panes"][0]["cmd"] = "bash"
        self.assertEqual(result["workspaces"][0]["panes"][0]["cmd"], "vim")
        self.assertEqual(len(cfg["workspaces"]), 1)

    def test_remove_active_selects_remaining(self):
        cfg = ws.add_workspace(ws.migrate({}), "other")
        cfg = ws.remove_workspace(cfg, "default")
        self.assertEqual(cfg["active"], "other")
        self.assertEqual(ws.workspace_names(cfg), ["other"])

    def test_update_only_workspace_fields(self):
        cfg = ws.update_workspace(ws.migrate({"font": "keep"}), pane_count=2,
                                  cwd="/tmp", layout="master", font="ignore", name="ignore")
        active = ws.active_workspace(cfg)
        self.assertEqual(len(active["panes"]), 2)
        self.assertEqual(active["cwd"], "/tmp")
        self.assertEqual(active["layout"], "master")
        self.assertEqual(active["name"], "default")
        self.assertEqual(cfg["font"], "keep")

    def test_padding_avoids_names_and_targets(self):
        cfg = ws.migrate({"pane_count": 4, "panes": [
            None, {"name": "g1", "cmd": "tmux attach -t g3"},
            {"name": "custom", "cmd": "tmux new-session -A -s g4"},
        ]})
        panes = ws.active_workspace(cfg)["panes"]
        self.assertEqual(panes[0]["name"], "g2")
        self.assertEqual(panes[3]["name"], "g5")

    def test_missing_command_uses_own_name(self):
        panes = ws.active_workspace(ws.migrate({
            "pane_count": 2, "panes": [{"name": "dev"}, {"name": "g1"}],
        }))["panes"]
        self.assertEqual(panes[0]["cmd"], "tmux new-session -A -s dev")
        self.assertEqual(panes[1]["cmd"], "tmux new-session -A -s g1")

    def test_validate_returns_deep_copy(self):
        cfg = ws.migrate({"theme": {"colors": ["red"]}})
        repaired = ws.validate(cfg)
        repaired["theme"]["colors"].append("blue")
        self.assertEqual(cfg["theme"]["colors"], ["red"])

    def test_arbitrary_json_damage(self):
        for raw in (None, [], "bad", 1, {}, {"workspaces": "bad"},
                    {"workspaces": [None, {"name": [], "layout": []}], "active": []},
                    {"pane_count": float("inf"), "panes": [{"cmd": []}]}):
            with self.subTest(raw=raw):
                cfg = ws.validate(raw)
                self.assertEqual(ws.validate(cfg), cfg)
                self.assertTrue(cfg["workspaces"])

    def test_repair_duplicate_workspace_names_without_losing_panes(self):
        cfg = ws.validate({"version": 2, "active": "bad", "workspaces": [
            {"name": "same", "panes": [{"name": "one", "cmd": "bash"}]},
            {"name": "same", "panes": [{"name": "two", "cmd": "vim"}]},
        ]})
        self.assertEqual(len(set(ws.workspace_names(cfg))), 2)
        self.assertEqual(cfg["workspaces"][1]["panes"][0]["cmd"], "vim")
        self.assertEqual(cfg["active"], "same")

    def test_copy_from_and_layout_override(self):
        cfg = ws.migrate({"pane_count": 2, "cwd": "/project"})
        cfg = ws.add_workspace(cfg, "copy", copy_from="default", layout="2x2")
        copied = ws.active_workspace(ws.set_active(cfg, "copy"))
        self.assertEqual(copied["cwd"], "/project")
        self.assertEqual(copied["pane_count"], 2)
        self.assertEqual(copied["layout"], "2x2")

    def test_supported_layouts(self):
        for layout in ("auto", "master", "2x2", "2x3", "3x2", "3x3", "4x2",
                       "1x1", "1x6", "6x1"):
            with self.subTest(layout=layout):
                self.assertEqual(ws.active_workspace(ws.migrate({"layout": layout}))
                                 ["layout"], layout)


if __name__ == "__main__":
    unittest.main()
