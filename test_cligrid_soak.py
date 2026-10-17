"""Always-on load checks for twenty panes and a bounded event log.

A Broadway 20-pane window lives in test_cligrid_headless.py and is skipped
when broadwayd is missing. This file never needs a display.
"""
import unittest

import cligrid_control as control
import cligrid_keymap as keymap
import cligrid_layout as layout

from cligrid import DEFAULT_KEYMAP, MAX_PANES


class TwentyPaneSoakTests(unittest.TestCase):
    def test_every_layout_covers_twenty_unique_positions(self):
        expected = list(range(MAX_PANES))
        for shape in layout.shape_names():
            cells = layout.cells(MAX_PANES, shape)
            positions = [pos for cell in cells for pos in cell["panes"]]
            with self.subTest(shape=shape):
                self.assertEqual(sorted(positions), expected)
                self.assertEqual(len(positions), MAX_PANES)

    def test_event_log_stays_bounded_under_a_burst(self):
        log = control.EventLog(limit=500)
        for n in range(5000):
            log.add("bell", pane="g%d" % ((n % MAX_PANES) + 1))
        self.assertEqual(len(log), 500)
        recent = log.recent(3)
        self.assertEqual([event["seq"] for event in recent], [4998, 4999, 5000])

    def test_wait_pattern_ceiling_still_holds_at_twenty_panes(self):
        for pane in range(1, MAX_PANES + 1):
            parsed = control.parse("wait %d --until ready --timeout 0" % pane)
            self.assertIsNone(parsed["error"])
            self.assertEqual(control.parse_wait(parsed["args"])["pane"], pane)

    def test_default_keymap_survives_a_full_override_roundtrip(self):
        rebuilt = keymap.merge(DEFAULT_KEYMAP, keymap.diff(DEFAULT_KEYMAP, DEFAULT_KEYMAP))
        self.assertEqual(rebuilt, dict(DEFAULT_KEYMAP))


if __name__ == "__main__":
    unittest.main()
