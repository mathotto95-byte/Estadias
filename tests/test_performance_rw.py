import sys
import types
import unittest

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias.normalizers import monitoramento_da_observacao
from src.modules.estadias.imports import normalize_lcte_row


class MonitoringImportTest(unittest.TestCase):
    def test_monitoramento_requires_seven_digits(self):
        self.assertEqual(monitoramento_da_observacao("1234567 texto"), "1234567")
        self.assertEqual(monitoramento_da_observacao("12345678"), "")
        self.assertEqual(monitoramento_da_observacao(None), "")

    def test_lcte_import_keeps_monitoramento_separate(self):
        row = normalize_lcte_row({"Observação": "1234567 Observacao restante"}, {"observacao": "Observação"}, {})
        self.assertEqual(row["observacao"], "Observacao restante")
        self.assertEqual(row["monitoramento"], "1234567")


if __name__ == "__main__":
    unittest.main()
