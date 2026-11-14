
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
        banco.migrar_categorias()
        banco.migrar_lancamentos_parcelamento()

        banco.criar_parcelamentos()
        banco.criar_recorrencias()

        banco.criar_cartoes()
        banco.criar_faturas()


        categorias = banco.listar_categorias("despesa")
        self.categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "AlimentaÃ§Ã£o"
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

    def test_consultas_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Verifica a listagem geral
        parcelamentos = banco.listar_parcelamentos()

        self.assertEqual(len(parcelamentos), 1)
        self.assertEqual(parcelamentos[0][0], parcelamento_id)
        self.assertEqual(parcelamentos[0][1], "Notebook")
        self.assertEqual(parcelamentos[0][4], 600.00)
        self.assertEqual(parcelamentos[0][5], 3)
        self.assertEqual(parcelamentos[0][7], 1)

        # Verifica a listagem das parcelas
        parcelas = banco.listar_parcelas_parcelamento(
            parcelamento_id
        )

        self.assertEqual(len(parcelas), 3)
        self.assertEqual(
            [parcela[1] for parcela in parcelas],
            [1, 2, 3]
        )
        self.assertEqual(
            [parcela[3] for parcela in parcelas],
            [200.00, 200.00, 200.00]
        )

        # Verifica o resumo inicial
        resumo = banco.resumo_parcelas_parcelamento(
            parcelamento_id
        )

        self.assertEqual(
            resumo,
            (3, 0, 3, 0, 600.00)
        )

        # Verifica consultas de um ID inexistente
        self.assertEqual(
            banco.listar_parcelas_parcelamento(999999),
            []
        )

        self.assertEqual(
            banco.resumo_parcelas_parcelamento(999999),
            (0, 0, 0, 0, 0)
        )

    def test_resumo_parcelamento_com_parcela_paga(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        parcelas = banco.listar_parcelas_parcelamento(
            parcelamento_id
        )

        primeira_parcela_id = parcelas[0][0]

        # Simula pagamento no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                """
                UPDATE parcelamento_parcelas
                SET pago = 1,
                    data_pagamento = ?
                WHERE id = ?
                """,
                ("2026-11-10", primeira_parcela_id)
            )
            conexao.commit()

        resumo = banco.resumo_parcelas_parcelamento(
            parcelamento_id
        )

        self.assertEqual(
            resumo,
            (3, 1, 2, 200.00, 400.00)
        )

    def test_ordenacao_parcelamentos_ativos_inativos(self):
        ids = []

        for descricao in ["Primeiro", "Segundo", "Terceiro"]:
            parcelamento_id = banco.adicionar_parcelamento(
                descricao=descricao,
                tipo="despesa",
                categoria_id=self.categoria_id,
                valor_total=300.00,
                quantidade_parcelas=3,
                data_inicio="2026-11-10"
            )
            ids.append(parcelamento_id)

        # Desativa o segundo parcelamento
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                "UPDATE parcelamentos SET ativa = 0 WHERE id = ?",
                (ids[1],)
            )
            conexao.commit()

        resultado = banco.listar_parcelamentos()

        self.assertEqual(
            [linha[0] for linha in resultado],
            [ids[0], ids[2], ids[1]]
        )

        self.assertEqual(
            [linha[7] for linha in resultado],
            [1, 1, 0]
        )

    def test_conexoes_consultas_fechadas_apos_excecao(self):
        funcoes = [
            (banco.listar_parcelamentos, ()),
            (banco.listar_parcelas_parcelamento, (999999,)),
            (banco.resumo_parcelas_parcelamento, (999999,))
        ]

        for funcao, argumentos in funcoes:
            with self.subTest(funcao=funcao.__name__):
                conexao_real = sqlite3.connect(
                    self.caminho_banco
                )

                # Forca uma falha SQL durante a consulta
                conexao_real.set_authorizer(
                    lambda *args: sqlite3.SQLITE_DENY
                )

                class ConexaoMonitorada:
                    def __init__(self, conexao):
                        self.conexao = conexao
                        self.fechada = False

                    def cursor(self):
                        return self.conexao.cursor()

                    def close(self):
                        self.fechada = True
                        self.conexao.close()

                conexao_monitorada = ConexaoMonitorada(
                    conexao_real
                )

                with patch.object(
                    banco.sqlite3,
                    "connect",
                    return_value=conexao_monitorada
                ):
                    with self.assertRaises(sqlite3.DatabaseError):
                        funcao(*argumentos)

                self.assertTrue(
                    conexao_monitorada.fechada,
                    f"{funcao.__name__} nao fechou a conexao."
                )

    def test_atualizar_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        resultado = banco.atualizar_parcelamento(
            id_parcelamento=parcelamento_id,
            descricao="Notebook atualizado",
            categoria_id=self.categoria_id
        )

        self.assertTrue(resultado)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            registro = conexao.execute(
                """
                SELECT descricao, categoria_id,
                       valor_total, quantidade_parcelas
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()

            total_parcelas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(
            registro,
            ("Notebook atualizado", self.categoria_id, 600.00, 3)
        )
        self.assertEqual(total_parcelas, 3)

        # ID inexistente nao pode ser atualizado
        self.assertFalse(
            banco.atualizar_parcelamento(
                id_parcelamento=999999,
                descricao="Inexistente",
                categoria_id=self.categoria_id
            )
        )

    def test_alterar_status_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Desativa o parcelamento
        self.assertTrue(
            banco.alterar_status_parcelamento(
                parcelamento_id, 0
            )
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            status = conexao.execute(
                "SELECT ativa FROM parcelamentos WHERE id = ?",
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(status, 0)

        # Reativa o parcelamento
        self.assertTrue(
            banco.alterar_status_parcelamento(
                parcelamento_id, 1
            )
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            status = conexao.execute(
                "SELECT ativa FROM parcelamentos WHERE id = ?",
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(status, 1)

        # ID inexistente
        self.assertFalse(
            banco.alterar_status_parcelamento(999999, 0)
        )

    def test_alterar_status_parcelamento_invalido(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        for status_invalido in [2, -1, "ativo", None]:
            with self.subTest(status=status_invalido):
                with self.assertRaises(ValueError):
                    banco.alterar_status_parcelamento(
                        parcelamento_id,
                        status_invalido
                    )

                with closing(sqlite3.connect(self.caminho_banco)) as conexao:
                    status_atual = conexao.execute(
                        """
                        SELECT ativa
                        FROM parcelamentos
                        WHERE id = ?
                        """,
                        (parcelamento_id,)
                    ).fetchone()[0]

                self.assertEqual(status_atual, 1)

    def test_rollback_falha_atualizar_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Cria uma falha SQL proposital durante o UPDATE
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute("""
                CREATE TRIGGER impedir_atualizacao_parcelamento
                BEFORE UPDATE ON parcelamentos
                BEGIN
                    SELECT RAISE(ABORT, 'falha simulada');
                END;
            """)
            conexao.commit()

        with self.assertRaises(sqlite3.DatabaseError):
            banco.atualizar_parcelamento(
                id_parcelamento=parcelamento_id,
                descricao="Notebook alterado",
                categoria_id=self.categoria_id
            )

        # Confirma que o registro original foi preservado
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            registro = conexao.execute(
                """
                SELECT descricao, valor_total, quantidade_parcelas
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()

        self.assertEqual(
            registro,
            ("Notebook", 600.00, 3)
        )

    def test_excluir_parcelamento_sem_pagamentos(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        resultado = banco.excluir_parcelamento(parcelamento_id)

        self.assertEqual(resultado, (True, "excluido"))

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            quantidade_parcelamentos = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            quantidade_parcelas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(quantidade_parcelamentos, 0)
        self.assertEqual(quantidade_parcelas, 0)

        # Exclusao de ID inexistente
        self.assertEqual(
            banco.excluir_parcelamento(999999),
            (False, "nao_encontrado")
        )

    def test_excluir_parcelamento_com_parcela_paga(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Simula uma parcela paga no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                """
                UPDATE parcelamento_parcelas
                SET pago = 1,
                    data_pagamento = ?
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                ("2026-11-10", parcelamento_id)
            )
            conexao.commit()

        # A exclusao deve ser bloqueada
        resultado = banco.excluir_parcelamento(parcelamento_id)

        self.assertEqual(
            resultado,
            (False, "possui_pagamentos")
        )

        # Confirma que nenhum registro foi removido
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            quantidade_parcelamentos = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            quantidade_parcelas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(quantidade_parcelamentos, 1)
        self.assertEqual(quantidade_parcelas, 3)

    def test_excluir_parcelamento_com_lancamento_vinculado(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Cria um lancamento financeiro no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            cursor = conexao.cursor()


            cursor.execute(
                """
                INSERT INTO lancamentos (
                    data,
                    descricao,
                    tipo,
                    categoria,
                    valor
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "2026-11-10",
                    "Parcela vinculada",
                    "despesa",
                    "AlimentaÃ§Ã£o",
                    200.00
                )
            )


            lancamento_id = cursor.lastrowid

            cursor.execute(
                """
                UPDATE parcelamento_parcelas
                SET lancamento_id = ?
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                (lancamento_id, parcelamento_id)
            )

            conexao.commit()

        resultado = banco.excluir_parcelamento(parcelamento_id)

        self.assertEqual(
            resultado,
            (False, "possui_lancamentos")
        )

        # Verifica se os registros foram preservados
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcelamento = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            parcelas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            lancamento = conexao.execute(
                """
                SELECT COUNT(*)
                FROM lancamentos
                WHERE id = ?
                """,
                (lancamento_id,)
            ).fetchone()[0]

        self.assertEqual(parcelamento, 1)
        self.assertEqual(parcelas, 3)
        self.assertEqual(lancamento, 1)

    def test_rollback_falha_excluir_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        # Simula falha ao excluir o parcelamento principal
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute("""
                CREATE TRIGGER impedir_exclusao_parcelamento
                BEFORE DELETE ON parcelamentos
                BEGIN
                    SELECT RAISE(ABORT, 'falha simulada');
                END;
            """)
            conexao.commit()

        # A exclusao deve falhar e executar rollback
        with self.assertRaises(sqlite3.DatabaseError):
            banco.excluir_parcelamento(parcelamento_id)

        # Verifica se os dados foram restaurados
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            quantidade_parcelamentos = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamentos
                WHERE id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            quantidade_parcelas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(quantidade_parcelamentos, 1)
        self.assertEqual(quantidade_parcelas, 3)

    def test_marcar_parcela_paga_sem_duplicidade(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela_id = conexao.execute(
                """
                SELECT id
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        # Primeiro pagamento
        resultado = banco.marcar_parcela_paga(
            parcela_id,
            "2026-11-10"
        )

        self.assertTrue(resultado)

        # Segundo pagamento deve ser recusado
        resultado_repetido = banco.marcar_parcela_paga(
            parcela_id,
            "2026-11-10"
        )

        self.assertFalse(resultado_repetido)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela = conexao.execute(
                """
                SELECT pago, data_pagamento, lancamento_id
                FROM parcelamento_parcelas
                WHERE id = ?
                """,
                (parcela_id,)
            ).fetchone()

            quantidade_lancamentos = conexao.execute(
                """
                SELECT COUNT(*)
                FROM lancamentos
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(parcela[0], 1)
        self.assertEqual(parcela[1], "2026-11-10")
        self.assertIsNotNone(parcela[2])
        self.assertEqual(quantidade_lancamentos, 1)

    def test_rollback_falha_pagamento_parcela(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela_id = conexao.execute(
                """
                SELECT id
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                (parcelamento_id,)
            ).fetchone()[0]

            # Simula falha na criacao do lancamento
            conexao.execute("""
                CREATE TRIGGER impedir_lancamento_parcela
                BEFORE INSERT ON lancamentos
                BEGIN
                    SELECT RAISE(ABORT, 'falha simulada');
                END;
            """)
            conexao.commit()

        with self.assertRaises(sqlite3.DatabaseError):
            banco.marcar_parcela_paga(
                parcela_id,
                "2026-11-10"
            )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela = conexao.execute(
                """
                SELECT pago, data_pagamento, lancamento_id
                FROM parcelamento_parcelas
                WHERE id = ?
                """,
                (parcela_id,)
            ).fetchone()

            quantidade_lancamentos = conexao.execute(
                """
                SELECT COUNT(*)
                FROM lancamentos
                WHERE parcelamento_id = ?
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        self.assertEqual(parcela[0], 0)
        self.assertIsNone(parcela[1])
        self.assertIsNone(parcela[2])
        self.assertEqual(quantidade_lancamentos, 0)

    def test_dashboard_pagamento_parcelamento(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        dashboard_antes = banco.obter_dashboard()

        self.assertEqual(
            dashboard_antes["parcelamentos_abertos"],
            600.00
        )
        self.assertEqual(dashboard_antes["despesas"], 0.00)
        self.assertEqual(dashboard_antes["saldo"], 0.00)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela_id = conexao.execute(
                """
                SELECT id
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        resultado = banco.marcar_parcela_paga(
            parcela_id,
            "2026-11-10"
        )

        self.assertTrue(resultado)

        dashboard_depois = banco.obter_dashboard()

        self.assertEqual(
            dashboard_depois["parcelamentos_abertos"],
            400.00
        )
        self.assertEqual(dashboard_depois["despesas"], 200.00)
        self.assertEqual(dashboard_depois["saldo"], -200.00)
        self.assertEqual(dashboard_depois["receitas"], 0.00)

    def test_evolucao_anual_pagamento_parcela(self):
        parcelamento_id = banco.adicionar_parcelamento(
            descricao="Notebook",
            tipo="despesa",
            categoria_id=self.categoria_id,
            valor_total=600.00,
            quantidade_parcelas=3,
            data_inicio="2026-11-10"
        )

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcela_id = conexao.execute(
                """
                SELECT id
                FROM parcelamento_parcelas
                WHERE parcelamento_id = ?
                  AND numero_parcela = 1
                """,
                (parcelamento_id,)
            ).fetchone()[0]

        # Antes do pagamento, nao deve existir despesa
        evolucao_antes = banco.obter_evolucao_anual(2026)

        self.assertEqual(len(evolucao_antes), 12)

        for mes in evolucao_antes:
            self.assertEqual(mes["receitas"], 0.00)
            self.assertEqual(mes["despesas"], 0.00)
            self.assertEqual(mes["saldo"], 0.00)

        # Parcela vence em novembro, mas e paga em dezembro
        resultado = banco.marcar_parcela_paga(
            parcela_id,
            "2026-12-05"
        )

        self.assertTrue(resultado)

        evolucao_depois = banco.obter_evolucao_anual(2026)

        novembro = evolucao_depois[10]
        dezembro = evolucao_depois[11]

        self.assertEqual(novembro["mes"], 11)
        self.assertEqual(novembro["despesas"], 0.00)
        self.assertEqual(novembro["saldo"], 0.00)

        self.assertEqual(dezembro["mes"], 12)
        self.assertEqual(dezembro["receitas"], 0.00)
        self.assertEqual(dezembro["despesas"], 200.00)
        self.assertEqual(dezembro["saldo"], -200.00)

        # Nao deve haver despesa em outros meses
        self.assertEqual(
            sum(mes["despesas"] for mes in evolucao_depois),
            200.00
        )


if __name__ == "__main__":
    unittest.main()
