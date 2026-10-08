import sqlite3
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

streamlit = types.ModuleType("streamlit")
streamlit.cache_data = lambda **kwargs: lambda func: func
sys.modules.setdefault("streamlit", streamlit)

from src.modules.estadias import repository
from src.database.connection import DatabaseConfig, DbConnection
from src.database.migrations import create_modular_tables
from src.modules.estadias.page import _analysis_deadline_status, _apply_summary_filters, _apply_validation_card, _build_cross_summary_table, _build_trip_summary_table, _charge_rule_status, _conference_suggestion, _apply_conference, _apply_situation_card, _configured_columns, _gps_permanence_report, _gps_verification_table
from estadias_app import github_backup


class AnalysisDeadlineTest(unittest.TestCase):
    def test_gps_verification_starts_from_every_lcte_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gps.sqlite"
            with closing(sqlite3.connect(path)) as raw:
                raw.row_factory = sqlite3.Row
                create_modular_tables(DbConnection(raw, "sqlite"))
                raw.execute("insert into mod_estadias_lcte_normalizada (id, nf, placa_norm) values (1, '100', 'ABC1234'), (2, '200', 'DEF5678'), (3, '300', 'GHI9012')")
                raw.execute("insert into mod_estadias_cruzamento_inicial (lcte_id, encontrou_rastreador, encontrou_origem, encontrou_destino) values (1, 1, 1, 1), (2, 0, 0, 0)")
                raw.execute("insert into mod_estadias_posicoes_resultado (lcte_id, tipo_estadia) values (1, 'ORIGEM')")
                raw.commit()
            config = DatabaseConfig(db_type="sqlite", sqlite_path=path)
            with patch("src.database.connection.get_database_config", return_value=config):
                result = _gps_verification_table(repository.read_gps_verification())
        by_id = result.set_index("lcte_id")
        self.assertEqual(len(result), 3)
        self.assertEqual(by_id.at[1, "Situação GPS"], "Carga e descarga")
        self.assertEqual(by_id.at[1, "posicoes_carga"], 1)
        self.assertEqual(by_id.at[2, "Situação GPS"], "Sem GPS no cálculo")
        self.assertEqual(by_id.at[3, "Situação GPS"], "Não calculada")

    def test_gps_verification_distinguishes_partial_locations(self):
        rows = pd.DataFrame([
            {"resultado_id": 1, "encontrou_rastreador": 1, "encontrou_origem": 1, "encontrou_destino": 0, "tempo_origem_min": 1440, "tempo_destino_min": None, "posicoes_carga": 2, "posicoes_descarga": 0},
            {"resultado_id": 2, "encontrou_rastreador": 1, "encontrou_origem": 0, "encontrou_destino": 1, "tempo_origem_min": None, "tempo_destino_min": 1441, "posicoes_carga": 0, "posicoes_descarga": 1},
            {"resultado_id": 3, "encontrou_rastreador": 1, "encontrou_origem": 0, "encontrou_destino": 0, "tempo_origem_min": None, "tempo_destino_min": None, "posicoes_carga": 0, "posicoes_descarga": 0},
        ])
        verified = _gps_verification_table(rows)
        self.assertEqual(verified["Situação GPS"].tolist(), ["Só carga", "Só descarga", "GPS sem local identificado"])
        self.assertEqual(verified["Evidência disponível"].tolist(), ["Posições resumidas salvas", "Posições resumidas salvas", "Somente resultado"])
        self.assertEqual(verified["Tempo total GPS"].tolist()[:2], ["24:00", "24:01"])
        self.assertTrue(pd.isna(verified.iloc[2]["Tempo total GPS (min)"]))
        self.assertEqual(verified[verified["Tempo total GPS (min)"].gt(1440)].index.tolist(), [1])

    def test_save_model_button_persists_selected_columns(self):
        ui = MagicMock()
        ui.session_state = {}
        apply_button, save_button = MagicMock(), MagicMock()
        ui.columns.return_value = (apply_button, save_button)
        save_button.form_submit_button.return_value = True

        def select_columns(_label, _options, key):
            ui.session_state[key] = ["Placa", "Origem"]
            return ui.session_state[key]

        ui.multiselect.side_effect = select_columns
        with patch("src.modules.estadias.page.st", ui), patch("src.modules.estadias.page.read_preferencia_colunas", return_value=[]) as read, patch("src.modules.estadias.page.save_preferencia_colunas") as save:
            selected = _configured_columns("VIAGENS", pd.DataFrame(columns=["Placa", "Origem", "Destino"]), "matheus")
        self.assertEqual(selected, ["Placa", "Origem"])
        read.assert_called_once_with("matheus", "VIAGENS")
        save.assert_called_once_with("matheus", "VIAGENS", ["Placa", "Origem"])
        self.assertIn("estadias_cross_columns_VIAGENS_matheus", ui.session_state)

    def test_column_preference_saves_per_user_and_rolls_back_on_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preferences.sqlite"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("create table mod_estadias_preferencias_colunas (id integer primary key autoincrement, usuario text, painel text, colunas_json text, updated_at text)")
            config = DatabaseConfig(db_type="sqlite", sqlite_path=path)
            with patch("src.database.connection.get_database_config", return_value=config):
                repository.save_preferencia_colunas("matheus", "VIAGENS", ["Placa", "Origem"])
                self.assertEqual(repository.read_preferencia_colunas("matheus", "VIAGENS"), ["Placa", "Origem"])
                self.assertEqual(repository.read_preferencia_colunas("outro", "VIAGENS"), [])
                repository.save_preferencia_colunas("matheus", "VIAGENS", ["Destino"])
                self.assertEqual(repository.read_preferencia_colunas("matheus", "VIAGENS"), ["Destino"])
                with closing(sqlite3.connect(path)) as conn:
                    self.assertEqual(conn.execute("select count(*) from mod_estadias_preferencias_colunas").fetchone()[0], 1)
                    conn.execute("create trigger prevent_preference_insert before insert on mod_estadias_preferencias_colunas begin select raise(abort, 'blocked'); end")
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.save_preferencia_colunas("matheus", "VIAGENS", ["Notas"])
                self.assertEqual(repository.read_preferencia_colunas("matheus", "VIAGENS"), ["Destino"])

    def test_gps_report_keeps_loading_and_unloading_on_one_filtered_row(self):
        trips = pd.DataFrame([{"lcte_id": 2, "Notas": "456", "Placa": "ABC1234", "Chegada Rastreador Carga": "01/10/2026 08:00", "Tempo Rastreador Carga": "26:00", "Chegada Rastreador Descarga": "03/10/2026 09:00", "Tempo Rastreador Descarga": "28:00"}])
        cross = pd.DataFrame([{"lcte_id": 1, "pontos_origem": 99}, {"lcte_id": 2, "pontos_origem": 12, "pontos_destino": 16, "referencias_visitadas_origem": "Patio A", "franquia_carga_min": 1440}])
        report = _gps_permanence_report(trips, cross)
        self.assertEqual(len(report), 1)
        self.assertEqual(report.iloc[0]["Notas"], "456")
        self.assertEqual(report.iloc[0]["Pontos GPS Carga"], 12)
        self.assertEqual(report.iloc[0]["Pontos GPS Descarga"], 16)
        self.assertEqual(report.iloc[0]["Referências visitadas Carga"], "Patio A")
        self.assertLess(report.columns.get_loc("Tempo Rastreador Carga"), report.columns.get_loc("Chegada Rastreador Descarga"))

    def test_charge_rule_uses_only_ots_2_and_3(self):
        self.assertEqual(_charge_rule_status(pd.Series({"OTS 2": "Dentro do prazo", "OTS 3": "Dentro do prazo", "OTD 1": "Fora do prazo"})), "Sim")
        self.assertEqual(_charge_rule_status(pd.Series({"OTS 2": "Fora do prazo", "OTS 3": "Dentro do prazo"})), "Não")
        self.assertEqual(_charge_rule_status(pd.Series({"OTS 2": "Dentro do prazo", "OTS 3": "Sem informação"})), "Sem informação")

    def test_cards_filter_combined_trip_rows(self):
        trips = pd.DataFrame([
            {"lcte_id": 1, "encontrou_rastreador": 1, "Status Estadia Carga": "ESTADIA", "Status Estadia Descarga": "PENDENTE", "Conferência Carga": "VALIDA", "Conferência Descarga": "A CONFERIR", "Status": "PENDENTE"},
            {"lcte_id": 2, "encontrou_rastreador": 1, "Status Estadia Carga": "SEM ESTADIA", "Status Estadia Descarga": "ESTADIA", "Conferência Carga": "INVALIDA", "Conferência Descarga": "A CONFERIR", "Status": "CONCLUIDO"},
            {"lcte_id": 3, "encontrou_rastreador": 0, "Status Estadia Carga": "PENDENTE", "Status Estadia Descarga": "PENDENTE", "Conferência Carga": "A CONFERIR", "Conferência Descarga": "A CONFERIR", "Status": "PENDENTE"},
        ])
        self.assertEqual(_apply_situation_card(trips, "ESTADIA")["lcte_id"].tolist(), [1, 2])
        self.assertEqual(_apply_situation_card(trips, "VALIDA")["lcte_id"].tolist(), [1])
        self.assertEqual(_apply_situation_card(trips, "INVALIDA")["lcte_id"].tolist(), [2])
        self.assertEqual(_apply_situation_card(trips, "PENDENTE")["lcte_id"].tolist(), [1, 3])
        self.assertEqual(_apply_situation_card(trips, "CONCLUIDO")["lcte_id"].tolist(), [2])
        self.assertEqual(_apply_validation_card(_apply_situation_card(trips, "ESTADIA"), "RASTREADOR")["lcte_id"].tolist(), [1, 2])

    def test_trip_summary_keeps_both_stays_on_one_line(self):
        lines = pd.DataFrame([
            {"lcte_id": 1, "Tipo": "ORIGEM", "Notas": "123", "Placa": "ABC1234", "Status": "ESTADIA", "Estadia": "Estadia", "Status Estadia": "ESTADIA", "Conferência": "VALIDA", "Motivo não validada": "", "Motivo conferência": "", "Sem tratativa": False, "Chegada Rastreador": "01/10/2026 10:00", "Saida Rastreador": "02/10/2026 10:00", "Tempo Rastreador": "24:00", "Chegada Control": "", "Saida Control": "", "Tempo Control": "", "Diferenca": "", "Motivo": "", "Concluir": "Concluir", "data_inicio_viagem_referencia": "2026-10-01"},
            {"lcte_id": 1, "Tipo": "DESTINO", "Notas": "123", "Placa": "ABC1234", "Status": "PENDENTE", "Estadia": "Pendente", "Status Estadia": "PENDENTE", "Conferência": "INVALIDA", "Motivo não validada": "Abaixo de 24h", "Motivo conferência": "", "Sem tratativa": True, "Chegada Rastreador": "03/10/2026 10:00", "Saida Rastreador": "03/10/2026 12:00", "Tempo Rastreador": "02:00", "Chegada Control": "", "Saida Control": "", "Tempo Control": "", "Diferenca": "", "Motivo": "", "Concluir": "Concluir", "data_inicio_viagem_referencia": "2026-10-01"},
        ])
        trips = _build_trip_summary_table(lines)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips.iloc[0]["Chegada Rastreador Carga"], "01/10/2026 10:00")
        self.assertEqual(trips.iloc[0]["Chegada Rastreador Descarga"], "03/10/2026 10:00")
        self.assertEqual(len(_apply_situation_card(trips, "INVALIDA")), 1)
        self.assertEqual(len(_apply_summary_filters(trips, {"tratativa": "Ativos", "conferencia": "VALIDA"})), 1)

    def test_write_marks_backup_check_without_database_scan(self):
        state = {}
        with patch.object(repository.st, "cache_data", create=True) as cache, patch.object(repository.st, "session_state", state, create=True):
            repository._invalidate_read_cache()
        cache.clear.assert_called_once()
        self.assertTrue(state["estadias_data_changed"])

    def test_existing_analysis_dates_migrate_once(self):
        with sqlite3.connect(":memory:") as raw:
            raw.row_factory = sqlite3.Row
            conn = DbConnection(raw, "sqlite")
            create_modular_tables(conn)
            raw.execute(f"drop table {repository.ANALYSIS_TABLE}")
            raw.execute(f"insert into {repository.CROSS_TABLE} (lcte_id, nf, analise_enviada_em) values (1, '123', '2026-09-29T10:00:00')")
            create_modular_tables(conn)
            dates = raw.execute(f"select analise_enviada_em from {repository.ANALYSIS_TABLE} where lcte_id = 1").fetchone()[0]
            legacy = raw.execute(f"select analise_enviada_em from {repository.CROSS_TABLE} where lcte_id = 1").fetchone()[0]
            create_modular_tables(conn)
            self.assertEqual(raw.execute(f"select count(*) from {repository.ANALYSIS_TABLE}").fetchone()[0], 1)
        self.assertEqual(dates, "2026-09-29T10:00:00")
        self.assertEqual(legacy, "")

    def test_existing_analysis_table_gains_conference_columns(self):
        with sqlite3.connect(":memory:") as raw:
            raw.row_factory = sqlite3.Row
            raw.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text)")
            raw.execute(f"insert into {repository.ANALYSIS_TABLE} values (1, '123', '2026-09-29T10:00:00', '')")
            create_modular_tables(DbConnection(raw, "sqlite"))
            columns = {row[1] for row in raw.execute(f"pragma table_info({repository.ANALYSIS_TABLE})")}
            saved = raw.execute(f"select nf, analise_enviada_em from {repository.ANALYSIS_TABLE} where lcte_id = 1").fetchone()
        self.assertTrue({"conferencia_origem", "conferencia_destino", "motivo_conferencia_origem", "motivo_conferencia_destino"}.issubset(columns))
        self.assertEqual(tuple(saved), ("123", "2026-09-29T10:00:00"))

    def test_fifteen_day_deadline_and_response(self):
        sent = "2026-09-29T10:00:00"
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 9)), ("14/10/2026 10:00", "Aguardando resposta"))
        self.assertEqual(_analysis_deadline_status(sent, "", datetime(2026, 10, 14, 11))[1], "Prazo vencido")
        self.assertEqual(_analysis_deadline_status(sent, "2026-10-15T12:00:00", datetime(2026, 10, 16))[1], "Respondida")

    def test_marking_keeps_original_sent_time(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_analysis_flags(1, True, False, "tester")
                sent = conn.execute(f"select analise_enviada_em from {repository.ANALYSIS_TABLE}").fetchone()[0]
                repository.save_analysis_flags(1, True, True, "tester")
                stored = conn.execute(f"select analise_enviada_em, analise_respondida_em from {repository.ANALYSIS_TABLE}").fetchone()
        self.assertEqual(stored[0], sent)
        self.assertTrue(stored[1])

    def test_separate_backup_contains_only_invoice_and_mark_dates(self):
        rows = pd.DataFrame([{"nf": "12345", "analise_enviada_em": "2026-09-29T10:00:00", "analise_respondida_em": "", "sem_tratativa_origem": 1, "sem_tratativa_destino": 0, "conferencia_origem": "INVALIDA", "motivo_conferencia_origem": "Prazo", "conferencia_destino": "", "motivo_conferencia_destino": ""}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "read_sql", return_value=rows), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_upload_bytes") as upload:
            result = github_backup.backup_analysis_marks_to_github()
        self.assertEqual(result["status"], "SUCESSO")
        self.assertEqual(upload.call_args.args[1], "backups/estadias_analises.csv")
        self.assertEqual(upload.call_args.args[2].decode("utf-8-sig"), "Nota fiscal,Enviada em,Respondida em,Sem tratativa origem,Sem tratativa destino,Conferencia origem,Motivo origem,Conferencia destino,Motivo destino\r\n12345,2026-09-29T10:00:00,,1,0,INVALIDA,Prazo,,\r\n")

    def test_manual_verdict_preserves_other_location_and_analysis_dates(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, conferencia_origem text, conferencia_destino text, motivo_conferencia_origem text, motivo_conferencia_destino text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            conn.execute(f"insert into {repository.ANALYSIS_TABLE} (lcte_id, nf, analise_enviada_em, conferencia_destino) values (1, '123', '2026-09-29T10:00:00', 'VALIDA')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_manual_conferences([(1, "ORIGEM", "INVALIDA", "Menos de 24 horas")], "tester")
            result = conn.execute(f"select analise_enviada_em, conferencia_origem, conferencia_destino from {repository.ANALYSIS_TABLE}").fetchone()
        self.assertEqual(result, ("2026-09-29T10:00:00", "INVALIDA", "VALIDA"))

    def test_destination_deadline_suggestion_validates_after_24_hours(self):
        base = {"Status Estadia": "ESTADIA", "Tipo": "DESTINO", "Data Limite": "19/09/2026", "Chegada Rastreador": "20/09/2026 10:00", "Saida Rastreador": "21/09/2026 08:00"}
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        base["Saida Rastreador"] = "21/09/2026 23:00"
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "VALIDA")
        base.update({"Chegada Rastreador": "18/09/2026 10:00", "Saida Rastreador": "19/09/2026 12:00"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        base["Data Limite"] = "09/05/2026"
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "A CONFERIR")
        # Arrival after the calendar limit starts the eligible period at GPS arrival.
        base.update({"Data Limite": "06/09/2026", "Chegada Rastreador": "07/09/2026 08:13", "Saida Rastreador": "08/09/2026 10:07"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "VALIDA")

    def test_origin_uses_appointment_to_gps_departure_with_invoice_evidence(self):
        base = {"Status Estadia": "ESTADIA", "Tipo": "ORIGEM", "Agendamento de Carga": "09/09/2026 20:00",
                "Chegada Rastreador": "08/09/2026 14:19", "Saida Rastreador": "09/09/2026 15:10", "Data Emissao NF": "09/09/2026 14:18"}
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        # NF 391240 was corrected by the confirmed appointment-to-departure rule.
        base.update({"Agendamento de Carga": "05/09/2026 05:00", "Chegada Rastreador": "04/09/2026 12:19", "Saida Rastreador": "05/09/2026 14:29", "Data Emissao NF": "05/09/2026 12:19"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        base.update({"Agendamento de Carga": "17/09/2026 22:00", "Chegada Rastreador": "17/09/2026 05:33", "Saida Rastreador": "18/09/2026 12:42", "Data Emissao NF": "18/09/2026 05:32"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        corrected_origins = [
            ("17/09/2026 11:00", "16/09/2026 13:11", "17/09/2026 14:28", "17/09/2026 13:11"),
            ("03/09/2026 17:30", "02/09/2026 18:49", "04/09/2026 06:11", "03/09/2026 18:46"),
            ("23/09/2026 12:00", "23/09/2026 07:01", "24/09/2026 07:31", "24/09/2026 05:50"),
        ]
        for appointment, arrival, departure, invoice in corrected_origins:
            base.update({"Agendamento de Carga": appointment, "Chegada Rastreador": arrival,
                         "Saida Rastreador": departure, "Data Emissao NF": invoice})
            self.assertEqual(_conference_suggestion(pd.Series(base))[0], "INVALIDA")
        base.update({"Agendamento de Carga": "15/09/2026 14:00", "Chegada Rastreador": "15/09/2026 14:00", "Saida Rastreador": "16/09/2026 15:00", "Data Emissao NF": "16/09/2026 13:46"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "VALIDA")
        base.update({"Agendamento de Carga": "15/09/2026 14:00", "Chegada Rastreador": "16/09/2026 09:42", "Saida Rastreador": "17/09/2026 10:23", "Data Emissao NF": "17/09/2026 09:18"})
        self.assertEqual(_conference_suggestion(pd.Series(base))[0], "A CONFERIR")

    def test_manual_verdict_takes_precedence_over_suggestion(self):
        row = pd.DataFrame([{"Status Estadia": "ESTADIA", "Tipo": "DESTINO", "Data Limite": "19/09/2026",
                             "Chegada Rastreador": "20/09/2026 10:00", "Saida Rastreador": "21/09/2026 08:00",
                             "Conferência manual": "VALIDA", "Motivo manual": "Comprovante conferido"}])
        result = _apply_conference(row)
        self.assertEqual((result.at[0, "Conferência"], result.at[0, "Motivo conferência"]), ("VALIDA", "Comprovante conferido"))
        self.assertEqual(result.at[0, "Motivo não validada"], "")

    def test_gps_stay_explains_invalid_and_pending_conference(self):
        rows = pd.DataFrame([
            {"Status Estadia": "ESTADIA", "Tipo": "ORIGEM", "Agendamento de Carga": "05/09/2026 05:00",
             "Chegada Rastreador": "04/09/2026 12:19", "Saida Rastreador": "05/09/2026 14:29",
             "Data Emissao NF": "05/09/2026 12:19"},
            {"Status Estadia": "ESTADIA", "Tipo": "DESTINO", "Chegada Rastreador": "20/09/2026 10:00",
             "Saida Rastreador": "21/09/2026 23:00", "Data Limite": "19/09/2026"},
            {"Status Estadia": "ESTADIA", "Tipo": "DESTINO", "Chegada Rastreador": "20/09/2026 10:00",
             "Saida Rastreador": "21/09/2026 23:00", "Data Limite": ""},
        ])
        result = _apply_conference(rows)
        self.assertEqual(result["Conferência"].tolist(), ["INVALIDA", "VALIDA", "A CONFERIR"])
        self.assertIn("09:29", result.at[0, "Motivo não validada"])
        self.assertIn("14:31", result.at[0, "Motivo não validada"])
        self.assertEqual(result.at[1, "Motivo não validada"], "")
        self.assertIn("data limite", result.at[2, "Motivo não validada"])
        self.assertTrue(result["Motivo conferência"].eq("").all())

    def test_no_treatment_is_per_location_and_can_be_undone(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, sem_tratativa_origem integer default 0, sem_tratativa_destino integer default 0, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "registrar_status_evento"), patch.object(repository, "_invalidate_read_cache"):
                repository.save_no_treatment_flag(1, "ORIGEM", True, "tester")
                flags = conn.execute(f"select sem_tratativa_origem, sem_tratativa_destino from {repository.ANALYSIS_TABLE}").fetchone()
                repository.save_no_treatment_flag(1, "ORIGEM", False, "tester")
                undone = conn.execute(f"select sem_tratativa_origem from {repository.ANALYSIS_TABLE}").fetchone()[0]
        self.assertEqual(flags, (1, 0))
        self.assertEqual(undone, 0)

    def test_no_treatment_hides_only_marked_line(self):
        cross = pd.DataFrame([{"lcte_id": 1, "nf": "123", "placa_norm": "ABC1234", "encontrou_origem": 1, "encontrou_destino": 1,
                               "tempo_origem_min": 1500, "tempo_destino_min": 1500, "estadia_carga_min": 60, "estadia_descarga_min": 60,
                               "sem_tratativa_origem": 1, "sem_tratativa_destino": 0}])
        summary = _build_cross_summary_table(cross)
        self.assertEqual(_apply_summary_filters(summary, {"tratativa": "Ativos"})["Tipo"].tolist(), ["DESTINO"])
        self.assertEqual(_apply_summary_filters(summary, {"tratativa": "Sem tratativa"})["Tipo"].tolist(), ["ORIGEM"])

    def test_analysis_backup_runs_at_19_brasilia_time(self):
        before = datetime(2026, 9, 29, 18, 30)
        after = datetime(2026, 9, 29, 19, 1)
        self.assertEqual(github_backup._seconds_until_analysis_backup(before, None), 1800)
        self.assertEqual(github_backup._seconds_until_analysis_backup(after, None), 0)
        self.assertGreater(github_backup._seconds_until_analysis_backup(after, after.date()), 23 * 3600)

    def test_backup_branch_is_separate_from_deployed_main(self):
        with patch.dict(os.environ, {"GITHUB_BRANCH": "main"}, clear=True):
            self.assertEqual(github_backup.github_settings()["branch"], "backup-data")

    def test_receive_marks_skips_ambiguous_invoices(self):
        csv_backup = "Nota fiscal,Enviada em,Respondida em\n123,2026-09-29T10:00:00,\n456,2026-09-29T11:00:00,\n"
        current = pd.DataFrame([
            {"lcte_id": 1, "nf": "123", "analise_enviada_em": None, "analise_respondida_em": None},
            {"lcte_id": 2, "nf": "456", "analise_enviada_em": "", "analise_respondida_em": ""},
            {"lcte_id": 3, "nf": "456", "analise_enviada_em": "", "analise_respondida_em": ""},
        ])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_download_text", return_value=csv_backup), patch.object(github_backup, "read_sql", return_value=current), patch.object(github_backup, "restore_analysis_dates", return_value=1) as restore:
            result = github_backup.restore_analysis_marks_from_github("tester", dry_run=False)
        self.assertEqual((result["restored"], result["ambiguous"]), (1, 1))
        restore.assert_called_once_with([(1, "2026-09-29T10:00:00", "")], "tester")

    def test_receive_no_treatment_without_analysis_dates(self):
        csv_backup = "Nota fiscal,Enviada em,Respondida em,Sem tratativa origem,Sem tratativa destino\n123,,,1,0\n"
        current = pd.DataFrame([{"lcte_id": 1, "nf": "123", "analise_enviada_em": None, "analise_respondida_em": None,
                                 "sem_tratativa_origem": 0, "sem_tratativa_destino": 0}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_download_text", return_value=csv_backup), patch.object(github_backup, "read_sql", return_value=current), patch.object(github_backup, "save_no_treatment_flag") as save:
            result = github_backup.restore_analysis_marks_from_github("tester", dry_run=False)
        self.assertEqual((result["ready"], result["restored"]), (1, 1))
        save.assert_called_once_with(1, "ORIGEM", True, "tester")

    def test_receive_manual_conference_without_overwriting_existing_verdict(self):
        csv_backup = "Nota fiscal,Enviada em,Respondida em,Sem tratativa origem,Sem tratativa destino,Conferencia origem,Motivo origem,Conferencia destino,Motivo destino\n123,,,0,0,INVALIDA,Menos de 24 horas,VALIDA,Comprovante\n"
        current = pd.DataFrame([{"lcte_id": 1, "nf": "123", "analise_enviada_em": "", "analise_respondida_em": "",
                                 "sem_tratativa_origem": 0, "sem_tratativa_destino": 0,
                                 "conferencia_origem": "", "motivo_conferencia_origem": "",
                                 "conferencia_destino": "INVALIDA", "motivo_conferencia_destino": "Revisado"}])
        with patch.object(github_backup, "github_backup_configured", return_value=True), patch.object(github_backup, "github_settings", return_value={}), patch.object(github_backup, "_download_text", return_value=csv_backup), patch.object(github_backup, "read_sql", return_value=current), patch.object(github_backup, "save_manual_conferences") as save:
            result = github_backup.restore_analysis_marks_from_github("tester", dry_run=False)
        self.assertEqual(result["restored"], 1)
        save.assert_called_once_with([(1, "ORIGEM", "INVALIDA", "Menos de 24 horas")], "tester")

    def test_old_complete_backup_remains_valid(self):
        old_tables = {table: [] for table in github_backup.BACKUP_TABLES if table != repository.ANALYSIS_TABLE}
        old_tables[repository.CROSS_TABLE] = [{"lcte_id": 1}]
        imports = {table: [] for table in github_backup.IMPORT_BACKUP_TABLES}
        payload = {"schema": "estadias_completo_v1",
                   "results": {"schema": "estadias_backup_v1", "tables": old_tables, "records": {table: len(rows) for table, rows in old_tables.items()}},
                   "imports": {"schema": "estadias_importacoes_backup_v1", "tables": imports, "records": {table: 0 for table in imports}}}
        self.assertTrue(github_backup._valid_complete_backup(json.dumps(payload).encode()))

    def test_receive_marks_preserves_existing_date(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute(f"create table {repository.CROSS_TABLE} (lcte_id integer, nf text)")
            conn.execute(f"create table {repository.ANALYSIS_TABLE} (lcte_id integer primary key, nf text, analise_enviada_em text, analise_respondida_em text, atualizado_em text, atualizado_por text)")
            conn.execute(f"insert into {repository.CROSS_TABLE} values (1, '123')")
            conn.execute(f"insert into {repository.ANALYSIS_TABLE} values (1, '123', '2026-09-28T09:00:00', '', '', '')")
            with patch.object(repository, "get_connection", return_value=conn), patch.object(repository, "_invalidate_read_cache"):
                repository.restore_analysis_dates([(1, "2026-09-29T10:00:00", "2026-09-30T12:00:00")], "tester")
                dates = conn.execute(f"select analise_enviada_em, analise_respondida_em from {repository.ANALYSIS_TABLE}").fetchone()
        self.assertEqual(dates, ("2026-09-28T09:00:00", "2026-09-30T12:00:00"))


if __name__ == "__main__":
    unittest.main()
