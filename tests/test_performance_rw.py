import json
import sys
import types
import unittest

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias.normalizers import monitoramento_da_observacao
from src.modules.estadias.imports import normalize_lcte_row
from src.modules.estadias.page import _performance_rw_table


class PerformanceRwTest(unittest.TestCase):
    def test_monitoramento_requires_seven_digits(self):
        self.assertEqual(monitoramento_da_observacao("1234567 texto"), "1234567")
        self.assertEqual(monitoramento_da_observacao("12345678"), "")
        self.assertEqual(monitoramento_da_observacao(None), "")

    def test_lcte_import_keeps_monitoramento_separate(self):
        row = normalize_lcte_row({"Observação": "1234567 Observacao restante"}, {"observacao": "Observação"}, {})
        self.assertEqual(row["observacao"], "Observacao restante")
        self.assertEqual(row["monitoramento"], "1234567")

    def test_panel_uses_original_observation_for_existing_result(self):
        cross = pd.DataFrame([{
            "lcte_id": 1, "nf": "746", "placa_norm": "AIW8A04", "motorista": "JOAO",
            "origem": "SANTOS", "destino": "RONDONOPOLIS", "data_emissao_nf": "2026-08-01",
            "chegada_origem": "2026-08-02 10:00:00", "saida_origem": "2026-08-02 20:00:00",
        }])
        observations = pd.DataFrame([{"id": 1, "dados_json": json.dumps({"Observação": "1234567 texto"})}])
        panel = _performance_rw_table(cross, observations)
        self.assertEqual(len(panel), 2)
        self.assertEqual(panel["Tipo"].tolist(), ["ORIGEM", "DESTINO"])
        self.assertEqual(panel["Monitoramento"].tolist(), ["1234567", "1234567"])
        self.assertEqual(panel["Motorista"].tolist(), ["JOAO", "JOAO"])
        self.assertEqual(panel.loc[0, "Chegada Rastreador"], "02/08/2026 10:00")
        self.assertEqual(len(panel.columns), 11)

    def test_saved_monitoramento_survives_missing_lcte(self):
        cross = pd.DataFrame([{"lcte_id": 1, "monitoramento": "7654321"}])
        panel = _performance_rw_table(cross, pd.DataFrame(columns=["id", "dados_json"]))
        self.assertEqual(panel["Monitoramento"].tolist(), ["7654321", "7654321"])


if __name__ == "__main__":
    unittest.main()
