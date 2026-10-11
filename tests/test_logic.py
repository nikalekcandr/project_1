"""Проверки логики Генштаба без окна: разбор строк быстрого ввода, правила, нормативы, казна, сигналы.

Запуск из папки проекта: python -m unittest discover tests
Нужен Python с tkinter (модуль импортирует его), экран не нужен.
"""
import importlib.util
import pathlib
import unittest
from datetime import date, datetime

SRC = pathlib.Path(__file__).resolve().parent.parent / "genshtab.py"
spec = importlib.util.spec_from_file_location("genshtab", SRC)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

NOW = datetime(2026, 10, 11, 20, 15)  # воскресенье
TODAY = NOW.date()


class Signals(unittest.TestCase):
    def test_time_today_or_tomorrow(self):
        self.assertEqual(g.parse_signal("21:30 карточки", NOW, TODAY)[0], datetime(2026, 10, 11, 21, 30))
        self.assertEqual(g.parse_signal("18:00 посылка", NOW, TODAY)[0], datetime(2026, 10, 12, 18, 0))

    def test_relative_and_dated(self):
        self.assertEqual(g.parse_signal("через 40 мин встать", NOW, TODAY)[0], datetime(2026, 10, 11, 20, 55))
        self.assertEqual(g.parse_signal("через 2 ч размяться", NOW, TODAY)[0], datetime(2026, 10, 11, 22, 15))
        self.assertEqual(g.parse_signal("завтра 9:30 позвонить", NOW, TODAY)[:2],
                         (datetime(2026, 10, 12, 9, 30), "позвонить"))
        self.assertEqual(g.parse_signal("25.10 10:00 экзамен", NOW, TODAY)[0], datetime(2026, 10, 25, 10, 0))

    def test_repeat_on_weekdays_skips_weekend(self):
        at, text, repeat = g.parse_signal("по будням 21:30 сводка", NOW, TODAY)
        self.assertEqual((at, repeat), (datetime(2026, 10, 12, 21, 30), "wd"))
        self.assertEqual(g.next_signal(datetime(2026, 10, 16, 21, 30), "wd"), datetime(2026, 10, 19, 21, 30))

    def test_errors(self):
        for bad in ("позвонить", "10.10 18:00 прошлое", "18:00"):
            with self.assertRaises(ValueError):
                g.parse_signal(bad, NOW, TODAY)


class Urges(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(g.parse_urge("ютуб 4 после обеда", g.URGE_KINDS), ("YouTube и видео", 4, "после обеда"))
        self.assertEqual(g.parse_urge("лента 5", g.URGE_KINDS), ("Лента и соцсети", 5, ""))
        self.assertEqual(g.parse_urge("сладкое", g.URGE_KINDS), ("Сладкое и перекус", 3, ""))
        self.assertEqual(g.parse_urge("бросить штурм 4 устал", g.URGE_KINDS)[:2], ("Бросить штурм раньше", 4))


class Money(unittest.TestCase):
    def test_lines(self):
        cats = g.MONEY_CATS
        self.assertEqual(g.parse_money_line("350 кафе шаурма", cats), (350.0, "Кафе и доставка", "шаурма", False))
        self.assertEqual(g.parse_money_line("1,2к продукты", cats)[:2], (1200.0, "Продукты"))
        self.assertTrue(g.parse_money_line("900 одежда футболка !", cats)[3])
        self.assertEqual(g.parse_money_line("350р такси", cats)[:2], (350.0, "Транспорт"))
        self.assertEqual(g.parse_money_line("300 непонятно что", cats)[1], "Прочее")
        with self.assertRaises(ValueError):
            g.parse_money_line("кафе 350", cats)

    def test_format(self):
        self.assertEqual(g.fmt_money(1250.5), "1 250,50 ₽")
        self.assertEqual(g.fmt_money(30000), "30 000 ₽")
        self.assertEqual(g.fmt_money(-1500), "−1 500 ₽")


class Fitness(unittest.TestCase):
    def test_values(self):
        self.assertEqual(g.parse_fit_value("time", "3:45"), 225)
        self.assertEqual(g.parse_fit_value("time", "14"), 840)
        self.assertEqual(g.parse_fit_value("time", "225"), 225)
        self.assertEqual(g.parse_fit_value("count", "12"), 12)
        self.assertEqual(g.fmt_fit_value("time", 800), "13:20")

    def test_grades(self):
        pull = {"better": "more", "grades": [10, 12, 15]}
        run = {"better": "less", "grades": [870, 810, 765]}
        self.assertEqual([g.fit_grade(pull, v) for v in (8, 10, 13, 15)], [0, 1, 2, 3])
        self.assertEqual([g.fit_grade(run, v) for v in (900, 860, 800, 760)], [0, 1, 2, 3])
        self.assertIsNone(g.fit_grade({"better": "none", "grades": []}, 70))


class Rules(unittest.TestCase):
    def test_defaults_and_garbage(self):
        self.assertEqual(g.rule_value({}, "duty_cap"), 3)
        self.assertEqual(g.rule_value({"met_share": "мусор"}, "met_share"), 97)
        self.assertEqual(g.rule_value({"duty_cap": 99}, "duty_cap"), 10)  # граница
        self.assertEqual(g.rule_value({"carry_from": "17.30"}, "carry_from"), "17:30")
        self.assertIs(g.rule_value({"duties_on": 0}, "duties_on"), False)

    def test_backplan(self):
        self.assertEqual(g.backplan_steps({}), g.BACKPLAN_STEPS)
        self.assertEqual(g.backplan_steps({"backplan": [[2, "добить"], [10, "старт"], [0, "нет"]]}),
                         [(10, "старт"), (2, "добить")])

    def test_weekdays(self):
        self.assertEqual(g.parse_weekdays("пн-пт"), [0, 1, 2, 3, 4])
        self.assertEqual(g.fmt_weekdays([5, 6]), "выходные")
        self.assertEqual(g.parse_weekdays("пн, ср, пт"), [0, 2, 4])


class Normalize(unittest.TestCase):
    def test_old_system_gets_new_sections(self):
        raw = g.sys_defaults()
        for key in ("rules", "urges", "protocols", "checklists", "fitness", "money", "signals", "campaigns"):
            raw.pop(key)
        out = g.normalize_system(raw)
        self.assertTrue(out["protocols"] and out["checklists"] and out["fitness"]["norms"])
        self.assertEqual(out["money"]["entries"], [])
        self.assertEqual(out["coach"]["weights"]["lists"], 0)  # листы не меняют прошлую боеготовность

    def test_garbage_is_dropped(self):
        raw = g.sys_defaults()
        raw["urges"] = [{"ts": "2026-10-10T10:00:00", "what": "Игры"}, "мусор", {"what": "без времени"}]
        raw["money"]["entries"] = [{"date": "2026-10-10", "sum": 100}, {"date": "плохо", "sum": 1}]
        out = g.normalize_system(raw)
        self.assertEqual(len(out["urges"]), 1)
        self.assertEqual(len(out["money"]["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
