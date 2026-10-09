import unittest

from estadias_app.ots_otd_rules import (
    UNKNOWN,
    avaliar_regras_viagem,
    calcular_otd1,
    calcular_otd2,
    calcular_otd3,
    calcular_ots2,
    calcular_ots3,
)


class OtsOtdRulesTest(unittest.TestCase):
    def setUp(self):
        self.schedule = {
            "previsao_carga": "30/09/2026 12:00",
            "agendamento_carga": "30/09/2026 10:00",
            "data_limite": "01/10/2026",
            "agenda_gfl": "01/10/2026 09:00",
            "data_hora_registro": "30/09/2026 08:00",
        }

    def test_each_rule_passes_across_month_boundary(self):
        self.assertEqual(calcular_ots2(self.schedule), "Dentro do prazo")
        self.assertEqual(calcular_ots3(self.schedule, origem="30/09/2026 09:00"), "Dentro do prazo")
        self.assertEqual(calcular_otd1(self.schedule, emissao_nf="30/09/2026 11:00"), "Dentro do prazo")
        self.assertEqual(calcular_otd2(self.schedule, destino="01/10/2026 08:00"), "Dentro do prazo")
        self.assertEqual(calcular_otd3(self.schedule, destino="01/10/2026 08:00"), "Dentro do prazo")
        self.assertEqual(avaliar_regras_viagem(self.schedule, "30/09/2026 09:00", "01/10/2026 08:00", "30/09/2026 11:00")["Dentro da Regra"], "Sim")

    def test_missing_data_stays_unknown(self):
        result = avaliar_regras_viagem(self.schedule, emissao_nf=None)
        self.assertEqual(result["OTS 3"], UNKNOWN)
        self.assertEqual(result["OTD 1"], UNKNOWN)
        self.assertEqual(result["Dentro da Regra"], UNKNOWN)

    def test_sunday_requires_destination_arrival_that_day(self):
        self.schedule["data_limite"] = "04/10/2026"
        self.assertEqual(calcular_otd2(self.schedule, destino="05/10/2026 00:01"), "Fora do prazo")
        self.assertEqual(calcular_otd3(self.schedule, destino="05/10/2026 00:01"), "Fora do prazo")

    def test_timezone_is_compared_in_brasilia(self):
        self.schedule["data_hora_registro"] = "2026-10-01T01:30:00+00:00"
        self.assertEqual(calcular_otd1(self.schedule, emissao_nf="30/09/2026 22:30"), "Dentro do prazo")


if __name__ == "__main__":
    unittest.main()
