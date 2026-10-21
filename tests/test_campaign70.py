"""Проверки кампании без зависимости от оконной подсистемы и tkinter.

Из монолитного приложения извлекаются только чистые константы и функция перепланирования.
python -m unittest discover -s tests -p 'test_campaign70.py'
"""
import ast
import copy
from datetime import date, timedelta
from pathlib import Path
import unittest

NAMES = {'CAMPAIGN', 'CAMPAIGN_START', 'CAMPAIGN_END', 'SYS_PHASES', 'SYS_DAY_TYPES',
         'SYS_WEEKDAY_TYPES', 'SYS_SEED_TASKS', 'replan_70'}
tree = ast.parse((Path(__file__).resolve().parents[1] / 'genshtab.py').read_text())
selected = [n for n in tree.body if
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NAMES for t in n.targets)
            or isinstance(n, ast.FunctionDef) and n.name in NAMES]
g = {}
exec(compile(ast.Module(body=selected, type_ignores=[]), 'campaign', 'exec'), g)


class Campaign70(unittest.TestCase):
    def test_period_and_weekly_template(self):
        start, end = date.fromisoformat(g['CAMPAIGN_START']), date.fromisoformat(g['CAMPAIGN_END'])
        self.assertEqual((end - start).days + 1, 70)
        hours = {d['name']: d['hours'] for d in g['SYS_DAY_TYPES']}
        total = sum(hours[g['SYS_WEEKDAY_TYPES'][(start + timedelta(days=i)).weekday()]] for i in range(70))
        self.assertEqual(total, 630)

    def test_phases(self):
        starts = [date.fromisoformat(p['start']) for p in g['SYS_PHASES']]
        self.assertEqual(starts[0].isoformat(), g['CAMPAIGN_START'])
        ends = starts[1:] + [date.fromisoformat(g['CAMPAIGN_END']) + timedelta(days=1)]
        self.assertEqual([(b-a).days for a, b in zip(starts, ends)], [10, 28, 32])

    def test_seed_tasks_not_overdue_at_start(self):
        for _, _, _, due, _ in g['SYS_SEED_TASKS']:
            self.assertGreaterEqual(due, g['CAMPAIGN_START'])

    def test_replan_preserves_records_rules_and_archive(self):
        original = {'name': 'Кампания-85', 'start': '2026-10-08', 'end': '2026-12-31',
                    'goals': {'hours': 750, 'sleep': 8}, 'phases': [{'name': 'Свой этап'}],
                    'rules_text': 'Мой личный устав', 'rules': {'duties_on': False},
                    'days': {'2026-10-10': {'hours': 4}}, 'xp_carry': 1000}
        s = copy.deepcopy(original)
        g['replan_70'](s)
        self.assertEqual(s['goals'], {'hours': 630, 'sleep': 8})
        for key in ('days', 'xp_carry', 'rules', 'rules_text'):
            self.assertEqual(s[key], original[key])
        self.assertEqual(s['archive']['before_70']['goals']['hours'], 750)
        s['goals']['sleep'] = 9
        self.assertEqual(s['archive']['before_70']['goals']['sleep'], 8)
        archive = copy.deepcopy(s['archive'])
        g['replan_70'](s)
        self.assertEqual(s['archive'], archive)


if __name__ == '__main__':
    unittest.main()
