"""Pure control protocol contract tests; run with /usr/bin/python3 test_cligrid_control.py."""

import json
import sys
import unittest

sys.dont_write_bytecode = True

from cligrid_control import (
    GUARDED_VERBS, VERBS, EventLog, Waiter, event_kinds, format_event, guard_refusal,
    pane_positions, parse, parse_events, parse_wait, split_force,
)


class GuardTests(unittest.TestCase):
    def test_force_only_counts_directly_after_the_verb(self):
        self.assertEqual(split_force(["reset", "--force", "2"]), (["reset", "2"], True))
        self.assertEqual(split_force(["all", "--force", "htop"]), (["all", "htop"], True))
        self.assertEqual(split_force(["all", "git", "push", "--force"]),
                         (["all", "git", "push", "--force"], False))
        self.assertEqual(split_force(["--force"]), (["--force"], False))
        self.assertEqual(split_force([]), ([], False))

    def test_guarded_verbs_are_the_ones_that_end_work(self):
        for verb in ("reset", "fresh", "new", "all", "fill", "run-all", "remove",
                     "close-window", "quit"):
            self.assertIn(verb, GUARDED_VERBS)
        for verb in ("send", "run", "dump", "wait", "status", "focus", "restart", "ws"):
            self.assertNotIn(verb, GUARDED_VERBS)

    def test_refusal_needs_a_guarded_verb_from_a_pane_without_force(self):
        self.assertIn("refused: reset", guard_refusal("reset", False, True))
        self.assertIsNone(guard_refusal("reset", True, True))
        self.assertIsNone(guard_refusal("reset", False, False))
        self.assertIsNone(guard_refusal("status", False, True))
        self.assertIsNone(guard_refusal("reset", False, True, mode="off"))


EXPECTED_VERBS = tuple(sorted(
    "show raise hide toggle zoom panes windows remove close-window restart reset fresh new "
    "all fill run-all fit focus swap status quit send run dump wait events watch help ws "
    "workspace layout theme doctor rename move palette find log notify keymap state version "
    "stack"
    .split()
))


class ParseTests(unittest.TestCase):
    def test_every_contract_verb_is_reachable(self):
        self.assertEqual(VERBS, EXPECTED_VERBS)
        required = {
            "all": " htop", "fill": " htop", "run-all": " htop", "focus": " 1",
            "swap": " 1 2", "wait": " 3 done", "send": " 1 hello", "run": " 1 htop",
        }
        for verb in EXPECTED_VERBS:
            with self.subTest(verb=verb):
                result = parse(verb + required.get(verb, ""))
                self.assertEqual(result, {
                    "verb": verb, "args": result["args"], "error": None,
                })

    def test_unknown_verbs(self):
        for verb in ("bogus", "SHOW", "showcase", "close", "RUN", "--help"):
            with self.subTest(verb=verb):
                result = parse(verb)
                self.assertNotIn(verb, VERBS)
                self.assertIn(verb, result["error"])
                self.assertIn("help", result["error"])

    def test_empty_line_is_show(self):
        for line in ("", " \t\n"):
            self.assertEqual(parse(line), {"verb": "show", "args": [], "error": None})

    def test_show_raise_aliases(self):
        for verb in ("show", "raise"):
            self.assertIsNone(parse(verb + " ignored '")["error"])

    def test_panes_windows_aliases(self):
        for verb in ("panes", "windows"):
            self.assertIsNone(parse(verb)["error"])
            self.assertIsNone(parse(verb + " 200 ignored")["error"])
            self.assertEqual(parse(verb + " bad")["error"],
                             "panes expects a count from 1 to 20")

    def test_remove_close_window_aliases(self):
        for verb in ("remove", "close-window"):
            self.assertIsNone(parse(verb)["error"])
            self.assertIsNone(parse(verb + " 0")["error"])
            self.assertEqual(parse(verb + " bad")["error"],
                             "remove expects a window number 1-20")

    def test_reset_fresh_new_aliases(self):
        for verb in ("reset", "fresh", "new"):
            self.assertIsNone(parse(verb)["error"])
            self.assertIsNone(parse(verb + " -1 ignored")["error"])
            self.assertEqual(parse(verb + " bad")["error"],
                             "reset expects a pane number 1-20, or no argument for every pane")

    def test_all_fill_run_all_preserve_shell_text(self):
        for verb in ("all", "fill", "run-all"):
            self.assertEqual(parse(verb + "  printf '%s  x'  $HOME ")["args"],
                             ["printf '%s  x'  $HOME "])
            self.assertIsNone(parse(verb + " echo '")["error"])
            self.assertEqual(parse(verb)["error"], "all expects a command, e.g. all htop")
            self.assertEqual(parse(verb + "\thtop")["error"],
                             "all expects a command, e.g. all htop")

    def test_zoom_usage_and_defaults(self):
        for suffix in ("", " toggle", " off", " 0", " 999", " 1 ignored"):
            self.assertIsNone(parse("zoom" + suffix)["error"])
        self.assertEqual(parse("zoom bad")["error"],
                         "zoom expects a pane number 1-20 or off")

    def test_focus_usage(self):
        for suffix in ("", " bad", " 0", " 21"):
            self.assertEqual(parse("focus" + suffix)["error"],
                             "focus expects a pane number 1-20")

    def test_restart_usage_and_default(self):
        self.assertIsNone(parse("restart")["error"])
        self.assertIsNone(parse("restart 0 ignored")["error"])
        self.assertEqual(parse("restart bad")["error"],
                         "restart expects a pane number 1-20")

    def test_legacy_index_boundaries(self):
        for verb in ("remove", "close-window", "restart", "reset", "fresh", "new"):
            for number in (-19, 0, 20):
                with self.subTest(verb=verb, number=number):
                    self.assertIsNone(parse("%s %d" % (verb, number))["error"])
            for number in (-20, 21):
                with self.subTest(verb=verb, number=number):
                    self.assertIsNotNone(parse("%s %d" % (verb, number))["error"])

    def test_swap_usage(self):
        for suffix in ("", " 1", " a 2"):
            self.assertEqual(parse("swap" + suffix)["error"],
                             "swap expects two positions, e.g. swap 1 6")
        for suffix in (" 0 2", " 1 21"):
            self.assertEqual(parse("swap" + suffix)["error"], "swap positions are 1-20")
        self.assertIsNone(parse("swap 1 2 ignored")["error"])

    def test_legacy_arguments_are_not_shell_unquoted(self):
        self.assertEqual(parse('focus "1"')["error"], "focus expects a pane number 1-20")
        self.assertEqual(parse("status unused '")["args"], ["unused", "'"])

    def test_new_commands_support_quoting(self):
        self.assertEqual(parse("send 3 'hello world'")["args"], ["3", "hello world"])
        result = parse("wait 3 --until 'foo|bar' --timeout 60")
        self.assertIsNone(result["error"])
        self.assertEqual(parse_wait(result["args"])["pattern"], "foo|bar")
        self.assertIsNotNone(parse("send 3 '")["error"])

    def test_parse_exposes_wait_and_events_errors(self):
        self.assertIn("pattern", parse("wait 3")["error"])
        self.assertIn("since", parse("events --since bad")["error"])


class PositionsTests(unittest.TestCase):
    def test_all(self):
        self.assertEqual(pane_positions(" all ", 4), [1, 2, 3, 4])
        self.assertEqual(pane_positions("all", 0), [])

    def test_focused(self):
        self.assertEqual(pane_positions("focused", 4), [])

    def test_ranges(self):
        self.assertEqual(pane_positions("1,3,4-6", 6), [1, 3, 4, 5, 6])

    def test_whitespace(self):
        self.assertEqual(pane_positions(" 1, 3, 4 - 6 ", 6), [1, 3, 4, 5, 6])
        self.assertEqual(pane_positions("1 3\t5", 6), [1, 3, 5])

    def test_duplicates(self):
        self.assertEqual(pane_positions("3,1,3,1-3", 4), [1, 2, 3])

    def test_reversed_ranges(self):
        self.assertEqual(pane_positions("5-2", 6), [2, 3, 4, 5])

    def test_invalid_specs(self):
        for spec in ("0", "7", "1-7", "wat", "1-x", "", "1,,2", "-1", "1.5"):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "pane"):
                pane_positions(spec, 6)

    def test_invalid_count(self):
        for count in (-1, 1.5, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                pane_positions("all", count)


class WaitTests(unittest.TestCase):
    def test_flags_and_default(self):
        self.assertEqual(parse_wait(["3", "--until", "foo|bar"]),
                         {"pane": 3, "pattern": "foo|bar", "timeout": 30.0})
        self.assertEqual(parse_wait(["3", "--until", "foo|bar", "--timeout", "60"]),
                         {"pane": 3, "pattern": "foo|bar", "timeout": 60.0})

    def test_positional(self):
        self.assertEqual(parse_wait(["3", "foo|bar", "2.5"]),
                         {"pane": 3, "pattern": "foo|bar", "timeout": 2.5})

    def test_bad_regex(self):
        with self.assertRaisesRegex(ValueError, "regex"):
            parse_wait(["3", "["])

    def test_missing_pattern(self):
        for args in ([], ["3"], ["3", "--until"], ["3", ""]):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "pattern"):
                parse_wait(args)

    def test_negative_or_nonfinite_timeout(self):
        for timeout in ("-1", "nan", "inf", "oops"):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "timeout"):
                parse_wait(["3", "foo", timeout])

    def test_bad_pane_and_options(self):
        for args in (["0", "x"], ["21", "x"], ["x", "x"],
                     ["3", "--bad", "x"], ["3", "x", "1", "extra"],
                     ["3", "x", "--until", "y"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_wait(args)

    def test_waiter_matching_and_timeout_boundary(self):
        waiter = Waiter(**parse_wait(["3", "foo|bar", "2"]), now=10.0)
        self.assertFalse(waiter.matches(2, "foo"))
        self.assertFalse(waiter.matches(3, "no match"))
        self.assertTrue(waiter.matches(3, "prefix bar suffix"))
        self.assertFalse(waiter.expired(11.999))
        self.assertTrue(waiter.expired(12.0))


class EventsTests(unittest.TestCase):
    def test_unfiltered(self):
        self.assertEqual(parse_events([]), {"kinds": [], "since": 0})
        self.assertEqual(parse_events(["--follow"]), {"kinds": [], "since": 0})

    def test_filtered(self):
        args = ["--kinds", "bell,exit", "--since", "42", "--follow"]
        self.assertEqual(parse_events(args),
                         {"kinds": ["bell", "exit"], "since": 42})

    def test_bad_filters(self):
        for args in (["--since"], ["--since", "-1"], ["--since", "x"],
                     ["--kinds"], ["--kinds", "bogus"], ["--bad"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_events(args)

    def test_event_kinds(self):
        self.assertEqual(set(event_kinds()), set(
            "boot spawn exit bell activity focus cwd state workspace layout alert error "
            "reply toast"
            .split()
        ))
        kinds = event_kinds()
        kinds.clear()
        self.assertEqual(len(event_kinds()), 14)

    def test_eviction_and_stamps(self):
        log = EventLog(limit=2)
        first = log.add("boot", seq=999, time="bad")
        second = log.add("bell", pane=3)
        third = log.add("exit", status=0)
        self.assertEqual([first["seq"], second["seq"], third["seq"]], [1, 2, 3])
        self.assertIsInstance(first["time"], float)
        self.assertEqual(len(log), 2)
        self.assertEqual(log.recent(), [second, third])

    def test_since_boundary(self):
        log = EventLog(2)
        for kind in ("boot", "bell", "exit"):
            log.add(kind)
        self.assertEqual([e["seq"] for e in log.since(1)], [2, 3])
        self.assertEqual([e["seq"] for e in log.since(2)], [3])
        self.assertEqual(log.since(3), [])
        self.assertEqual(log.since(100), [])

    def test_recent_limits(self):
        log = EventLog()
        self.assertEqual(log.recent(), [])
        log.add("boot")
        last = log.add("bell")
        self.assertEqual(log.recent(1), [last])
        self.assertEqual(log.recent(0), [])
        self.assertEqual(len(log.recent(100)), 2)

    def test_invalid_limits(self):
        for limit in (-1, 1.5, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                EventLog(limit)
        log = EventLog(0)
        self.assertEqual(log.add("boot")["seq"], 1)
        self.assertEqual(len(log), 0)

    def test_format_round_trip(self):
        event = EventLog().add("reply", message="two\nlines", pane=2)
        line = format_event(event)
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(json.loads(line), event)

    def test_format_unserializable_fields(self):
        value = object()
        self.assertEqual(json.loads(format_event({"value": value})), {"value": str(value)})
        cyclic = []
        cyclic.append(cyclic)
        self.assertIsInstance(json.loads(format_event({"value": cyclic})), (dict, str))
        self.assertIsInstance(json.loads(format_event({("tuple",): value})), (dict, str))


if __name__ == "__main__":
    unittest.main()
