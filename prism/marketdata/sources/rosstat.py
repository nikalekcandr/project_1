"""Росстат: индекс потребительских цен и календарь публикаций.

Хранятся обе версии значения — первая публикация и уточнённая: контракт
указывает, какая применяется.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def parse_cpi_csv(text: str) -> dict[str, Any]:
    """CSV: month,mom_first,mom_revised,published — м/м темпы в процентах к предыдущему месяцу.

    Возвращает данные датасета ``cpi_ru``: уровни индекса (база = 100 в первом
    месяце) для первой и уточнённой публикации.
    """
    rows = list(csv.DictReader(io.StringIO(text)))
    first, revised, pub = {}, {}, {}
    lvl_f = lvl_r = 100.0
    for i, r in enumerate(rows):
        m = r["month"]
        if i > 0:
            lvl_f = lvl_r_prev * (1 + float(r["mom_first"]) / 100.0)
            lvl_r = lvl_r_prev * (1 + float(r.get("mom_revised") or r["mom_first"]) / 100.0)
        first[m], revised[m] = round(lvl_f, 6), round(lvl_r, 6)
        pub[m] = r.get("published", "")
        lvl_r_prev = lvl_r
    return {"index_first": first, "index_revised": revised, "published": pub}
