
import os
import sqlite3
import tempfile
import unittest

from contextlib import closing
from unittest.mock import patch

import banco


class TestParcelamentos(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.caminho_banco = os.path.join(
            self.temp_dir.name,
            "parcelamentos_teste.db"
        )

        patcher = patch.dict(
            os.environ,
            {"KAIRUA_DB_PATH": self.caminho_banco}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        banco.criar_banco()
        banco.criar_categorias()
        banco.criar_parcelamentos()

        categorias = banco.listar_categorias("despesa")
        self.categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

    def test_cadastro_parcelamento_tres_parcelas(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Compra parcelada",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=300.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        self.assertIsNotNone(parcelamento_id)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcelas = conexao.execute(
                """
                SELECT numero_parcela, data_vencimento, valor, pago
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                ORDER BY numero_parcela
                """,
                (parcelamento_id,)
            ).fetchall()

        self.assertEqual(
            parcelas,
            [
                (1, "2026-11-10", 100.0, 0),
                (2, "2026-12-10", 100.0, 0),
                (3, "2027-01-10", 100.0, 0),
            ]
        )


    def test_arredondamento_valor_parcelas(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Compra com arredondamento",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=100.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            valores = [
                linha[0]
                for linha in conexao.execute(
                    """
                    SELECT valor
                    FROM parcelamento_parcelas
                    WHERE parcelamento_id = ?
                    ORDER BY numero_parcela
                    """,
                    (parcelamento_id,)
                ).fetchall()
            ]

        self.assertEqual(valores, [33.33, 33.33, 33.34])
        self.assertAlmostEqual(sum(valores), 100.00, places=2)


    def test_vencimentos_fim_de_mes(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Compra no fim do mes",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=400.00,
            quantidade_parcelas=4,
            data_inicio="2026-01-31"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            vencimentos = [
                linha[0]
                for linha in conexao.execute(
                    """
                    SELECT data_vencimento
                    FROM parcelamento_parcelas
                    WHERE parcelamento_id = ?
                    ORDER BY numero_parcela
                    """,
                    (parcelamento_id,)
                ).fetchall()
            ]

        self.assertEqual(
            vencimentos,
            [
                "2026-01-31",
                "2026-02-28",
                "2026-03-31",
                "2026-04-30"
            ]
        )


    def test_vencimentos_ano_bissexto(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Parcelamento em ano bissexto",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=300.00,
            quantidade_parcelas=3,
            data_inicio="2024-01-31"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            vencimentos = [
                linha[0]
                for linha in conexao.execute(
                    """
                    SELECT data_vencimento
                    FROM parcelamento_parcelas
                    WHERE parcelamento_id = ?
                    ORDER BY numero_parcela
                    """,
                    (parcelamento_id,)
                ).fetchall()
            ]

        self.assertEqual(
            vencimentos,
            [
                "2024-01-31",
                "2024-02-29",
                "2024-03-31"
            ]
        )


    def test_parcelamento_entradas_invalidas(self):
        casos = [
            (100.00, 0, "2026-11-10"),
            (100.00, -3, "2026-11-10"),
            (-100.00, 3, "2026-11-10"),
            (0.00, 3, "2026-11-10"),
            (100.00, 3, "2026-02-30"),
        ]

        for valor, quantidade, data in casos:
            with self.subTest(
                valor=valor,
                quantidade=quantidade,
                data=data
            ):
                with self.assertRaises(ValueError):
                    banco.adicionar_parcelamento(
                        descricao="Parcelamento invalido",
                        tipo="despesa",
                        categoria_id=self.categoria_id,
                        valor_total=valor,
                        quantidade_parcelas=quantidade,
                        data_inicio=data
                    )

    def test_rollback_falha_ao_criar_parcelas(self):
        # Trigger criado somente no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute("""
                CREATE TRIGGER falha_terceira_parcela
                BEFORE INSERT ON parcelamento_parcelas
                WHEN NEW.numero_parcela = 3
                BEGIN
                    SELECT RAISE(ABORT, 'Falha simulada');
                END;
            """)
            conexao.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            banco.adicionar_parcelamento(
                descricao="Teste de rollback",
                tipo="despesa",
                categoria_id=self.categoria_id,
                valor_total=400.00,
                quantidade_parcelas=4,
                data_inicio="2026-11-10"
            )

        # Verifica se a transacao foi totalmente desfeita
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            total_parcelamentos = conexao.execute(
                "SELECT COUNT(*) FROM parcelamentos"
            ).fetchone()[0]

            total_parcelas = conexao.execute(
                "SELECT COUNT(*) FROM parcelamento_parcelas"
            ).fetchone()[0]

        self.assertEqual(total_parcelamentos, 0)
        self.assertEqual(total_parcelas, 0)


if __name__ == "__main__":
    unittest.main()
