"""Contract tests; run with /usr/bin/python3 test_cligrid_layout.py."""

import sys
import unittest

# Keep the requested standalone check from creating files outside its two-file scope.
sys.dont_write_bytecode = True

import cligrid_layout as layout


class LayoutTests(unittest.TestCase):
    def assert_invariants(self, count, shape, groups=None):
        result = layout.cells(count, shape, groups)
        self.assertEqual(sorted(p for cell in result for p in cell["panes"]),
                         list(range(count)))
        rows = layout.shape_for(count, shape)[1]
        covered = set()
        occupied = set()
        for cell in result:
            self.assertEqual(set(cell), {"col", "row", "span", "rowspan", "panes"})
            self.assertGreater(cell["span"], 0)
            self.assertGreater(cell["rowspan"], 0)
            self.assertLessEqual(cell["row"] + cell["rowspan"], rows)
            self.assertGreaterEqual(cell["col"], 0)
            self.assertLessEqual(cell["col"] + cell["span"], 6)
            for row in range(cell["row"], cell["row"] + cell["rowspan"]):
                covered.add(row)
                for col in range(cell["col"], cell["col"] + cell["span"]):
                    self.assertNotIn((col, row), occupied)
                    occupied.add((col, row))
        for row in covered:
            self.assertEqual(sum(c["span"] for c in result
                                 if c["row"] <= row < c["row"] + c["rowspan"]), 6)
        self.assertEqual([(c["row"], c["col"]) for c in result],
                         sorted((c["row"], c["col"]) for c in result))

    def test_all_shapes_invariants(self):
        for shape in layout.shape_names():
            for count in range(1, 21):
                with self.subTest(shape=shape, count=count):
                    self.assert_invariants(count, shape)

    def test_grouped_invariants(self):
        for shape in layout.shape_names():
            for count in range(1, 21):
                groups = [list(range(p, min(p + 2, count))) for p in range(0, count, 2)]
                with self.subTest(shape=shape, count=count):
                    self.assert_invariants(count, shape, groups)

    def test_auto_matches_cligrid(self):
        try:
            import cligrid
        except Exception as exc:
            self.skipTest(f"cligrid import unavailable: {exc}")
        for count in range(1, 9):
            self.assertEqual([(c["col"], c["row"], c["span"])
                              for c in layout.cells(count)], cligrid.grid_cells(count))

    def test_auto_known_geometry(self):
        expected = {
            1: [(0, 0, 6)], 2: [(0, 0, 3), (3, 0, 3)],
            3: [(0, 0, 2), (2, 0, 2), (4, 0, 2)],
            4: [(0, 0, 3), (3, 0, 3), (0, 1, 3), (3, 1, 3)],
            5: [(0, 0, 2), (2, 0, 2), (4, 0, 2), (0, 1, 3), (3, 1, 3)],
        }
        for count, geometry in expected.items():
            self.assertEqual([(c["col"], c["row"], c["span"])
                              for c in layout.cells(count)], geometry)

    def test_shape_names(self):
        names = layout.shape_names()
        required = {"auto", "master", "2x2", "2x3", "3x2", "3x3", "4x2"}
        required.update(f"1x{n}" for n in range(1, 7))
        required.update(f"{n}x1" for n in range(1, 7))
        self.assertTrue(required <= set(names))
        self.assertEqual(names, sorted(set(names)))
        names.clear()
        self.assertIn("auto", layout.shape_names())
        self.assertEqual(layout.SUBCOLS, 6)

    def test_normalize_shape(self):
        for name in layout.shape_names():
            self.assertEqual(layout.normalize_shape(name), name)
        for name in ("unknown", "", None, [], 42):
            self.assertEqual(layout.normalize_shape(name), "auto")

    def test_shape_for(self):
        self.assertEqual(layout.shape_for(4), (2, 2))
        self.assertEqual(layout.shape_for(8), (3, 3))
        self.assertEqual(layout.shape_for(20, "4x2"), (4, 5))
        self.assertEqual(layout.shape_for(2, "6x1"), (2, 1))
        self.assertEqual(layout.shape_for(7, "1x6"), (1, 7))

    def test_short_rows(self):
        for shape in layout.shape_names():
            expected = 2
            if "x" in shape:
                columns, rows = map(int, shape.split("x"))
                if 1 in (columns, rows):
                    expected = max(2, columns, rows)
            for count in (1, 7, 20):
                self.assertEqual(layout.short_rows(count, shape), expected)

    def test_master(self):
        self.assertEqual(layout.shape_for(5, "master"), (2, 4))
        result = layout.cells(5, "master")
        self.assertEqual(result[0], dict(col=0, row=0, span=3, rowspan=4, panes=[0]))
        self.assertEqual(result[1:], [dict(col=3, row=p - 1, span=3, rowspan=1, panes=[p])
                                     for p in range(1, 5)])

    def test_single_master(self):
        self.assertEqual(layout.shape_for(1, "master"), (1, 1))
        self.assertEqual(layout.cells(1, "master"),
                         [dict(col=0, row=0, span=6, rowspan=1, panes=[0])])

    def test_integer_widths(self):
        self.assertEqual([c["span"] for c in layout.cells(4, "4x1")], [2, 2, 1, 1])
        self.assertEqual([c["span"] for c in layout.cells(5, "5x1")], [2, 1, 1, 1, 1])
        self.assertEqual([c["span"] for c in layout.cells(6, "6x1")], [1] * 6)

    def test_groups(self):
        groups = [[2], [1, 0], [3]]
        self.assertEqual([c["panes"] for c in layout.cells(4, groups=groups)],
                         [[1, 0], [2], [3]])
        self.assertEqual(groups, [[2], [1, 0], [3]])

    def test_singleton_groups(self):
        for shape in layout.shape_names():
            self.assertEqual(layout.cells(5, shape, [[p] for p in range(5)]),
                             layout.cells(5, shape))

    def test_duplicate_groups(self):
        for groups in ([[0, 0], [1]], [[0], [0, 1]]):
            with self.assertRaises(ValueError):
                layout.cells(2, groups=groups)

    def test_omitted_groups(self):
        for groups in ([], [[0]]):
            with self.assertRaises(ValueError):
                layout.cells(2, groups=groups)

    def test_unknown_group_positions(self):
        for groups in ([[0], [2]], [[-1], [1]], [[0], ["1"]], [[0], [True]]):
            with self.assertRaises(ValueError):
                layout.cells(2, groups=groups)

    def test_malformed_groups(self):
        for groups in ([[0, 1], []], [0, 1], "01", [[0], None]):
            with self.assertRaises(ValueError):
                layout.cells(2, groups=groups)

    def test_neighbor_edges(self):
        for pos, direction in ((0, "left"), (0, "up"), (2, "right"), (4, "down")):
            self.assertEqual(layout.neighbor(5, pos, direction), pos)
        self.assertEqual(layout.neighbor(5, 2, "bogus"), 2)

    def test_neighbor_rows(self):
        for pos, direction, expected in ((0, "right", 1), (1, "left", 0),
                                         (1, "down", 4), (3, "up", 0), (4, "up", 2)):
            self.assertEqual(layout.neighbor(5, pos, direction), expected)

    def test_neighbor_master(self):
        self.assertEqual(layout.neighbor(5, 0, "right", "master"), 3)
        for pos in range(1, 5):
            self.assertEqual(layout.neighbor(5, pos, "left", "master"), 0)
        self.assertEqual(layout.neighbor(5, 2, "down", "master"), 3)
        self.assertEqual(layout.neighbor(5, 3, "up", "master"), 2)
        self.assertEqual(layout.neighbor(5, 0, "down", "master"), 0)

    def test_neighbor_groups(self):
        groups = [[0, 1], [2]]
        self.assertEqual(layout.neighbor(3, 1, "right", groups=groups), 2)
        self.assertEqual(layout.neighbor(3, 2, "left", groups=groups), 0)
        self.assertEqual(layout.neighbor(3, 1, "left", groups=groups), 1)

    def test_neighbor_bounds(self):
        for shape in layout.shape_names():
            for count in range(1, 21):
                for pos in range(-1, count + 1):
                    for direction in ("left", "right", "up", "down"):
                        self.assertIn(layout.neighbor(count, pos, direction, shape), range(count))

    def test_count_normalization(self):
        for count in (0, -1, None, "invalid"):
            self.assertEqual(layout.cells(count), layout.cells(1))
        self.assertEqual(layout.shape_for("4"), (2, 2))

    def test_results_are_independent(self):
        groups = [[0, 1], [2]]
        result = layout.cells(3, groups=groups)
        result[0]["panes"].clear()
        self.assertEqual(groups, [[0, 1], [2]])
        self.assertEqual(layout.cells(3, groups=groups)[0]["panes"], [0, 1])


if __name__ == "__main__":
    unittest.main()
