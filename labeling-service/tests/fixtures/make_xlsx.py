"""Генератор тестового Excel тех.нарушений (формат МО: header на строке 8)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COLS = [
    "id_cds_claim", "name_mr", "text_message", "t_ov",
    "d_create", "d_doklad", "d_close",
    "obj_koteln", "obj_ctp", "obj_ts",
]

# 3 CTP-инцидента (1 разрешаемый, 1 с несуществующим номером, 1 дубль id) + 1 котельная (GO)
ROWS = [
    # разрешаемый: ЦТП-1 существует в справочнике фикстуры
    dict(id_cds_claim=1001, name_mr="Тестовск г.о.",
         text_message="утечка на ЦТП-1 по ул. Ленина, без ГВС", t_ov=-10,
         d_create="2026-01-05 10:00", d_doklad="2026-01-05 10:30", d_close="2026-01-05 14:00",
         obj_koteln=0, obj_ctp=1, obj_ts=0),
    # номер, которого нет в справочнике → unresolved
    dict(id_cds_claim=1002, name_mr="Тестовск г.о.",
         text_message="повреждение на ЦТП-999 неизвестный", t_ov=-8,
         d_create="2026-01-06 09:00", d_doklad="2026-01-06 09:20", d_close=None,
         obj_koteln=0, obj_ctp=1, obj_ts=0),
    # дубль id_cds_claim=1001 из «более нового файла» → должен схлопнуться
    dict(id_cds_claim=1001, name_mr="Тестовск г.о.",
         text_message="утечка на ЦТП-1 по ул. Ленина, без ГВС", t_ov=-10,
         d_create="2026-01-05 10:00", d_doklad="2026-01-05 10:30", d_close="2026-01-05 14:00",
         obj_koteln=0, obj_ctp=1, obj_ts=0),
    # GO-событие (котельная) — не размечается
    dict(id_cds_claim=2001, name_mr="Тестовск г.о.",
         text_message="авария на котельной №5", t_ov=-12,
         d_create="2026-01-07 08:00", d_doklad="2026-01-07 08:30", d_close=None,
         obj_koteln=1, obj_ctp=0, obj_ts=0),
]


def write_sample(path: str | Path) -> Path:
    """Пишет xlsx с 8 строками-шапкой перед заголовком (header=8)."""
    df = pd.DataFrame(ROWS)[COLS]
    path = Path(path)
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        # 8 пустых строк-преамбулы, затем таблица с заголовком на 9-й строке (index 8)
        df.to_excel(xl, index=False, startrow=8, sheet_name="Sheet1")
    return path


if __name__ == "__main__":
    p = write_sample("sample_tech.xlsx")
    print("written", p)
