import unittest
import json
import sys
import types
from io import BytesIO
from unittest.mock import patch

import pandas as pd

from estadias_app.ots_otd import enrich_summary, receive


def backup():
    return {"rows": [{
        "id": 1, "codigo_monitoramento": "1234567", "data_hora_registro": "2026-09-10 08:00:00",
        "previsao_carga": "2026-09-10", "agendamento_carga": "2026-09-10 10:00:00",
        "data_limite": "2026-09-12", "agenda_gfl": "2026-09-12 12:00:00",
    }]}


class DirectOtsOtdTest(unittest.TestCase):
    def test_receive_reuses_estadias_github_token(self):
        payload = {"schema": "ots_otd_backup_v1", "records": 1, "rows": backup()["rows"]}
        github = types.ModuleType("estadias_app.github_backup")
        github.github_settings = lambda: {"token": "existing-token"}
        with patch.dict(sys.modules, {"estadias_app.github_backup": github}), patch("estadias_app.ots_otd.urlopen") as fetch:
            fetch.return_value.__enter__.return_value = BytesIO(json.dumps(payload).encode())
            self.assertEqual(receive(), payload)
            self.assertEqual(fetch.call_args.args[0].get_header("Authorization"), "Bearer existing-token")

    def test_matches_monitoring_nf_plate_and_both_gps_arrivals(self):
        rows = pd.DataFrame([
            {"lcte_id": 1, "Tipo": "ORIGEM", "Notas": "746", "Placa": "AIW8A04", "monitoramento": "1234567", "Chegada Rastreador": "10/09/2026 09:00", "Data Emissao NF": "10/09/2026 11:00"},
            {"lcte_id": 1, "Tipo": "DESTINO", "Notas": "746", "Placa": "AIW8A04", "monitoramento": "1234567", "Chegada Rastreador": "12/09/2026 08:00", "Data Emissao NF": "10/09/2026 11:00"},
        ])
        result = enrich_summary(rows, backup())
        self.assertEqual(result["Correspondência OTS/OTD"].tolist(), ["Exata", "Exata"])
        self.assertEqual(result["OTD 3"].tolist(), ["Dentro do prazo", "Dentro do prazo"])
        self.assertEqual(result["OTD 1"].tolist(), ["Dentro do prazo", "Dentro do prazo"])

    def test_conflicting_monitoring_cannot_borrow_schedule(self):
        rows = pd.DataFrame([
            {"lcte_id": 1, "Notas": "746", "Placa": "AIW8A04", "monitoramento": "1234567"},
            {"lcte_id": 2, "Notas": "746", "Placa": "AIW8A04", "monitoramento": "7654321"},
        ])
        result = enrich_summary(rows, backup())
        self.assertTrue(result["Motivo vínculo OTS/OTD"].str.contains("mais de uma viagem").all())
        self.assertTrue(result["Dentro da Regra"].eq("Sem informação").all())

    def test_missing_gps_does_not_approve_trip(self):
        rows = pd.DataFrame([{"lcte_id": 1, "Notas": "746", "Placa": "AIW8A04", "monitoramento": "1234567", "Data Emissao NF": "10/09/2026"}])
        result = enrich_summary(rows, backup()).iloc[0]
        self.assertEqual(result["OTS 3"], "Sem informação")
        self.assertEqual(result["OTD 3"], "Sem informação")
        self.assertEqual(result["Dentro da Regra"], "Sem informação")

    def test_sunday_requires_gps_on_sunday(self):
        payload = backup()
        payload["rows"][0]["data_limite"] = "2026-09-13"
        rows = pd.DataFrame([{"lcte_id": 1, "Notas": "746", "Placa": "AIW8A04", "monitoramento": "1234567", "Chegada Rastreador Descarga": "14/09/2026 08:00"}])
        result = enrich_summary(rows, payload).iloc[0]
        self.assertEqual(result["OTD 2"], "Fora do prazo")
        self.assertEqual(result["OTD 3"], "Fora do prazo")


if __name__ == "__main__":
    unittest.main()
