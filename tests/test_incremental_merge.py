import sys
import types
import unittest

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias.service import _merge_incremental_rows


class IncrementalMergeTest(unittest.TestCase):
    def test_scoped_update_preserves_other_trips_and_conclusions(self):
        existing = pd.DataFrame([
            {"lcte_id": 1, "painel_atual": "CONCLUIDOS", "concluido": 1, "nf": "old"},
            {"lcte_id": 2, "painel_atual": "ESTADIAS", "concluido": 0, "nf": "other"},
        ])
        recalculated = [
            {"lcte_id": 1, "painel_atual": "ESTADIAS", "concluido": 0, "nf": "new"},
            {"lcte_id": 3, "painel_atual": "ESTADIAS", "concluido": 0, "nf": "added"},
        ]
        rows, to_save, ids, counts = _merge_incremental_rows(existing, recalculated, True)
        self.assertEqual([row["lcte_id"] for row in rows], [2, 1, 3])
        self.assertEqual([row["lcte_id"] for row in to_save], [1, 3])
        self.assertEqual(ids, {1, 3})
        self.assertEqual(rows[1]["nf"], "old")
        self.assertEqual(counts, {"registros_novos": 1, "registros_atualizados": 0, "concluidos_preservados": 1})

    def test_full_update_drops_missing_trip(self):
        existing = pd.DataFrame([{"lcte_id": 1, "nf": "old"}, {"lcte_id": 2, "nf": "other"}])
        rows, to_save, ids, counts = _merge_incremental_rows(existing, [{"lcte_id": 1, "nf": "new"}], False)
        self.assertEqual(rows, [{"lcte_id": 1, "nf": "new"}])
        self.assertEqual(to_save, [])
        self.assertEqual(ids, {1})
        self.assertEqual(counts["registros_atualizados"], 1)


if __name__ == "__main__":
    unittest.main()
