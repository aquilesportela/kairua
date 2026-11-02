
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import banco


class TestBancoTemporario(unittest.TestCase):

    def test_caminho_alternativo_e_isolamento(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste_kairua.db"

            with patch.dict(
                os.environ,
                {"KAIRUA_DB_PATH": str(caminho)}
            ):
                self.assertEqual(
                    banco.obter_caminho_banco(),
                    str(caminho)
                )

                with closing(
                    sqlite3.connect(banco.obter_caminho_banco())
                ) as conexao:
                    conexao.execute(
                        "CREATE TABLE verificacao (id INTEGER)"
                    )
                    conexao.commit()

                with closing(sqlite3.connect(str(caminho))) as conexao:
                    tabela = conexao.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'verificacao'"
                    ).fetchone()

                self.assertIsNotNone(tabela)

            self.assertFalse(
                "KAIRUA_DB_PATH" in os.environ
                and os.environ["KAIRUA_DB_PATH"] == str(caminho)
            )

        self.assertFalse(caminho.exists())


    def test_criar_tabela_lancamentos(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste_lancamentos.db"

            with patch.dict(
                os.environ,
                {"KAIRUA_DB_PATH": str(caminho)}
            ):
                banco.criar_banco()

                with closing(sqlite3.connect(str(caminho))) as conexao:
                    tabela = conexao.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'lancamentos'"
                    ).fetchone()

                    self.assertIsNotNone(tabela)

    def test_criar_categorias_padrao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste_categorias.db"

            with patch.dict(
                os.environ,
                {"KAIRUA_DB_PATH": str(caminho)}
            ):
                banco.criar_categorias()

                categorias = banco.listar_categorias()

                self.assertEqual(len(categorias), 11)

                nomes = [categoria[1] for categoria in categorias]

                self.assertIn("Alimentação", nomes)
                self.assertIn("Salário", nomes)


    def test_cadastro_e_filtros_lancamentos(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste_operacoes.db"

            with patch.dict(
                os.environ,
                {"KAIRUA_DB_PATH": str(caminho)}
            ):
                # Inicializa o banco temporário
                banco.criar_banco()
                banco.criar_categorias()
                banco.migrar_categorias()

                # Recupera categorias reais do banco de teste
                categorias_receita = banco.listar_categorias("receita")
                categorias_despesa = banco.listar_categorias("despesa")

                id_receita = next(
                    categoria[0]
                    for categoria in categorias_receita
                    if categoria[1] == "Salário"
                )

                id_despesa = next(
                    categoria[0]
                    for categoria in categorias_despesa
                    if categoria[1] == "Alimentação"
                )

                # Registra movimentações fictícias
                banco.adicionar_lancamento(
                    "2026-11-01",
                    "Salário de teste",
                    "receita",
                    id_receita,
                    3500.00
                )

                banco.adicionar_lancamento(
                    "2026-11-02",
                    "Mercado de teste",
                    "despesa",
                    id_despesa,
                    250.00
                )

                # Consulta todos os lançamentos
                lancamentos = banco.listar_lancamentos()

                self.assertEqual(len(lancamentos), 2)

                # Valida o filtro por tipo
                receitas = banco.listar_lancamentos(
                    tipo="receita"
                )

                self.assertEqual(len(receitas), 1)
                self.assertEqual(receitas[0][2], "Salário de teste")
                self.assertEqual(receitas[0][5], 3500.00)

                # Valida o filtro por categoria
                despesas = banco.listar_lancamentos(
                    categoria_id=id_despesa
                )

                self.assertEqual(len(despesas), 1)
                self.assertEqual(despesas[0][2], "Mercado de teste")

                # Valida o limite exclusivo da data final
                periodo = banco.listar_lancamentos(
                    data_inicio="2026-11-01",
                    data_fim="2026-11-03"
                )

                self.assertEqual(len(periodo), 2)

                periodo_anterior = banco.listar_lancamentos(
                    data_inicio="2026-11-01",
                    data_fim="2026-11-02"
                )

                self.assertEqual(len(periodo_anterior), 1)

                # Confirma que os valores estão preservados
                valores = {
                    lancamento[2]: lancamento[5]
                    for lancamento in lancamentos
                }

                self.assertEqual(
                    valores["Salário de teste"],
                    3500.00
                )

                self.assertEqual(
                    valores["Mercado de teste"],
                    250.00
                )


    def test_edicao_e_exclusao_lancamento(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teste_edicao.db"

            with patch.dict(
                os.environ,
                {"KAIRUA_DB_PATH": str(caminho)}
            ):
                # Prepara o banco temporario
                banco.criar_banco()
                banco.criar_categorias()
                banco.migrar_categorias()

                # Recupera uma categoria existente
                categorias = banco.listar_categorias("despesa")

                categoria_id = next(
                    categoria[0]
                    for categoria in categorias
                    if categoria[1] == "Alimentação"
                )

                # Cria um lancamento ficticio
                banco.adicionar_lancamento(
                    "2026-11-02",
                    "Compra original",
                    "despesa",
                    categoria_id,
                    100.00
                )

                lancamentos = banco.listar_lancamentos()
                self.assertEqual(len(lancamentos), 1)

                id_lancamento = lancamentos[0][0]

                # Confirma o cadastro
                original = banco.buscar_lancamento(id_lancamento)

                self.assertIsNotNone(original)
                self.assertEqual(original[2], "Compra original")
                self.assertEqual(original[5], 100.00)

                # Atualiza descricao e valor
                atualizado = banco.atualizar_lancamento(
                    id_lancamento,
                    "2026-11-02",
                    "Compra atualizada",
                    "despesa",
                    categoria_id,
                    175.50
                )

                self.assertTrue(atualizado)

                # Verifica se a atualizacao foi persistida
                alterado = banco.buscar_lancamento(id_lancamento)

                self.assertEqual(alterado[2], "Compra atualizada")
                self.assertEqual(alterado[5], 175.50)

                # Tenta atualizar usando categoria inexistente
                categoria_invalida = banco.atualizar_lancamento(
                    id_lancamento,
                    "2026-11-02",
                    "Alteracao invalida",
                    "despesa",
                    -1,
                    999.00
                )

                self.assertFalse(categoria_invalida)

                # Confirma que a tentativa invalida nao alterou os dados
                preservado = banco.buscar_lancamento(id_lancamento)

                self.assertEqual(preservado[2], "Compra atualizada")
                self.assertEqual(preservado[5], 175.50)

                # Exclui o lancamento
                excluido = banco.excluir_lancamento(id_lancamento)

                self.assertTrue(excluido)
                self.assertIsNone(
                    banco.buscar_lancamento(id_lancamento)
                )

                # Verifica exclusao de ID inexistente
                self.assertFalse(
                    banco.excluir_lancamento(id_lancamento)
                )

                # Verifica edicao de ID inexistente
                self.assertFalse(
                    banco.atualizar_lancamento(
                        id_lancamento,
                        "2026-11-02",
                        "Nao deve existir",
                        "despesa",
                        categoria_id,
                        50.00
                    )
                )


if __name__ == "__main__":
    unittest.main()
