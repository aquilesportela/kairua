
import unittest

import banco
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

class TestPeriodoFatura(unittest.TestCase):

    def test_compra_antes_fechamento(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-11-06", 7, 15
        )

        self.assertEqual(
            resultado,
            (2026, 11, "2026-11-07", "2026-12-15")
        )

    def test_compra_no_dia_fechamento(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-11-07", 7, 15
        )

        self.assertEqual(
            resultado,
            (2026, 12, "2026-12-07", "2027-01-15")
        )

    def test_compra_apos_fechamento(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-11-08", 7, 15
        )

        self.assertEqual(
            resultado,
            (2026, 12, "2026-12-07", "2027-01-15")
        )

    def test_virada_de_ano(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-12-31", 7, 15
        )

        self.assertEqual(
            resultado,
            (2027, 1, "2027-01-07", "2027-02-15")
        )

    def test_fechamento_em_mes_curto(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-02-01", 31, 31
        )

        self.assertEqual(
            resultado,
            (2026, 2, "2026-02-28", "2026-03-31")
        )

    def test_vencimento_em_fevereiro(self):
        resultado = banco.calcular_periodo_fatura(
            "2026-01-10", 20, 31
        )

        self.assertEqual(
            resultado,
            (2026, 1, "2026-01-20", "2026-02-28")
        )


class TestCriacaoFaturas(unittest.TestCase):

    def setUp(self):
        self.pasta_temporaria = tempfile.TemporaryDirectory()
        self.caminho_banco = (
            Path(self.pasta_temporaria.name) / "cartoes_teste.db"
        )

        self.patch_banco = patch.dict(
            os.environ,
            {"KAIRUA_DB_PATH": str(self.caminho_banco)}
        )
        self.patch_banco.start()

        banco.criar_cartoes()
        banco.criar_faturas()

        banco.adicionar_cartao(
            "Cartao de teste",
            5000.00,
            7,
            15
        )

        self.cartao_id = banco.listar_cartoes()[0][0]

    def tearDown(self):
        self.patch_banco.stop()
        self.pasta_temporaria.cleanup()

    def consultar_faturas(self):
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            return conexao.execute(
                """
                SELECT
                    id,
                    cartao_id,
                    mes,
                    ano,
                    data_fechamento,
                    data_vencimento
                FROM faturas
                ORDER BY id
                """
            ).fetchall()

    def test_criar_fatura(self):
        id_fatura = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-11-06"
        )

        faturas = self.consultar_faturas()

        self.assertEqual(len(faturas), 1)
        self.assertEqual(faturas[0][0], id_fatura)
        self.assertEqual(faturas[0][1], self.cartao_id)
        self.assertEqual(faturas[0][2], 11)
        self.assertEqual(faturas[0][3], 2026)
        self.assertEqual(faturas[0][4], "2026-11-07")
        self.assertEqual(faturas[0][5], "2026-12-15")

    def test_reutilizar_fatura_existente(self):
        primeiro_id = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-11-01"
        )

        segundo_id = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-11-06"
        )

        self.assertEqual(primeiro_id, segundo_id)
        self.assertEqual(len(self.consultar_faturas()), 1)

    def test_criar_nova_fatura_apos_fechamento(self):
        primeira_id = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-11-06"
        )

        segunda_id = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-11-07"
        )

        self.assertNotEqual(primeira_id, segunda_id)

        faturas = self.consultar_faturas()

        self.assertEqual(len(faturas), 2)
        self.assertEqual(
            [(fatura[3], fatura[2]) for fatura in faturas],
            [(2026, 11), (2026, 12)]
        )

    def test_cartao_inexistente(self):
        resultado = banco.obter_ou_criar_fatura(
            -1,
            "2026-11-06"
        )

        self.assertIsNone(resultado)
        self.assertEqual(len(self.consultar_faturas()), 0)

    def test_compra_cartao_persistida(self):
        # Prepara a tabela de categorias e compras
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        # Registra uma compra de R$ 250,00
        resultado = banco.adicionar_compra_cartao(
            self.cartao_id,
            categoria_id,
            "Compra de teste",
            "2026-11-06",
            250.00
        )

        self.assertTrue(resultado[0])

        id_compra, id_fatura = resultado[1]

        # Verifica se a compra realmente foi salva no SQLite
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            compra = conexao.execute(
                """
                SELECT descricao, valor, fatura_id
                FROM compras_cartao
                WHERE id = ?
                """,
                (id_compra,)
            ).fetchone()

            fatura = conexao.execute(
                """
                SELECT valor_total
                FROM faturas
                WHERE id = ?
                """,
                (id_fatura,)
            ).fetchone()

        self.assertIsNotNone(
            compra,
            "A compra nao foi persistida no banco."
        )

        self.assertEqual(compra[0], "Compra de teste")
        self.assertEqual(compra[1], 250.00)
        self.assertEqual(compra[2], id_fatura)
        self.assertEqual(fatura[0], 250.00)


    def test_limite_apos_compra(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        # Limite inicial
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )

        # Registra uma compra
        resultado = banco.adicionar_compra_cartao(
            self.cartao_id,
            categoria_id,
            "Compra de teste",
            "2026-11-06",
            250.00
        )

        self.assertTrue(resultado[0])

        # Confere o limite comprometido
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            250.00
        )

        # Confere o limite restante
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4750.00
        )


    def test_compra_acima_do_limite(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        # Tenta comprar acima do limite de R$ 5.000
        resultado = banco.adicionar_compra_cartao(
            self.cartao_id,
            categoria_id,
            "Compra acima do limite",
            "2026-11-06",
            5500.00
        )

        self.assertFalse(resultado[0])
        self.assertEqual(
            resultado[1],
            ("limite_insuficiente", 5000.00)
        )

        # Confirma que nenhuma compra foi registrada
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            quantidade_compras = conexao.execute(
                "SELECT COUNT(*) FROM compras_cartao"
            ).fetchone()[0]

            quantidade_faturas = conexao.execute(
                "SELECT COUNT(*) FROM faturas"
            ).fetchone()[0]

        self.assertEqual(quantidade_compras, 0)
        self.assertEqual(quantidade_faturas, 0)

        # O limite deve permanecer intacto
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )


    def test_compra_parcelada_distribuicao_e_limite(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Notebook parcelado",
            "2026-11-06",
            1200.00,
            6
        )

        self.assertTrue(resultado[0])
        compra_id, quantidade = resultado[1]

        self.assertEqual(quantidade, 6)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            compra = conexao.execute(
                """
                SELECT valor
                FROM compras_cartao
                WHERE id = ?
                """,
                (compra_id,)
            ).fetchone()

            parcelas = conexao.execute(
                """
                SELECT
                    pc.numero_parcela,
                    pc.total_parcelas,
                    pc.valor,
                    f.ano,
                    f.mes,
                    f.valor_total
                FROM parcelas_cartao pc
                JOIN faturas f
                    ON f.id = pc.fatura_id
                WHERE pc.compra_id = ?
                ORDER BY pc.numero_parcela
                """,
                (compra_id,)
            ).fetchall()

        # Compra original registra o valor integral
        self.assertEqual(compra[0], 1200.00)

        # Foram criadas seis parcelas
        self.assertEqual(len(parcelas), 6)

        # Cada parcela tem valor de R$ 200
        self.assertEqual(
            [parcela[2] for parcela in parcelas],
            [200.00] * 6
        )

        # Numeracao das parcelas
        self.assertEqual(
            [parcela[0] for parcela in parcelas],
            [1, 2, 3, 4, 5, 6]
        )

        # Cada parcela pertence a uma fatura mensal
        self.assertEqual(
            [(parcela[3], parcela[4]) for parcela in parcelas],
            [
                (2026, 11),
                (2026, 12),
                (2027, 1),
                (2027, 2),
                (2027, 3),
                (2027, 4)
            ]
        )

        # Cada fatura recebeu R$ 200
        self.assertEqual(
            [parcela[5] for parcela in parcelas],
            [200.00] * 6
        )

        # O limite deve considerar os R$ 1.200 completos
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            1200.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            3800.00
        )


    def test_arredondamento_compra_parcelada(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra com arredondamento",
            "2026-11-06",
            100.00,
            3
        )

        self.assertTrue(resultado[0])

        compra_id, quantidade = resultado[1]
        self.assertEqual(quantidade, 3)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcelas = conexao.execute(
                """
                SELECT numero_parcela, valor
                FROM parcelas_cartao
                WHERE compra_id = ?
                ORDER BY numero_parcela
                """,
                (compra_id,)
            ).fetchall()

            total_faturas = conexao.execute(
                """
                SELECT SUM(valor_total)
                FROM faturas
                WHERE cartao_id = ?
                """,
                (self.cartao_id,)
            ).fetchone()[0]

        self.assertEqual(
            [parcela[1] for parcela in parcelas],
            [33.33, 33.33, 33.34]
        )

        self.assertAlmostEqual(
            sum(parcela[1] for parcela in parcelas),
            100.00,
            places=2
        )

        self.assertAlmostEqual(
            total_faturas,
            100.00,
            places=2
        )

        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            100.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4900.00
        )


    def test_compra_parcelada_acima_do_limite(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")

        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra parcelada acima do limite",
            "2026-11-06",
            6000.00,
            6
        )

        # Operacao deve ser rejeitada
        self.assertFalse(resultado[0])

        self.assertEqual(
            resultado[1],
            ("limite_insuficiente", 5000.00)
        )

        # Nenhum registro deve ter sido criado
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            for tabela in (
                "compras_cartao",
                "parcelas_cartao",
                "faturas"
            ):
                quantidade = conexao.execute(
                    f"SELECT COUNT(*) FROM {tabela}"
                ).fetchone()[0]

                self.assertEqual(
                    quantidade,
                    0,
                    f"A tabela {tabela} nao deveria ter registros."
                )

        # O limite deve permanecer intacto
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )


    def test_parcelamento_com_fatura_paga_rollback(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")
        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        # Cria previamente a fatura de dezembro
        fatura_paga_id = banco.obter_ou_criar_fatura(
            self.cartao_id,
            "2026-12-06"
        )

        # Marca a fatura como paga no banco temporario
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            conexao.execute(
                """
                UPDATE faturas
                SET paga = 1
                WHERE id = ?
                """,
                (fatura_paga_id,)
            )
            conexao.commit()

        # Tenta criar tres parcelas, incluindo dezembro
        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra com fatura paga",
            "2026-11-06",
            900.00,
            3
        )

        self.assertEqual(
            resultado,
            (False, "fatura_paga")
        )

        # Verifica que nenhuma compra ou parcela foi gravada
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            compras = conexao.execute(
                "SELECT COUNT(*) FROM compras_cartao"
            ).fetchone()[0]

            parcelas = conexao.execute(
                "SELECT COUNT(*) FROM parcelas_cartao"
            ).fetchone()[0]

            faturas = conexao.execute(
                """
                SELECT ano, mes, paga
                FROM faturas
                ORDER BY ano, mes
                """
            ).fetchall()

        self.assertEqual(compras, 0)
        self.assertEqual(parcelas, 0)

        # Somente a fatura paga preexistente deve permanecer
        self.assertEqual(
            faturas,
            [(2026, 12, 1)]
        )

        # Nenhum limite deve ter sido comprometido
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )

    def test_pagamento_fatura_libera_limite(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")
        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_cartao(
            self.cartao_id,
            categoria_id,
            "Compra para testar pagamento",
            "2026-11-06",
            800.00
        )

        self.assertTrue(resultado[0])
        _, fatura_id = resultado[1]

        # Antes do pagamento
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            800.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4200.00
        )

        # Efetua o pagamento
        pagamento = banco.pagar_fatura(
            fatura_id,
            "2026-12-10"
        )

        self.assertEqual(pagamento, (True, 800.00))

        # Confere a persistencia do pagamento
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            fatura = conexao.execute(
                """
                SELECT paga, data_pagamento, valor_total
                FROM faturas
                WHERE id = ?
                """,
                (fatura_id,)
            ).fetchone()

        self.assertEqual(
            fatura,
            (1, "2026-12-10", 800.00)
        )

        # O limite deve ser liberado
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )

        # Impede pagamento duplicado
        segundo_pagamento = banco.pagar_fatura(
            fatura_id,
            "2026-12-11"
        )

        self.assertEqual(
            segundo_pagamento,
            (False, "fatura_ja_paga")
        )


    def test_pagamento_parcela_libera_limite_proporcional(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categorias = banco.listar_categorias("despesa")
        categoria_id = next(
            categoria[0]
            for categoria in categorias
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Notebook parcelado",
            "2026-11-06",
            1200.00,
            6
        )

        self.assertTrue(resultado[0])
        compra_id, _ = resultado[1]

        # Antes do pagamento, todo o valor compromete o limite
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            1200.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            3800.00
        )

        # Localiza a fatura da primeira parcela
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            primeira_fatura = conexao.execute(
                """
                SELECT pc.fatura_id
                FROM parcelas_cartao pc
                WHERE pc.compra_id = ?
                AND pc.numero_parcela = 1
                """,
                (compra_id,)
            ).fetchone()

        self.assertIsNotNone(primeira_fatura)
        fatura_id = primeira_fatura[0]

        # Paga apenas a primeira fatura
        pagamento = banco.pagar_fatura(
            fatura_id,
            "2026-12-10"
        )

        self.assertEqual(pagamento, (True, 200.00))

        # Apenas R$ 200 devem ser liberados
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            1000.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4000.00
        )

        # Confere que as outras cinco faturas continuam abertas
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            faturas_abertas = conexao.execute(
                """
                SELECT COUNT(*)
                FROM faturas
                WHERE cartao_id = ?
                AND paga = 0
                """,
                (self.cartao_id,)
            ).fetchone()[0]

        self.assertEqual(faturas_abertas, 5)

    def test_pagamento_fatura_inexistente(self):
        # Prepara as tabelas necessarias para calcular o limite
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        # Tenta pagar uma fatura que nao existe
        resultado = banco.pagar_fatura(
            -1,
            "2026-12-10"
        )

        self.assertEqual(
            resultado,
            (False, "fatura_inexistente")
        )

        # O limite deve permanecer inalterado
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            0.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )

    def test_pagamento_fatura_com_compras_mistas(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categoria_id = next(
            categoria[0]
            for categoria in banco.listar_categorias("despesa")
            if categoria[1] == "Alimentação"
        )

        # Compra comum de R$ 300
        compra_comum = banco.adicionar_compra_cartao(
            self.cartao_id,
            categoria_id,
            "Compra comum",
            "2026-11-06",
            300.00
        )

        self.assertTrue(compra_comum[0])
        fatura_id = compra_comum[1][1]

        # Compra parcelada de R$ 1.200 em 6 vezes
        compra_parcelada = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra parcelada",
            "2026-11-06",
            1200.00,
            6
        )

        self.assertTrue(compra_parcelada[0])

        # Limite antes do pagamento
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            1500.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            3500.00
        )

        # A primeira fatura deve conter R$ 300 + R$ 200
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            valor_fatura = conexao.execute(
                """
                SELECT valor_total
                FROM faturas
                WHERE id = ?
                """,
                (fatura_id,)
            ).fetchone()[0]

        self.assertEqual(valor_fatura, 500.00)

        # Paga a primeira fatura
        pagamento = banco.pagar_fatura(
            fatura_id,
            "2026-12-10"
        )

        self.assertEqual(pagamento, (True, 500.00))

        # Restam cinco parcelas de R$ 200
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            1000.00
        )
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4000.00
        )

    def test_parcelamento_fim_mes_ano_bissexto(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categoria_id = next(
            categoria[0]
            for categoria in banco.listar_categorias("despesa")
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra no fim do mes",
            "2028-01-31",
            400.00,
            4
        )

        self.assertTrue(resultado[0])
        compra_id, quantidade = resultado[1]

        self.assertEqual(quantidade, 4)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcelas = conexao.execute(
                """
                SELECT
                    pc.numero_parcela,
                    pc.valor,
                    f.ano,
                    f.mes,
                    f.data_fechamento,
                    f.data_vencimento
                FROM parcelas_cartao pc
                JOIN faturas f
                    ON f.id = pc.fatura_id
                WHERE pc.compra_id = ?
                ORDER BY pc.numero_parcela
                """,
                (compra_id,)
            ).fetchall()

        self.assertEqual(len(parcelas), 4)

        # Confere os meses das faturas
        self.assertEqual(
            [(p[2], p[3]) for p in parcelas],
            [
                (2028, 2),
                (2028, 3),
                (2028, 4),
                (2028, 5)
            ]
        )

        # Confere as datas de fechamento
        self.assertEqual(
            [p[4] for p in parcelas],
            [
                "2028-02-07",
                "2028-03-07",
                "2028-04-07",
                "2028-05-07"
            ]
        )

        # Vencimento no mes seguinte ao fechamento
        self.assertEqual(
            [p[5] for p in parcelas],
            [
                "2028-03-15",
                "2028-04-15",
                "2028-05-15",
                "2028-06-15"
            ]
        )

        # Valores preservados
        self.assertEqual(
            [p[1] for p in parcelas],
            [100.00] * 4
        )

        # Limite comprometido integralmente
        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            400.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4600.00
        )

    def test_parcelamento_virada_ano(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categoria_id = next(
            categoria[0]
            for categoria in banco.listar_categorias("despesa")
            if categoria[1] == "Alimentação"
        )

        resultado = banco.adicionar_compra_parcelada_cartao(
            self.cartao_id,
            categoria_id,
            "Compra de dezembro",
            "2026-12-20",
            600.00,
            3
        )

        self.assertTrue(resultado[0])
        compra_id, quantidade = resultado[1]
        self.assertEqual(quantidade, 3)

        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            parcelas = conexao.execute(
                """
                SELECT
                    pc.numero_parcela,
                    pc.valor,
                    f.ano,
                    f.mes,
                    f.data_fechamento,
                    f.data_vencimento
                FROM parcelas_cartao pc
                JOIN faturas f
                    ON f.id = pc.fatura_id
                WHERE pc.compra_id = ?
                ORDER BY pc.numero_parcela
                """,
                (compra_id,)
            ).fetchall()

        self.assertEqual(
            parcelas,
            [
                (1, 200.00, 2027, 1, "2027-01-07", "2027-02-15"),
                (2, 200.00, 2027, 2, "2027-02-07", "2027-03-15"),
                (3, 200.00, 2027, 3, "2027-03-07", "2027-04-15")
            ]
        )

        self.assertEqual(
            banco.calcular_limite_utilizado(self.cartao_id),
            600.00
        )

        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            4400.00
        )

    def test_compra_parcelada_dados_invalidos(self):
        banco.criar_categorias()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

        categoria_id = next(
            categoria[0]
            for categoria in banco.listar_categorias("despesa")
            if categoria[1] == "Alimentação"
        )

        casos = [
            ("quantidade_invalida", "Compra", "2026-11-06", 500.00, 1),
            ("valor_invalido", "Compra", "2026-11-06", 0.00, 3),
            ("valor_invalido", "Compra", "2026-11-06", -100.00, 3),
            ("descricao_invalida", "   ", "2026-11-06", 500.00, 3),
            ("data_invalida", "Compra", "2026-02-30", 500.00, 3),
            ("data_invalida", "Compra", "data-errada", 500.00, 3)
        ]

        for erro, descricao, data, valor, parcelas in casos:
            with self.subTest(erro=erro, data=data, valor=valor):
                resultado = banco.adicionar_compra_parcelada_cartao(
                    self.cartao_id,
                    categoria_id,
                    descricao,
                    data,
                    valor,
                    parcelas
                )

                self.assertEqual(resultado, (False, erro))

        # Nenhuma compra ou parcela deve ter sido criada
        with closing(sqlite3.connect(self.caminho_banco)) as conexao:
            compras = conexao.execute(
                "SELECT COUNT(*) FROM compras_cartao"
            ).fetchone()[0]

            parcelas = conexao.execute(
                "SELECT COUNT(*) FROM parcelas_cartao"
            ).fetchone()[0]

            faturas = conexao.execute(
                "SELECT COUNT(*) FROM faturas"
            ).fetchone()[0]

        self.assertEqual(compras, 0)
        self.assertEqual(parcelas, 0)
        self.assertEqual(faturas, 0)

        # O limite deve permanecer integralmente disponivel
        self.assertEqual(
            banco.calcular_limite_disponivel(self.cartao_id),
            5000.00
        )


if __name__ == "__main__":
    unittest.main()
