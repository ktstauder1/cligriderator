"""Unit tests for keymap merge and conflict detection."""
import unittest

import cligrid_keymap as km


DEFAULTS = {
    "Z": "zoom",
    "Q": "quit",
    "P": "palette",
    "space": "unused",
}


class MergeTests(unittest.TestCase):
    def test_user_override_replaces_a_default(self):
        self.assertEqual(km.merge(DEFAULTS, {"Z": "quit"})["Z"], "quit")

    def test_empty_override_removes_the_binding(self):
        merged = km.merge(DEFAULTS, {"Z": ""})
        self.assertNotIn("Z", merged)
        self.assertEqual(merged["Q"], "quit")

    def test_unknown_user_key_is_added(self):
        self.assertEqual(km.merge(DEFAULTS, {"F1": "doctor"})["F1"], "doctor")

    def test_non_dict_user_map_is_ignored(self):
        self.assertEqual(km.merge(DEFAULTS, None), DEFAULTS)
        self.assertEqual(km.merge(DEFAULTS, ["Z"]), DEFAULTS)


class ConflictTests(unittest.TestCase):
    def test_unknown_action_is_reported(self):
        known = {"zoom", "quit", "palette"}
        rows = km.conflicts({"Z": "zoom", "X": "explode"}, known, prefix_keys=())
        self.assertEqual(rows, [("X", "explode", "unknown action")])

    def test_prefix_key_that_is_also_bound_is_reported(self):
        rows = km.conflicts(DEFAULTS, set(DEFAULTS.values()), prefix_keys=("space",))
        self.assertEqual(rows, [("space", "unused", "collides with the prefix key")])

    def test_clean_map_is_silent(self):
        known = {"zoom", "quit", "palette"}
        self.assertEqual(km.conflicts(
            {"Z": "zoom", "Q": "quit"}, known, prefix_keys=("space",)), [])

    def test_invert_groups_keys_by_action(self):
        grouped = km.invert({"Z": "zoom", "H": "focus.left", "Left": "focus.left"})
        self.assertEqual(grouped["zoom"], ["Z"])
        self.assertEqual(grouped["focus.left"], ["H", "Left"])


class LookupAndShortcutTests(unittest.TestCase):
    MAP = {"C": "copy", "V": "paste", "Z": "zoom", "c": "never"}

    def test_lookup_tries_exact_then_case_variants(self):
        self.assertEqual(km.lookup(self.MAP, "C"), "copy")
        self.assertEqual(km.lookup(self.MAP, "c"), "never")
        self.assertEqual(km.lookup({"V": "paste"}, "v"), "paste")
        self.assertEqual(km.lookup({"v": "paste"}, "V"), "paste")
        self.assertIsNone(km.lookup(self.MAP, "Q"))
        self.assertIsNone(km.lookup(None, "C"))
        self.assertIsNone(km.lookup(self.MAP, ""))

    def test_ctrl_shift_looks_up_the_keymap(self):
        self.assertEqual(km.resolve_shortcut(self.MAP, "C", True, True, False), "copy")
        self.assertEqual(km.resolve_shortcut(self.MAP, "z", True, True, False), "zoom")

    def test_ctrl_c_copies_only_when_text_is_selected(self):
        self.assertEqual(km.resolve_shortcut(self.MAP, "c", True, False, True), "copy")
        self.assertEqual(km.resolve_shortcut(self.MAP, "C", True, False, True), "copy")
        self.assertIsNone(km.resolve_shortcut(self.MAP, "c", True, False, False))

    def test_ctrl_v_pastes_without_shift(self):
        self.assertEqual(km.resolve_shortcut(self.MAP, "v", True, False, False), "paste")
        self.assertEqual(km.resolve_shortcut(self.MAP, "V", True, False, False), "paste")

    def test_wayland_drops_shift_mask_but_keeps_the_shifted_name(self):
        # COSMIC/GTK3 often reports Ctrl+Shift+Z as Control + "Z" with no SHIFT_MASK.
        self.assertEqual(km.resolve_shortcut(self.MAP, "Z", True, False, False), "zoom")

    def test_plain_ctrl_letter_still_reaches_the_terminal(self):
        self.assertIsNone(km.resolve_shortcut(self.MAP, "z", True, False, False))
        self.assertIsNone(km.resolve_shortcut(self.MAP, "q", True, False, False))
        self.assertIsNone(km.resolve_shortcut(self.MAP, "C", False, False, True))


class DiffAndParseTests(unittest.TestCase):
    def test_diff_omits_unchanged_defaults(self):
        self.assertEqual(km.diff(DEFAULTS, dict(DEFAULTS)), {})

    def test_diff_records_unbinds_and_additions(self):
        merged = {"Q": "quit", "P": "palette", "F1": "doctor"}
        self.assertEqual(km.diff(DEFAULTS, merged), {"Z": "", "space": "", "F1": "doctor"})

    def test_merge_of_a_diff_recreates_the_map(self):
        merged = {"Q": "quit", "F1": "doctor"}
        self.assertEqual(km.merge(DEFAULTS, km.diff(DEFAULTS, merged)), merged)

    def test_parse_fields_keeps_the_first_duplicate(self):
        built, rows = km.parse_fields([("zoom", "Z"), ("quit", "Z Q")])
        self.assertEqual(built, {"Z": "zoom", "Q": "quit"})
        self.assertEqual(rows, [("Z", "quit", "already bound to zoom")])

    def test_known_ids_include_focus_slots(self):
        ids = km.known_ids(["zoom"], max_panes=3)
        self.assertEqual(ids, {"zoom", "focus.1", "focus.2", "focus.3"})


if __name__ == "__main__":
    unittest.main()
