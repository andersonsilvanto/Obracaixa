"""Testes das regras de negócio (sem abrir a interface gráfica)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obracaixa import app


class FormatacaoTests(unittest.TestCase):
    def test_formata_brl(self) -> None:
        self.assertEqual(app.formata_brl(1234.5), "R$ 1.234,50")
        self.assertEqual(app.formata_brl(0), "R$ 0,00")

    def test_valida_data_aceita_tres_formatos(self) -> None:
        for texto in ("25-12-2026", "25/12/2026", "2026-12-25"):
            with self.subTest(texto=texto):
                self.assertEqual(app.valida_data(texto).day, 25)

    def test_valida_data_rejeita_texto_invalido(self) -> None:
        self.assertIsNone(app.valida_data("31/02/2026"))
        self.assertIsNone(app.valida_data("abc"))


class FinanceiroBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        pasta = Path(self._tmp.name)
        patches = (
            patch.object(app, "ARQ_TRANSACOES", str(pasta / "transacoes.json")),
            patch.object(app, "ARQ_PENDENCIAS", str(pasta / "pendencias.json")),
            patch.object(app, "ARQ_AGENDA", str(pasta / "agenda.json")),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.pasta = pasta
        self.fin = app.FinanceiroBase()

    def test_saldo_soma_entradas_e_subtrai_saidas(self) -> None:
        self.fin.adicionar_transacao({"tipo": "entrada", "valor": 1000.0})
        self.fin.adicionar_transacao({"tipo": "saida", "valor": 250.0})
        self.fin.adicionar_transacao({"tipo": "ajuste_positivo", "valor": 50.0})
        self.fin.adicionar_transacao({"tipo": "ajuste_negativo", "valor": 20.0})
        self.assertEqual(self.fin.resumo_financeiro()["saldo"], 780.0)

    def test_agendamento_nao_altera_o_saldo_mas_define_a_receber(self) -> None:
        self.fin.adicionar_agendamento(
            {"nome": "Obra A", "data_inicio": "2026-11-01", "valor_acordado": 5000.0}
        )
        resumo = self.fin.resumo_financeiro()
        self.assertEqual(resumo["saldo"], 0)
        self.assertEqual(resumo["valor_acordado"], 5000.0)
        self.assertEqual(resumo["valor_a_receber_obras"], 5000.0)

    def test_pagamento_parcial_reduz_a_receber_da_obra(self) -> None:
        self.fin.adicionar_agendamento(
            {"nome": "Obra A", "data_inicio": "2026-11-01", "valor_acordado": 5000.0}
        )
        self.fin.adicionar_transacao(
            {"tipo": "pagamento_parcial", "valor": 2000.0, "obra": "Obra A"}
        )
        resumo = self.fin.resumo_financeiro()
        self.assertEqual(resumo["saldo"], 2000.0)
        self.assertEqual(resumo["valor_a_receber_obras"], 3000.0)

    def test_parcelamento_gera_pendencias_restantes(self) -> None:
        base = {
            "id": "abc",
            "data": "2026-01-10",
            "valor": 100.0,
            "parcelas_totais": 4,
            "parcela_atual": 1,
            "sub_categoria": "Ferramentas",
        }
        self.fin.adicionar_pendencia_parcelada("saida", base)
        pendencias = self.fin.pendencias["a_pagar"]
        self.assertEqual(len(pendencias), 3)
        self.assertEqual([p["parcela"] for p in pendencias], [2, 3, 4])
        self.assertEqual(self.fin.resumo_financeiro()["a_pagar_parcelas"], 300.0)

    def test_compra_a_vista_nao_gera_pendencias(self) -> None:
        base = {"id": "x", "data": "2026-01-10", "valor": 80.0, "parcelas_totais": 1}
        self.fin.adicionar_pendencia_parcelada("saida", base)
        self.assertEqual(self.fin.pendencias["a_pagar"], [])

    def test_dados_persistem_em_disco(self) -> None:
        self.fin.adicionar_transacao({"tipo": "entrada", "valor": 10.0})
        salvo = json.loads((self.pasta / "transacoes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(salvo), 1)
        self.assertEqual(salvo[0]["valor"], 10.0)

    def test_migracao_preenche_campos_ausentes(self) -> None:
        migradas = self.fin.migrar_dados([{"valor": 5.0}])
        self.assertEqual(migradas[0]["tipo"], "saida")
        self.assertEqual(migradas[0]["parcelas_totais"], 1)
        self.assertIn("id", migradas[0])


    # --- Cancelamento de acordo (v3.4) ---

    def _agendar(self, nome, valor, data="2026-11-01"):
        self.fin.adicionar_agendamento(
            {"nome": nome, "data_inicio": data, "valor_acordado": valor}
        )

    def test_cancelar_acordo_remove_do_a_receber_sem_mexer_no_saldo(self) -> None:
        self._agendar("Obra A", 5000.0)
        self.fin.adicionar_transacao({"tipo": "entrada", "valor": 100.0})
        cancelada = self.fin.cancelar_agendamento("Obra A")
        self.assertIsNotNone(cancelada)
        resumo = self.fin.resumo_financeiro()
        self.assertEqual(resumo["valor_acordado"], 0)
        self.assertEqual(resumo["valor_a_receber_obras"], 0)
        self.assertEqual(resumo["saldo"], 100.0)

    def test_cancelamento_preserva_historico(self) -> None:
        self._agendar("Obra A", 5000.0)
        self.fin.cancelar_agendamento("Obra A")
        transacoes = self.fin.transacoes
        self.assertEqual(len(transacoes), 1)
        self.assertEqual(transacoes[0]["tipo"], "agendamento_cancelado")
        self.assertTrue(transacoes[0]["descricao"].startswith("[CANCELADO]"))
        self.assertEqual(self.fin.get_acordos_ativos(), [])

    def test_pagamento_recebido_de_obra_cancelada_nao_abate_outra_obra(self) -> None:
        self._agendar("Obra A", 5000.0)
        self._agendar("Obra B", 3000.0)
        self.fin.adicionar_transacao(
            {"tipo": "pagamento_parcial", "valor": 2000.0, "obra": "Obra A"}
        )
        self.fin.cancelar_agendamento("Obra A")
        resumo = self.fin.resumo_financeiro()
        self.assertEqual(resumo["valor_acordado"], 3000.0)
        self.assertEqual(resumo["valor_a_receber_obras"], 3000.0)
        self.assertEqual(resumo["saldo"], 2000.0)

    def test_cancelar_acordo_inexistente_ou_repetido_retorna_none(self) -> None:
        self.assertIsNone(self.fin.cancelar_agendamento("Nao existe"))
        self._agendar("Obra A", 1000.0)
        self.assertIsNotNone(self.fin.cancelar_agendamento("Obra A"))
        self.assertIsNone(self.fin.cancelar_agendamento("Obra A"))

    def test_cancelar_por_id_escolhe_o_acordo_correto(self) -> None:
        self._agendar("Obra A", 1000.0, "2026-11-01")
        self._agendar("Obra A", 2000.0, "2026-12-01")
        primeiro, segundo = self.fin.get_acordos_ativos()
        self.fin.cancelar_agendamento("Obra A", primeiro["id"])
        restantes = self.fin.get_acordos_ativos()
        self.assertEqual(len(restantes), 1)
        self.assertEqual(restantes[0]["id"], segundo["id"])
        self.assertEqual(self.fin.resumo_financeiro()["valor_acordado"], 2000.0)

    def test_cancelamento_persiste_em_disco_e_marca_a_agenda(self) -> None:
        self._agendar("Obra A", 1000.0)
        self.fin.cancelar_agendamento("Obra A")
        transacoes = json.loads((self.pasta / "transacoes.json").read_text(encoding="utf-8"))
        agenda = json.loads((self.pasta / "agenda.json").read_text(encoding="utf-8"))
        self.assertEqual(transacoes[0]["tipo"], "agendamento_cancelado")
        self.assertTrue(agenda["2026-11"][0]["cancelado"])

    def test_obra_reagendada_depois_do_cancelamento_volta_a_contar(self) -> None:
        self._agendar("Obra A", 1000.0)
        self.fin.cancelar_agendamento("Obra A")
        self._agendar("Obra A", 4000.0, "2026-12-01")
        resumo = self.fin.resumo_financeiro()
        self.assertEqual(resumo["valor_acordado"], 4000.0)
        self.assertEqual(resumo["valor_a_receber_obras"], 4000.0)


class PastaDadosTests(unittest.TestCase):
    def test_variavel_de_ambiente_tem_prioridade(self) -> None:
        with patch.dict("os.environ", {"OBRACAIXA_DADOS": "/tmp/meus-dados"}):
            self.assertEqual(app.pasta_dados(), "/tmp/meus-dados")


if __name__ == "__main__":
    unittest.main()
