import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import banco


class TestEsquemaHibrido(unittest.TestCase):
    def setUp(self):
        # Contratos e fixtures da etapa 2 permanecem isolados das etapas posteriores.
        catalogo = patch.object(banco, "MIGRACOES", banco.MIGRACOES[:2])
        catalogo.start()
        self.addCleanup(catalogo.stop)
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / "hibrido_teste.db"
        ambiente = patch.dict(os.environ, {"KAIRUA_DB_PATH": str(self.caminho)})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.preparar_legado()

    def preparar_legado(self):
        for funcao in (
            banco.criar_banco, banco.criar_categorias, banco.migrar_categorias,
            banco.criar_recorrencias, banco.migrar_lancamentos_recorrencia,
            banco.criar_parcelamentos, banco.migrar_lancamentos_parcelamento,
            banco.criar_cartoes, banco.criar_faturas,
            banco.criar_compras_cartao, banco.criar_parcelas_cartao,
        ):
            funcao()
        with closing(banco.abrir_conexao()) as conexao:
            conexao.execute("INSERT INTO lancamentos "
                            "(id, data, descricao, tipo, categoria, valor, categoria_id) "
                            "VALUES (1, '2026-11-01', 'Manual antigo', 'despesa', 'Alimentação', 12.34, 1)")
            conexao.execute("INSERT INTO lancamentos "
                            "(id, data, descricao, tipo, categoria, valor, categoria_id) "
                            "VALUES (2, '2026-12-01', 'Outro', 'despesa', 'Alimentação', 20, 1)")
            conexao.execute("INSERT INTO recorrencias "
                            "(id, descricao, tipo, categoria_id, valor, frequencia, data_inicio) "
                            "VALUES (1, 'Serviço', 'despesa', 1, 20, 'mensal', '2026-11-01')")
            conexao.execute("INSERT INTO recorrencia_ocorrencias "
                            "(id, recorrencia_id, data_vencimento, valor) "
                            "VALUES (1, 1, '2026-11-01', 20)")
            conexao.execute("INSERT INTO parcelamentos "
                            "(id, descricao, tipo, categoria_id, valor_total, quantidade_parcelas, data_inicio) "
                            "VALUES (1, 'Aquisição', 'despesa', 1, 40, 2, '2026-11-01')")
            conexao.execute("INSERT INTO parcelamento_parcelas "
                            "(id, parcelamento_id, numero_parcela, data_vencimento, valor) "
                            "VALUES (1, 1, 1, '2026-11-01', 20)")
            conexao.execute("INSERT INTO cartoes VALUES (1, 'Cartão', 1000, 7, 15, 1)")
            conexao.execute("INSERT INTO faturas "
                            "(id, cartao_id, mes, ano, data_fechamento, data_vencimento, valor_total) "
                            "VALUES (1, 1, 11, 2026, '2026-11-07', '2026-12-15', 10)")
            conexao.execute("INSERT INTO compras_cartao VALUES "
                            "(1, 1, 1, 1, 'Compra', '2026-11-01', 10)")
            conexao.execute("INSERT INTO parcelas_cartao VALUES (1, 1, 1, 2, 1, 5)")
            conexao.commit()

    def migrar_e_conectar(self):
        banco.aplicar_migracoes(self.caminho)
        conexao = banco.abrir_conexao()
        self.addCleanup(conexao.close)
        conexao.execute("PRAGMA foreign_keys = ON")
        self.assertEqual(conexao.execute("PRAGMA foreign_keys").fetchone(), (1,))
        return conexao

    def evento(self, conexao, **alteracoes):
        campos = dict(tipo="despesa", descricao="Evento", categoria_id=1,
                      valor_centavos=1000, data_competencia="2026-11-01",
                      situacao_competencia="confirmada", chave_origem="origem:1")
        campos.update(alteracoes)
        return conexao.execute(
            f"INSERT INTO eventos_financeiros ({', '.join(campos)}) "
            f"VALUES ({', '.join('?' for _ in campos)})", tuple(campos.values())
        ).lastrowid

    def test_catalogo_completo_cria_tabelas_e_reexecuta(self):
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [1, 2])
        conexao = self.migrar_e_conectar()
        evento = self.evento(conexao)
        conexao.execute("INSERT INTO liquidacoes_eventos "
                        "(evento_id, lancamento_id, valor_centavos) VALUES (?, 1, 100)", (evento,))
        conexao.commit()
        antes = conexao.execute("SELECT * FROM esquema_migracoes ORDER BY versao").fetchall()
        eventos = conexao.execute("SELECT * FROM eventos_financeiros").fetchall()
        liquidacoes = conexao.execute("SELECT * FROM liquidacoes_eventos").fetchall()
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        self.assertEqual(conexao.execute("SELECT * FROM esquema_migracoes ORDER BY versao").fetchall(), antes)
        self.assertEqual(conexao.execute("SELECT * FROM eventos_financeiros").fetchall(), eventos)
        self.assertEqual(conexao.execute("SELECT * FROM liquidacoes_eventos").fetchall(), liquidacoes)

    def test_banco_vazio_rejeita_versao_2_e_preserva_versao_1(self):
        destino = self.caminho.with_name("vazio.db")
        with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(destino)}):
            with self.assertRaisesRegex(ValueError, "Esquema legado incompativel"):
                banco.aplicar_migracoes(destino)
        with closing(sqlite3.connect(destino)) as conexao:
            tabelas = {r[0] for r in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(conexao.execute("SELECT versao FROM esquema_migracoes").fetchall(), [(1,)])
        self.assertEqual(tabelas, {"esquema_migracoes"})

    def test_valores_tipos_estados_e_campos_obrigatorios(self):
        conexao = self.migrar_e_conectar()
        casos = (
            {"tipo": "transferencia"}, {"tipo": None}, {"descricao": "  "},
            {"descricao": None}, {"categoria_id": None}, {"valor_centavos": 0},
            {"valor_centavos": -1}, {"valor_centavos": 1.5},
            {"valor_centavos": "abc"}, {"valor_centavos": None},
            {"situacao_competencia": "prevista"}, {"situacao_competencia": None},
            {"chave_origem": " "}, {"chave_origem": None},
        )
        for caso in casos:
            with self.subTest(caso=caso):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.evento(conexao, **caso)
        for numero, tipo in enumerate(("receita", "despesa")):
            self.evento(conexao, tipo=tipo, chave_origem=f"valida:{numero}")

    def test_datas_iso_e_coerencia_da_situacao(self):
        conexao = self.migrar_e_conectar()
        for data in (None, "", "2026-02-29", "2026-02-30", "2026-13-01", "2026-11-31",
                     "01/11/2026", "2026-1-01", "0000-01-01", "2026-11-01 00:00:00"):
            with self.subTest(data=data):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.evento(conexao, data_competencia=data)
        with self.assertRaises(sqlite3.IntegrityError):
            self.evento(conexao, situacao_competencia="pendente")
        self.evento(conexao, situacao_competencia="pendente", data_competencia=None)
        self.evento(conexao, situacao_competencia="estimada", data_competencia="2024-02-29",
                    chave_origem="estimada:1")

    def test_chave_origem_unica(self):
        conexao = self.migrar_e_conectar()
        self.evento(conexao)
        with self.assertRaises(sqlite3.IntegrityError):
            self.evento(conexao)

    def test_origens_exclusivas_e_unicas(self):
        conexao = self.migrar_e_conectar()
        origens = ("compra_cartao_id", "parcelamento_id", "parcela_comum_id",
                   "ocorrencia_id", "lancamento_legado_id")
        for indice, primeira in enumerate(origens):
            for segunda in origens[indice + 1:]:
                with self.subTest(origens=(primeira, segunda)):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "CHECK constraint failed"):
                        self.evento(conexao, chave_origem="incompativel",
                                    **{primeira: 1, segunda: 1})
        for primeira in origens:
            self.evento(conexao, chave_origem=primeira, **{primeira: 1})
            with self.assertRaises(sqlite3.IntegrityError):
                self.evento(conexao, chave_origem=f"duplicada:{primeira}", **{primeira: 1})

    def test_referencias_de_evento_inexistentes(self):
        conexao = self.migrar_e_conectar()
        for campo in ("categoria_id", "compra_cartao_id", "parcelamento_id",
                      "parcela_comum_id", "ocorrencia_id", "lancamento_legado_id"):
            with self.subTest(campo=campo):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.evento(conexao, **{campo: 999})

    def test_liquidacoes_muitos_para_muitos_e_par_unico(self):
        conexao = self.migrar_e_conectar()
        eventos = [self.evento(conexao, chave_origem=f"evento:{n}") for n in (1, 2)]
        for evento in eventos:
            for lancamento in (1, 2):
                conexao.execute("INSERT INTO liquidacoes_eventos "
                                "(evento_id, lancamento_id, valor_centavos) VALUES (?, ?, 100)",
                                (evento, lancamento))
        self.assertEqual(conexao.execute("SELECT count(*) FROM liquidacoes_eventos").fetchone(), (4,))
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute("INSERT INTO liquidacoes_eventos "
                            "(evento_id, lancamento_id, valor_centavos) VALUES (?, 1, 50)", (eventos[0],))

    def test_liquidacoes_valores_e_referencias_invalidas(self):
        conexao = self.migrar_e_conectar()
        evento = self.evento(conexao)
        for valores in ((evento, 1, 0), (evento, 1, -1), (evento, 1, 1.5),
                        (evento, 1, "abc"), (evento, 1, None),
                        (999, 1, 10), (evento, 999, 10), (None, 1, 10), (evento, None, 10)):
            with self.subTest(valores=valores):
                with self.assertRaises(sqlite3.IntegrityError):
                    conexao.execute("INSERT INTO liquidacoes_eventos "
                                    "(evento_id, lancamento_id, valor_centavos) VALUES (?, ?, ?)", valores)

    def test_exclusoes_restritas_com_fk_habilitada(self):
        conexao = self.migrar_e_conectar()
        evento = self.evento(conexao, compra_cartao_id=1)
        conexao.execute("INSERT INTO liquidacoes_eventos "
                        "(evento_id, lancamento_id, valor_centavos) VALUES (?, 1, 100)", (evento,))
        for sql in ("DELETE FROM eventos_financeiros", "DELETE FROM lancamentos WHERE id = 1",
                    "DELETE FROM compras_cartao WHERE id = 1", "DELETE FROM categorias WHERE id = 1"):
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    conexao.execute(sql)

    def test_indices_e_integridade(self):
        conexao = self.migrar_e_conectar()
        indices = {r[0] for r in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertTrue({"idx_eventos_competencia", "idx_eventos_categoria_competencia",
                         "idx_liquidacoes_lancamento"} <= indices)
        for indice, colunas in {
            "idx_eventos_competencia": ["data_competencia"],
            "idx_eventos_categoria_competencia": ["categoria_id", "data_competencia"],
            "idx_liquidacoes_lancamento": ["lancamento_id"],
        }.items():
            self.assertEqual([r[2] for r in conexao.execute(f'PRAGMA index_info("{indice}")')], colunas)
        unicos = [r[1] for r in conexao.execute("PRAGMA index_list(liquidacoes_eventos)") if r[2]]
        self.assertIn(["evento_id", "lancamento_id"], [
            [r[2] for r in conexao.execute(f'PRAGMA index_info("{i}")')] for i in unicos
        ])
        self.assertEqual(conexao.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(conexao.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_legado_preservado_sem_reconhecimento_automatico(self):
        with closing(banco.abrir_conexao()) as conexao:
            tabelas = [r[0] for r in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            antes = {t: (conexao.execute(f'SELECT * FROM "{t}"').fetchall(),
                         conexao.execute(f'PRAGMA table_info("{t}")').fetchall()) for t in tabelas}
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [1, 2])
        with closing(banco.abrir_conexao()) as conexao:
            for tabela, esperado in antes.items():
                self.assertEqual((conexao.execute(f'SELECT * FROM "{tabela}"').fetchall(),
                                  conexao.execute(f'PRAGMA table_info("{tabela}")').fetchall()), esperado)
            self.assertEqual(conexao.execute("SELECT count(*) FROM eventos_financeiros").fetchone(), (0,))
            self.assertEqual(conexao.execute("SELECT count(*) FROM liquidacoes_eventos").fetchone(), (0,))
            self.assertEqual(conexao.execute("PRAGMA foreign_keys").fetchone(), (0,))

    def test_falha_migracao_2_desfaz_tabelas_indices_e_registro(self):
        versao, nome, sql = banco.MIGRACOES[1]
        catalogo = (banco.MIGRACOES[0], (versao, nome, sql + ("SQL INVALIDO",)))
        with patch.object(banco, "MIGRACOES", catalogo):
            with self.assertRaises(sqlite3.DatabaseError):
                banco.aplicar_migracoes(self.caminho)
        with closing(banco.abrir_conexao()) as conexao:
            self.assertEqual(conexao.execute("SELECT versao FROM esquema_migracoes").fetchall(), [(1,)])
            self.assertEqual(conexao.execute("SELECT name FROM sqlite_master WHERE "
                "name IN ('eventos_financeiros', 'liquidacoes_eventos') OR name LIKE 'idx_eventos_%' "
                "OR name = 'idx_liquidacoes_lancamento'").fetchall(), [])
            self.assertEqual(conexao.execute("SELECT valor FROM lancamentos WHERE id = 1").fetchone(), (12.34,))
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [2])

    TABELAS_PAI = ("categorias", "compras_cartao", "parcelamentos",
                   "parcelamento_parcelas", "recorrencia_ocorrencias", "lancamentos")

    def base_minima(self, destino, ausente=None, ddl_id="id INTEGER PRIMARY KEY", indice=None):
        with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(destino)}):
            with closing(banco.abrir_conexao()) as conexao:
                for tabela in self.TABELAS_PAI:
                    if tabela != ausente:
                        ddl = ddl_id if tabela == "categorias" else "id INTEGER PRIMARY KEY"
                        conexao.execute(f'CREATE TABLE "{tabela}" ({ddl})')
                if indice:
                    conexao.execute(indice)
                conexao.execute("CREATE TABLE dados_preservados (id INTEGER PRIMARY KEY, texto TEXT)")
                conexao.execute("INSERT INTO dados_preservados VALUES (1, 'original')")
                conexao.commit()

    def assert_falha_preserva_base(self, destino, erro="Esquema legado incompativel"):
        with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(destino)}):
            with closing(banco.abrir_conexao()) as conexao:
                tabelas = [r[0] for r in conexao.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")]
                antes = {t: conexao.execute(f'SELECT * FROM "{t}"').fetchall() for t in tabelas}
            with self.assertRaisesRegex(ValueError, erro):
                banco.aplicar_migracoes(destino)
            with closing(banco.abrir_conexao()) as conexao:
                self.assertEqual(conexao.execute("SELECT versao FROM esquema_migracoes").fetchall(), [(1,)])
                for tabela, dados in antes.items():
                    self.assertEqual(conexao.execute(f'SELECT * FROM "{tabela}"').fetchall(), dados)
                self.assertEqual(conexao.execute("SELECT name FROM sqlite_master WHERE name IN "
                    "('eventos_financeiros', 'liquidacoes_eventos', '__kairua_validacao_chave_fk')").fetchall(), [])

    def test_ausencia_individual_das_tabelas_e_retomada(self):
        for tabela in self.TABELAS_PAI:
            with self.subTest(tabela=tabela):
                destino = self.caminho.with_name(f"sem_{tabela}.db")
                self.base_minima(destino, ausente=tabela)
                self.assert_falha_preserva_base(destino, tabela)
                with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(destino)}):
                    with closing(banco.abrir_conexao()) as conexao:
                        conexao.execute(f'CREATE TABLE "{tabela}" (id INTEGER PRIMARY KEY)')
                        conexao.commit()
                    self.assertEqual(banco.aplicar_migracoes(destino), [2])
                    self.assertEqual(banco.aplicar_migracoes(destino), [])

    def test_coluna_referenciada_ausente(self):
        for tabela in self.TABELAS_PAI:
            with self.subTest(tabela=tabela):
                destino = self.caminho.with_name(f"coluna_{tabela}.db")
                self.base_minima(destino, ausente=tabela)
                with closing(sqlite3.connect(destino)) as conexao:
                    conexao.execute(f'CREATE TABLE "{tabela}" (outra INTEGER PRIMARY KEY)')
                    conexao.commit()
                self.assert_falha_preserva_base(destino, "Colunas referenciadas ausentes")

    def test_chaves_incompativeis_sqlite(self):
        casos = (
            ("id INTEGER", None),
            ("id INTEGER, outra INTEGER, PRIMARY KEY (id, outra)", None),
            ("id INTEGER", "CREATE UNIQUE INDEX chave ON categorias(id) WHERE id > 0"),
            ("id INTEGER", "CREATE UNIQUE INDEX chave ON categorias(abs(id))"),
            ("id TEXT COLLATE BINARY", "CREATE UNIQUE INDEX chave ON categorias(id COLLATE NOCASE)"),
        )
        for numero, (ddl, indice) in enumerate(casos):
            with self.subTest(ddl=ddl, indice=indice):
                destino = self.caminho.with_name(f"incompativel_{numero}.db")
                self.base_minima(destino, ddl_id=ddl, indice=indice)
                self.assert_falha_preserva_base(destino)

    def test_chaves_unicas_validas_inclusive_collation(self):
        for numero, (ddl, indice) in enumerate((
            ("id TEXT PRIMARY KEY", None), ("id INTEGER UNIQUE", None),
            ("id TEXT COLLATE NOCASE", "CREATE UNIQUE INDEX chave ON categorias(id COLLATE NOCASE)"),
        )):
            with self.subTest(ddl=ddl):
                destino = self.caminho.with_name(f"unica_{numero}.db")
                self.base_minima(destino, ddl_id=ddl, indice=indice)
                with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(destino)}):
                    self.assertEqual(banco.aplicar_migracoes(destino), [1, 2])

    def test_dependencias_derivadas_do_sql_na_mesma_transacao(self):
        # Uma FK acrescentada ao DDL deve ser descoberta sem lista manual.
        versao, nome, sql = banco.MIGRACOES[1]
        alterado = sql + ("CREATE TABLE origem_extra (id INTEGER PRIMARY KEY, "
                           "externo INTEGER REFERENCES tabela_extra(chave))",)
        with patch.object(banco, "MIGRACOES", (banco.MIGRACOES[0], (versao, nome, alterado))):
            with self.assertRaisesRegex(ValueError, "tabela_extra"):
                banco.aplicar_migracoes(self.caminho)
        with closing(banco.abrir_conexao()) as conexao:
            self.assertEqual(conexao.execute("SELECT name FROM sqlite_master WHERE name IN "
                "('eventos_financeiros', 'liquidacoes_eventos', 'origem_extra')").fetchall(), [])

    def test_precondicao_usa_conexao_do_executor_com_transacao_ativa(self):
        original = banco._validar_dependencias_hibridas
        chamadas = []

        def validar(conexao, sql):
            self.assertTrue(conexao.in_transaction)
            self.assertEqual(conexao.execute("SELECT name FROM sqlite_master WHERE name IN "
                "('eventos_financeiros', 'liquidacoes_eventos')").fetchall(), [])
            self.assertEqual(Path(conexao.execute("PRAGMA database_list").fetchone()[2]), self.caminho)
            chamadas.append(conexao)
            return original(conexao, sql)

        with patch.dict(banco._PRECONDICOES_MIGRACOES, {(2, "esquema_financeiro_hibrido"): validar}):
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [1, 2])
        self.assertEqual(len(chamadas), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            chamadas[0].execute("SELECT 1")

    def test_atualizacoes_rejeitam_check_e_unicidade(self):
        conexao = self.migrar_e_conectar()
        primeiro = self.evento(conexao, chave_origem="primeiro")
        segundo = self.evento(conexao, chave_origem="segundo")
        for campo, valor in (("valor_centavos", 0), ("tipo", "invalido"),
                             ("situacao_competencia", "pendente"),
                             ("data_competencia", "2026-02-29"), ("chave_origem", "segundo")):
            with self.subTest(campo=campo):
                with self.assertRaises(sqlite3.IntegrityError):
                    conexao.execute(f'UPDATE eventos_financeiros SET "{campo}" = ? WHERE id = ?',
                                    (valor, primeiro))
        for evento in (primeiro, segundo):
            conexao.execute("INSERT INTO liquidacoes_eventos "
                            "(evento_id, lancamento_id, valor_centavos) VALUES (?, 1, 100)", (evento,))
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute("UPDATE liquidacoes_eventos SET valor_centavos = -1")
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute("UPDATE liquidacoes_eventos SET evento_id = ? WHERE evento_id = ?",
                            (primeiro, segundo))


if __name__ == "__main__":
    unittest.main()
