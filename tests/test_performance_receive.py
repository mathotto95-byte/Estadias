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
        partial = enrich_summary(summary, local, payload).iloc[0]
        self.assertEqual(partial["Agenda GFL"], row["Agenda GFL"])
        self.assertEqual(partial["OTS 2"], "Dentro do prazo")
        self.assertEqual(partial["OTS 3"], "Sem informação")
        self.assertIn("Chegada GPS alterada", partial["Motivo vínculo PerformanceRW"])
        payload["rows"].append(row)
        with self.assertRaises(ValueError):
            validate(payload)

    def test_compatible_duplicate_trip_retains_rules(self):
        row = {"Nota Fiscal": "123", "Placa": "ABC1D23", "Atendeu todas as regras": "Sim",
               "Correspondência Estadias": "NF + placa exata; viagem duplicada compatível",
               "Chegada na Origem": "2026-10-01 10:00", "Chegada no Destino": "2026-10-03 12:00",
               **dict.fromkeys(RULES, "Dentro do prazo")}
        payload = {"schema": "performance_results_v1", "analyzed_at": "2026-10-04T10:00:00-03:00", "sources": {}, "rows": [row]}
        cross = pd.DataFrame([
            {"lcte_id": 1, "nf": "123", "placa_norm": "ABC1D23", "chave_viagem": "VIAGEM-1", "chegada_origem": "2026-10-01 10:00", "chegada_destino": "2026-10-03 12:00"},
            {"lcte_id": 2, "nf": "123", "placa_norm": "ABC1D23", "chave_viagem": "VIAGEM-1", "chegada_origem": "2026-10-01 10:00", "chegada_destino": "2026-10-03 12:00"},
        ])
        received = attach(cross, payload)
        self.assertEqual(received.iloc[0]["OTS 2"], "Dentro do prazo")
        summary = pd.DataFrame([{"Notas": "123", "Placa": "ABC1D23"}])
        self.assertEqual(enrich_summary(summary, cross, payload).iloc[0]["OTD 3"], "Dentro do prazo")
        cross.loc[1, "chave_viagem"] = "VIAGEM-2"
        self.assertEqual(attach(cross, payload).iloc[0]["OTS 2"], "Sem informação")

    def test_same_trip_with_changed_destination_keeps_only_current_rules(self):
        row = {"Nota Fiscal": "123", "Placa": "ABC1D23", "Atendeu todas as regras": "Sim",
               "Correspondência Estadias": "Exata", "Chegada na Origem": "2026-10-01 10:00",
               "Chegada no Destino": "2026-10-03 12:00", **dict.fromkeys(RULES, "Dentro do prazo")}
        payload = {"schema": "performance_results_v1", "analyzed_at": "2026-10-04T10:00:00-03:00", "sources": {}, "rows": [row]}
        cross = pd.DataFrame([
            {"lcte_id": 1, "nf": "123", "placa_norm": "ABC1D23", "chave_viagem": "VIAGEM-1", "chegada_origem": "2026-10-01 10:00", "chegada_destino": "2026-10-03 12:00"},
            {"lcte_id": 2, "nf": "123", "placa_norm": "ABC1D23", "chave_viagem": "VIAGEM-1", "chegada_origem": "2026-10-01 10:00", "chegada_destino": "2026-10-03 13:00"},
        ])
        result = attach(cross, payload).set_index("lcte_id")
        self.assertEqual(result.loc["1", "Correspondência"], "Exata")
        self.assertEqual(result.loc["2", "Correspondência"], "Parcial")
        self.assertEqual(result.loc["2", "OTS 2"], "Dentro do prazo")
        self.assertEqual(result.loc["2", "OTS 3"], "Dentro do prazo")
        self.assertEqual(result.loc["2", "OTD 3"], "Sem informação")
        summary = pd.DataFrame([{"lcte_id": 2, "Notas": "123", "Placa": "ABC1D23"}])
        self.assertEqual(enrich_summary(summary, cross, payload).iloc[0]["OTD 3"], "Sem informação")
