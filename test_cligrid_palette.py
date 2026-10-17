"""Test command palette matching, ranking, grouping, and highlights."""

import copy
import itertools
import unittest

import cligrid_palette as palette


class ScoreTests(unittest.TestCase):
    def test_word_start_beats_mid_word(self):
        self.assertGreater(palette.score('a', ' a')[0], palette.score('a', 'xa')[0])

    def test_case_insensitive(self):
        self.assertEqual(palette.score('GT', 'go to')[1], [0, 3])

    def test_non_subsequence(self):
        self.assertIsNone(palette.score('tg', 'go to'))

    def test_empty(self):
        self.assertEqual(palette.score('', 'anything'), (0, []))

    def test_bonuses(self):
        self.assertEqual(palette.score('a', 'a'), (25, [0]))
        self.assertEqual(palette.score('A', 'a'), (22, [0]))
        self.assertEqual(palette.score('ab', 'ab'), (47, [0, 1]))
        self.assertEqual(palette.score('ab', 'a b'), (50, [0, 2]))
        self.assertEqual(palette.score('a', 'xa'), (12, [1]))

    def test_leading_penalty_and_cap(self):
        for offset in (1, 5, 12, 13, 30):
            self.assertEqual(palette.score('a', ' ' * offset + 'a'),
                             (25 - min(12, offset), [offset]))

    def test_highest_score(self):
        self.assertEqual(palette.score('gt', 'go to pane 2'), (50, [0, 3]))
        self.assertEqual(palette.score('gt', 'gt t'), (50, [0, 3]))

    def test_bounds(self):
        self.assertIsNone(palette.score('a', 'x' * 400 + 'a'))
        self.assertEqual(palette.score('a' * 65, 'a' * 400)[1], list(range(64)))

    def test_matches_exhaustive_reference(self):
        for text in ('ab aB ab', 'gt t', 'a_ab', 'Ba aba'):
            for query in ('ab', 'aa', 'BA', 'gt', 'bbb'):
                candidates = []
                for indices in itertools.combinations(range(len(text)), len(query)):
                    if any(query[j].casefold() != text[i].casefold()
                           for j, i in enumerate(indices)):
                        continue
                    value = -min(12, indices[0])
                    for j, i in enumerate(indices):
                        value += 10 + 12 * (i == 0 or not text[i - 1].isalnum())
                        value += 9 * (j > 0 and indices[j - 1] == i - 1)
                        value += 3 * (query[j] == text[i])
                    candidates.append((value, indices))
                expected = max((value for value, _ in candidates), default=None)
                actual = palette.score(query, text)
                self.assertEqual(None if actual is None else actual[0], expected)


class RankTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(label='Alpha', hint='first', section='Actions'),
                     dict(label='Beta', hint='alpha', section='Panes'),
                     dict(label='Gamma', hint='third', section='Themes')]

    def test_tie_stability(self):
        rows = [dict(label='a', hint='', section=str(i)) for i in range(3)]
        self.assertEqual([r['section'] for r in palette.rank('a', rows)], ['0', '1', '2'])

    def test_no_mutation(self):
        before = copy.deepcopy(self.rows)
        for query in ('a', ''):
            result = palette.rank(query, self.rows, recents=('Gamma',))
            self.assertTrue(all(all(r is not original for original in self.rows) for r in result))
        self.assertEqual(self.rows, before)

    def test_limit(self):
        self.assertEqual(len(palette.rank('a', self.rows, limit=2)), 2)
        self.assertEqual(palette.rank('', self.rows, limit=0), [])
        self.assertEqual(len(palette.rank('', self.rows, limit=1)), 1)

    def test_empty_recents(self):
        result = palette.rank('', self.rows, recents=('Gamma', 'missing', 'Alpha', 'Gamma'))
        self.assertEqual([r['label'] for r in result], ['Gamma', 'Alpha', 'Beta'])
        self.assertEqual([r['section'] for r in result], ['Recent', 'Recent', 'Panes'])
        self.assertTrue(all(r['score'] == 0 and r['match'] == [] for r in result))
        self.assertEqual([r['label'] for r in palette.rank('', self.rows)],
                         ['Alpha', 'Beta', 'Gamma'])

    def test_label_before_hint(self):
        rows = [dict(label='xa', hint='a', section='Actions'),
                dict(label='zzz', hint='a', section='Actions')]
        result = palette.rank('a', rows)
        self.assertEqual([(r['label'], r['score'], r['match']) for r in result],
                         [('zzz', 25, []), ('xa', 12, [1])])
        self.assertEqual(palette.rank('q', rows), [])


class GroupTests(unittest.TestCase):
    def test_spans(self):
        self.assertEqual(palette.highlight_spans([7, 2, 0, 1, 2]), [(0, 3), (7, 8)])
        self.assertEqual(palette.highlight_spans([]), [])

    def test_sections(self):
        rows = [dict(section=s) for s in ('Other', 'Themes', 'Actions', 'Recent',
                                          'Panes', 'Layouts', 'Workspaces', 'Extra', 'Actions')]
        groups = palette.sections(rows)
        self.assertEqual([name for name, _ in groups], list(palette.SECTION_ORDER) + ['Other', 'Extra'])
        self.assertEqual(groups[1][1], [rows[2], rows[8]])
        self.assertEqual(palette.sections([]), [])


if __name__ == '__main__':
    unittest.main()
