
import os
import sqlite3
import tempfile
import unittest

from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import banco


class TestRecorrencias(unittest.TestCase):

    def setUp(self):
        # Cria um banco temporario exclusivo para cada teste
        self.pasta_temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta_temporaria.cleanup)

        self.caminho_banco = str(
            Path(self.pasta_temporaria.name) / "recorrencias_teste.db"
        )

        # Direciona as operacoes para o banco temporario
        self.ambiente = patch.dict(
            os.environ,
            {"KAIRUA_DB_PATH": self.caminho_banco}
        )
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

        # Inicializa as tabelas necessarias
        banco.criar_banco()
        banco.criar_categorias()
        banco.criar_recorrencias()

        # Seleciona uma categoria de despesa existente
        categorias = banco.listar_categorias("despesa")

        self.categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

    # ==================================================
    # TESTE 1 - CADASTRO E PRIMEIRA OCORRENCIA
    # ==================================================

    def test_cadastro_recorrencia_e_primeira_ocorrencia(self):
        recorrencia_id = banco.adicionar_recorrencia(
            descricao="Internet residencial",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor=120.00,
            frequencia="mensal",
            data_inicio="2026-11-10"
        )

        # Verifica se o cadastro retornou um ID valido
        self.assertIsInstance(recorrencia_id, int)
        self.assertGreater(recorrencia_id, 0)

        # Confere o cadastro pela funcao publica
        recorrencias = banco.listar_recorrencias()

        self.assertEqual(len(recorrencias), 1)

        recorrencia = recorrencias[0]

        self.assertEqual(recorrencia[0], recorrencia_id)
        self.assertEqual(recorrencia[1], "Internet residencial")
        self.assertEqual(recorrencia[2], "despesa")
        self.assertEqual(recorrencia[3], "Alimentação")
        self.assertEqual(recorrencia[4], 120.00)
        self.assertEqual(recorrencia[5], "mensal")
        self.assertEqual(recorrencia[6], "2026-11-10")
        self.assertIsNone(recorrencia[7])
        self.assertEqual(recorrencia[8], 1)

        # Confere a primeira ocorrencia diretamente no SQLite
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            ocorrencias = conexao.execute(
                """
                SELECT
                    recorrencia_id,
                    data_vencimento,
                    valor,
                    pago,
                    data_pagamento,
                    lancamento_id
                FROM recorrencia_ocorrencias
                WHERE recorrencia_id = ?
                """,
                (recorrencia_id,)
            ).fetchall()

        self.assertEqual(
            ocorrencias,
            [
                (
                    recorrencia_id,
                    "2026-11-10",
                    120.00,
                    0,
                    None,
                    None
                )
            ]
        )

    # ==================================================
    # TESTE 2 - RECORRENCIA ANUAL EM ANO BISSEXTO
    # ==================================================

    def test_calculo_recorrencia_anual_ano_bissexto(self):
        proxima_data = banco.calcular_proxima_data_recorrencia(
            ultima_data="2024-02-29",
            data_inicio="2024-02-29",
            frequencia="anual"
        )

        self.assertEqual(
            proxima_data.strftime("%Y-%m-%d"),
            "2025-02-28"
        )


    def test_recorrencia_mensal_com_data_fim(self):
        recorrencia_id = banco.adicionar_recorrencia(
            descricao="Assinatura de teste",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor=49.90,
            frequencia="mensal",
            data_inicio="2026-11-10",
            data_fim="2026-12-10"
        )

        # Deve gerar a ocorrencia de dezembro
        resultado = banco.gerar_proxima_ocorrencia(
            recorrencia_id
        )

        self.assertTrue(resultado)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            datas = [
                linha[0]
                for linha in conexao.execute(
                    """
                    SELECT data_vencimento
                    FROM recorrencia_ocorrencias
                    WHERE recorrencia_id = ?
                    ORDER BY data_vencimento
                    """,
                    (recorrencia_id,)
                ).fetchall()
            ]

        self.assertEqual(
            datas,
            ["2026-11-10", "2026-12-10"]
        )

        # Janeiro ultrapassa a data de termino
        resultado = banco.gerar_proxima_ocorrencia(
            recorrencia_id
        )

        self.assertFalse(resultado)


    def test_conexao_fechada_apos_excecao(self):
        recorrencia_id = banco.adicionar_recorrencia(
            descricao="Recorrencia com data invalida",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor=100.00,
            frequencia="mensal",
            data_inicio="2026-11-10"
        )

        # Altera somente o banco temporario para provocar um erro
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                """
                UPDATE recorrencia_ocorrencias
                SET data_vencimento = ?
                WHERE recorrencia_id = ?
                """,
                ("data-invalida", recorrencia_id)
            )
            conexao.commit()

        # A funcao deve propagar o erro, mas fechar a conexao
        with self.assertRaises(ValueError):
            banco.gerar_proxima_ocorrencia(recorrencia_id)

        # No Windows, a exclusao falharia se a conexao
        # SQLite ainda estivesse aberta
        os.remove(self.caminho_banco)

        self.assertFalse(os.path.exists(self.caminho_banco))


    def test_recorrencia_desativada_nao_gera_ocorrencia(self):
        recorrencia_id = banco.adicionar_recorrencia(
            descricao="Assinatura desativada",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor=49.90,
            frequencia="mensal",
            data_inicio="2026-11-10"
        )

        self.assertIsNotNone(recorrencia_id)

        # Desativa a recorrencia no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                """
                UPDATE recorrencias
                SET ativa = 0
                WHERE id = ?
                """,
                (recorrencia_id,)
            )
            conexao.commit()

        resultado = banco.gerar_proxima_ocorrencia(
            recorrencia_id
        )

        self.assertFalse(resultado)

        # Apenas a ocorrencia inicial deve existir
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            quantidade = conexao.execute(
                """
                SELECT COUNT(*)
                FROM recorrencia_ocorrencias
                WHERE recorrencia_id = ?
                """,
                (recorrencia_id,)
            ).fetchone()[0]

        self.assertEqual(quantidade, 1)


    def test_impede_ocorrencias_duplicadas(self):
        recorrencia_id = banco.adicionar_recorrencia(
            descricao="Assinatura mensal",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor=49.90,
            frequencia="mensal",
            data_inicio="2026-11-10"
        )

        self.assertIsNotNone(recorrencia_id)

        # A primeira ocorrencia ja foi criada no cadastro.
        # Tentar inserir outra com a mesma data deve falhar.
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            with self.assertRaises(sqlite3.IntegrityError):
                conexao.execute(
                    """
                    INSERT INTO recorrencia_ocorrencias (
                        recorrencia_id,
                        data_vencimento,
                        valor,
                        pago
                    )
                    VALUES (?, ?, ?, 0)
                    """,
                    (
                        recorrencia_id,
                        "2026-11-10",
                        49.90
                    )
                )

            conexao.rollback()

            quantidade = conexao.execute(
                """
                SELECT COUNT(*)
                FROM recorrencia_ocorrencias
                WHERE recorrencia_id = ?
                AND data_vencimento = ?
                """,
                (
                    recorrencia_id,
                    "2026-11-10"
                )
            ).fetchone()[0]

        self.assertEqual(quantidade, 1)


if __name__ == "__main__":
    unittest.main()
