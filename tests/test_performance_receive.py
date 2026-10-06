import unittest
import pandas as pd
from estadias_app.performance import attach, validate, RULES, enrich_summary, SCHEDULE_FIELDS


class ReceiveTests(unittest.TestCase):
    def test_exact_missing_stale_and_duplicates(self):
        row = {"Nota Fiscal": "1", "Placa": "ABC1D23", "Atendeu todas as regras": "Sim", "Correspondência Estadias": "Exata", "Chegada na Origem": "2026-10-01 10:00", "Chegada no Destino": "", **dict.fromkeys(RULES, "Dentro do prazo")}
        row.update(dict(zip(SCHEDULE_FIELDS, ["01/10/2026", "01/10/2026 10:00", "02/10/2026", "02/10/2026 12:00"])))
        payload = {"schema": "performance_results_v1", "analyzed_at": "2026-10-02T10:00:00-03:00", "sources": {}, "rows": [row]}
        local = pd.DataFrame([{"nf": "001", "placa_norm": "ABC-1D23", "chegada_origem": "2026-10-01 10:00:00", "lcte_id": 7}])
        self.assertEqual(attach(local, payload).iloc[0]["Atendeu todas as regras"], "Sim")
        summary = pd.DataFrame([{"Notas": "001", "Placa": "ABC-1D23", "Tipo": "CARGA"}, {"Notas": "001", "Placa": "ABC-1D23", "Tipo": "DESCARGA"}])
        enriched = enrich_summary(summary, local, payload)
        self.assertEqual(len(enriched), 2)
        for field in SCHEDULE_FIELDS:
            self.assertEqual(enriched[field].tolist(), [row[field]] * 2)
        self.assertEqual(enriched["Dentro da Regra"].tolist(), ["Sim", "Sim"])
        self.assertEqual(enrich_summary(summary, local, None).iloc[0]["Dentro da Regra"], "Sem informação")
        local.loc[0, "nf"] = "2"
        self.assertEqual(attach(local, payload).iloc[0]["Correspondência"], "Sem correspondência")
        local.loc[0, "nf"] = "1"
        local.loc[0, "chegada_origem"] = "2026-10-01 11:00"
        self.assertEqual(attach(local, payload).iloc[0]["Atendeu todas as regras"], "Sem informação")
        self.assertEqual(enrich_summary(summary, local, payload).iloc[0]["Agenda GFL"], "")
        payload["rows"].append(row)
        with self.assertRaises(ValueError):
            validate(payload)
