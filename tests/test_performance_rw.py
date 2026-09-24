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
            "encontrou_origem": 1, "tempo_origem_min": 600, "estadia_carga_min": 120,
        }])
        observations = pd.DataFrame([{"id": 1, "dados_json": json.dumps({"Observação": "1234567 texto", "Município da cobrança": "Araucária"})}])
        panel = _performance_rw_table(cross, observations)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel["Tipo"].tolist(), ["ORIGEM"])
        self.assertEqual(panel["Status Estadia"].tolist(), ["ESTADIA"])
        self.assertEqual(panel["Monitoramento"].tolist(), ["1234567"])
        self.assertEqual(panel["Município da Cobrança"].tolist(), ["Araucária"])
        self.assertEqual(panel["Motorista"].tolist(), ["JOAO"])
        self.assertEqual(panel.loc[0, "Chegada Rastreador"], "02/08/2026 10:00")
        self.assertEqual(len(panel.columns), 12)

    def test_saved_monitoramento_survives_missing_lcte(self):
        cross = pd.DataFrame([{"lcte_id": 1, "monitoramento": "7654321", "encontrou_destino": 1, "tempo_destino_min": 90, "estadia_descarga_min": 30}])
        panel = _performance_rw_table(cross, pd.DataFrame(columns=["id", "dados_json"]))
        self.assertEqual(panel["Monitoramento"].tolist(), ["7654321"])
        self.assertEqual(panel["Município da Cobrança"].tolist(), [""])

    def test_without_estadia_is_not_exported(self):
        cross = pd.DataFrame([{"lcte_id": 2, "encontrou_origem": 1, "tempo_origem_min": 90, "estadia_carga_min": 0}])
        panel = _performance_rw_table(cross, pd.DataFrame(columns=["id", "dados_json"]))
        self.assertTrue(panel.empty)
        self.assertIn("Município da Cobrança", panel.columns)


if __name__ == "__main__":
    unittest.main()
