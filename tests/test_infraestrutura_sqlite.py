import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import banco


class TestInfraestruturaSQLite(unittest.TestCase):
    def setUp(self):
        # Exercita o executor com o catalogo minimo da etapa 1.
        # O catalogo completo de producao e validado em test_esquema_hibrido.py.
        catalogo = patch.object(banco, "MIGRACOES", banco.MIGRACOES[:1])
        catalogo.start()
        self.addCleanup(catalogo.stop)
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / "infraestrutura.db"
        ambiente = patch.dict(os.environ, {"KAIRUA_DB_PATH": str(self.caminho)})
        ambiente.start()
        self.addCleanup(ambiente.stop)

    def consultar(self, sql):
        with closing(banco.abrir_conexao()) as conexao:
            return conexao.execute(sql).fetchall()

    def inicializar_legado(self):
        banco.criar_banco()
        banco.criar_categorias()
        banco.migrar_categorias()
        banco.migrar_datas()
        banco.criar_recorrencias()
        banco.migrar_lancamentos_recorrencia()
        banco.criar_parcelamentos()
        banco.migrar_lancamentos_parcelamento()
        banco.criar_cartoes()
        banco.criar_faturas()
        banco.criar_compras_cartao()
        banco.criar_parcelas_cartao()

    def test_conexao_respeita_caminho_e_opcoes(self):
        with closing(banco.abrir_conexao()) as conexao:
            self.assertEqual(conexao.execute("PRAGMA database_list").fetchone()[2],
                             str(self.caminho.resolve()))
            self.assertEqual(conexao.execute("PRAGMA foreign_keys").fetchone(), (0,))
            self.assertEqual(conexao.row_factory, None)
        outro = self.caminho.with_name("outro.db")
        with patch.dict(os.environ, {"KAIRUA_DB_PATH": str(outro)}):
            with closing(banco.abrir_conexao()) as conexao:
                self.assertEqual(conexao.execute("PRAGMA database_list").fetchone()[2],
                                 str(outro.resolve()))

    def test_banco_novo_e_reexecucao(self):
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [1])
        antes = self.consultar("SELECT * FROM esquema_migracoes")
        self.assertEqual(antes[0][:2], (1, "controle_de_versoes"))
        self.assertTrue(antes[0][2])
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        self.assertEqual(self.consultar("SELECT * FROM esquema_migracoes"), antes)
        self.assertEqual(self.consultar(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ), [("esquema_migracoes",)])
        self.inicializar_legado()
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        self.assertEqual(len(banco.listar_categorias()), 11)

    def test_legado_preservado_sem_baseline_implicito(self):
        banco.criar_banco()
        with closing(banco.abrir_conexao()) as conexao:
            conexao.execute("INSERT INTO lancamentos VALUES "
                            "(7, '02/11/2026', 'Original', 'despesa', 'Outros', 12.34)")
            conexao.commit()
        dados = self.consultar("SELECT * FROM lancamentos")
        estrutura = self.consultar("PRAGMA table_info(lancamentos)")
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [1])
        self.assertEqual(self.consultar("SELECT * FROM lancamentos"), dados)
        self.assertEqual(self.consultar("PRAGMA table_info(lancamentos)"), estrutura)
        self.inicializar_legado()
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        self.assertEqual(self.consultar("SELECT id, data, valor FROM lancamentos"),
                         [(7, "2026-11-02", 12.34)])
        colunas = {linha[1] for linha in self.consultar("PRAGMA table_info(lancamentos)")}
        self.assertTrue({"categoria_id", "recorrencia_id", "parcelamento_id"} <= colunas)
        self.assertEqual(self.consultar("SELECT versao FROM esquema_migracoes"), [(1,)])

    def test_falha_rollback_ddl_dml_e_retomada(self):
        self.inicializar_legado()
        with closing(banco.abrir_conexao()) as conexao:
            conexao.execute("INSERT INTO lancamentos "
                            "(data, descricao, tipo, categoria, valor) VALUES "
                            "('2026-11-02', 'Preservar', 'despesa', 'Outros', 25)")
            conexao.commit()
        dados = self.consultar("SELECT * FROM lancamentos")
        instrucoes = (
            "ALTER TABLE lancamentos ADD COLUMN teste INTEGER",
            "UPDATE lancamentos SET valor = 999",
            "CREATE TABLE auxiliar (id INTEGER)",
        )
        migracao = (2, "teste_transacional", instrucoes + ("SQL INVALIDO",))
        with patch.object(banco, "MIGRACOES", banco.MIGRACOES + (migracao,)):
            with self.assertRaises(sqlite3.DatabaseError):
                banco.aplicar_migracoes(self.caminho)
        self.assertEqual(self.consultar("SELECT * FROM lancamentos"), dados)
        self.assertNotIn("teste", {r[1] for r in self.consultar("PRAGMA table_info(lancamentos)")})
        self.assertEqual(self.consultar(
            "SELECT name FROM sqlite_master WHERE name = 'auxiliar'"), [])
        self.assertEqual(self.consultar("SELECT versao FROM esquema_migracoes"), [(1,)])
        corrigida = (2, "teste_transacional", instrucoes)
        with patch.object(banco, "MIGRACOES", banco.MIGRACOES + (corrigida,)):
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [2])
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        self.assertEqual(self.consultar("SELECT valor FROM lancamentos"), [(999.0,)])

    def test_falha_primeira_versao_desfaz_bootstrap(self):
        with patch.object(banco, "MIGRACOES", ((1, "falha", (
            "CREATE TABLE parcial (id INTEGER)", "SQL INVALIDO"
        )),)):
            with self.assertRaises(sqlite3.DatabaseError):
                banco.aplicar_migracoes(self.caminho)
        self.assertEqual(self.consultar(
            "SELECT name FROM sqlite_master WHERE type = 'table'"), [])
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [1])

    def test_falha_registro_versao_desfaz_migracao(self):
        banco.aplicar_migracoes(self.caminho)
        with closing(banco.abrir_conexao()) as conexao:
            conexao.execute("CREATE TRIGGER bloquear_versao BEFORE INSERT ON "
                            "esquema_migracoes WHEN NEW.versao = 2 BEGIN "
                            "SELECT RAISE(ABORT, 'falha de registro'); END")
            conexao.commit()
        with patch.object(banco, "MIGRACOES", banco.MIGRACOES + (
            (2, "teste", ("CREATE TABLE parcial (id INTEGER)",)),
        )):
            with self.assertRaises(sqlite3.IntegrityError):
                banco.aplicar_migracoes(self.caminho)
        self.assertEqual(self.consultar(
            "SELECT name FROM sqlite_master WHERE name = 'parcial'"), [])
        self.assertEqual(self.consultar("SELECT versao FROM esquema_migracoes"), [(1,)])

    def test_historico_incompativel_rejeitado(self):
        banco.aplicar_migracoes(self.caminho)
        for versao, nome in ((1, "nome_alterado"), (99, "desconhecida")):
            with self.subTest(versao=versao):
                with closing(banco.abrir_conexao()) as conexao:
                    conexao.execute("DELETE FROM esquema_migracoes")
                    conexao.execute("INSERT INTO esquema_migracoes (versao, nome) VALUES (?, ?)",
                                    (versao, nome))
                    conexao.commit()
                with self.assertRaises(ValueError):
                    banco.aplicar_migracoes(self.caminho)
                self.assertEqual(self.consultar("SELECT versao, nome FROM esquema_migracoes"),
                                 [(versao, nome)])

    def test_catalogo_invalido_rejeitado(self):
        for versoes in ((1, 1), (2, 1), (0,), (True,)):
            with self.subTest(versoes=versoes):
                with patch.object(banco, "MIGRACOES", tuple(
                    (v, "teste", ()) for v in versoes
                )):
                    with self.assertRaises(ValueError):
                        banco.aplicar_migracoes(self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_destino_explicito_obrigatorio_antes_de_conectar(self):
        with patch.object(banco.sqlite3, "connect") as conectar:
            with self.assertRaises(ValueError):
                banco.aplicar_migracoes()
            conectar.assert_not_called()

    def test_destino_explicito_independe_da_variavel_de_ambiente(self):
        outro = self.caminho.with_name("explicito.db")
        self.assertEqual(banco.aplicar_migracoes(outro), [1])
        self.assertFalse(self.caminho.exists())
        with closing(sqlite3.connect(outro)) as conexao:
            self.assertEqual(conexao.execute(
                "SELECT versao FROM esquema_migracoes").fetchall(), [(1,)])

    def test_nome_protegido_e_equivalentes_sem_consultar_arquivo(self):
        # O nome sintetico nunca e aberto; nem a existencia e consultada.
        protegido = self.caminho.with_name("financeiro.db")
        anterior = os.getcwd()
        try:
            os.chdir(self.caminho.parent)
            for destino in (
                "financeiro.db", "./financeiro.db", "sub/../financeiro.db",
                protegido, str(protegido).upper(), "FINANCEIRO.DB. ",
            ):
                with self.subTest(destino=destino):
                    with patch.object(banco.sqlite3, "connect") as conectar:
                        with patch.object(Path, "lstat") as consultar:
                            with self.assertRaises(ValueError):
                                banco.aplicar_migracoes(destino)
                            consultar.assert_not_called()
                        conectar.assert_not_called()
        finally:
            os.chdir(anterior)

    def test_destino_relativo_seguro_e_equivalente_absoluto(self):
        anterior = os.getcwd()
        try:
            os.chdir(self.caminho.parent)
            self.assertEqual(banco.aplicar_migracoes(self.caminho.name), [1])
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        finally:
            os.chdir(anterior)

    def test_aliases_ambiguos_rejeitados(self):
        for destino in ("FINANC~1.DB", "file:teste.db", "teste.db:stream",
                        "//servidor/pasta/teste.db", "teste.db.", "teste.db "):
            with self.subTest(destino=destino):
                with patch.object(banco.sqlite3, "connect") as conectar:
                    with self.assertRaises(ValueError):
                        banco.aplicar_migracoes(destino)
                    conectar.assert_not_called()

    def test_hardlink_rejeitado_sem_abrir_destino(self):
        protegido = self.caminho.with_name("financeiro.db")
        protegido.write_bytes(b"conteudo sintetico preservado")
        try:
            os.link(protegido, self.caminho)
        except (OSError, NotImplementedError) as erro:
            self.skipTest(f"Hardlinks indisponiveis: {erro}")
        with patch.object(banco.sqlite3, "connect") as conectar:
            with self.assertRaises(ValueError):
                banco.aplicar_migracoes(self.caminho)
            conectar.assert_not_called()
        self.assertEqual(protegido.read_bytes(), b"conteudo sintetico preservado")

    def test_link_simbolico_rejeitado_sem_resolver_alvo(self):
        protegido = self.caminho.with_name("financeiro.db")
        protegido.write_bytes(b"sintetico")
        try:
            self.caminho.symlink_to(protegido)
        except (OSError, NotImplementedError) as erro:
            self.skipTest(f"Links simbolicos indisponiveis: {erro}")
        with patch.object(banco.sqlite3, "connect") as conectar:
            with patch.object(Path, "resolve") as resolver:
                with self.assertRaises(ValueError):
                    banco.aplicar_migracoes(self.caminho)
                resolver.assert_not_called()
            conectar.assert_not_called()
        self.assertEqual(protegido.read_bytes(), b"sintetico")

    def test_link_em_diretorio_rejeitado(self):
        diretorio = self.caminho.parent / "alias"
        try:
            diretorio.symlink_to(self.caminho.parent, target_is_directory=True)
        except (OSError, NotImplementedError) as erro:
            self.skipTest(f"Links de diretorio indisponiveis: {erro}")
        with patch.object(banco.sqlite3, "connect") as conectar:
            with self.assertRaises(ValueError):
                banco.aplicar_migracoes(diretorio / "copia.db")
            conectar.assert_not_called()

    def test_incerteza_na_validacao_rejeitada(self):
        with patch.object(Path, "lstat", side_effect=PermissionError("sem acesso")):
            with patch.object(banco.sqlite3, "connect") as conectar:
                with self.assertRaises(ValueError):
                    banco.aplicar_migracoes(self.caminho)
                conectar.assert_not_called()

    def test_historico_deve_ser_prefixo(self):
        banco.aplicar_migracoes(self.caminho)
        catalogo = banco.MIGRACOES + (
            (2, "segunda", ("CREATE TABLE segunda (id INTEGER)",)),
            (3, "terceira", ("CREATE TABLE terceira (id INTEGER)",)),
        )
        for historico in (
            ((1, "controle_de_versoes"), (3, "terceira")),
            ((2, "segunda"), (3, "terceira")),
            ((2, "segunda"),),
        ):
            with self.subTest(historico=historico):
                with closing(banco.abrir_conexao()) as conexao:
                    conexao.execute("DELETE FROM esquema_migracoes")
                    conexao.executemany(
                        "INSERT INTO esquema_migracoes (versao, nome) VALUES (?, ?)",
                        historico)
                    conexao.commit()
                with patch.object(banco, "MIGRACOES", catalogo):
                    with self.assertRaises(ValueError):
                        banco.aplicar_migracoes(self.caminho)
                self.assertEqual(self.consultar(
                    "SELECT versao, nome FROM esquema_migracoes ORDER BY versao"),
                    list(historico))
                self.assertEqual(self.consultar(
                    "SELECT name FROM sqlite_master WHERE name IN ('segunda', 'terceira')"), [])

    def test_prefixo_valido_aplica_somente_pendentes(self):
        catalogo = banco.MIGRACOES + (
            (2, "segunda", ("CREATE TABLE segunda (id INTEGER)",)),
            (3, "terceira", ("CREATE TABLE terceira (id INTEGER)",)),
        )
        with patch.object(banco, "MIGRACOES", catalogo[:2]):
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [1, 2])
        with patch.object(banco, "MIGRACOES", catalogo):
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [3])
            self.assertEqual(banco.aplicar_migracoes(self.caminho), [])

    def test_controle_transacional_proibido_com_comentarios(self):
        banco.aplicar_migracoes(self.caminho)
        for comando in ("bEgIn", "COMMIT", "END", "ROLLBACK", "SAVEPOINT x",
                        "RELEASE x", "ROLLBACK TO x"):
            with self.subTest(comando=comando):
                migracao = (2, "proibida", (
                    "CREATE TABLE parcial (id INTEGER)",
                    f"-- comentario\n /* outro */ {comando};",
                ))
                with patch.object(banco, "MIGRACOES", banco.MIGRACOES + (migracao,)):
                    with self.assertRaises(sqlite3.DatabaseError) as erro:
                        banco.aplicar_migracoes(self.caminho)
                self.assertIn("authorized", str(erro.exception))
                self.assertEqual(self.consultar(
                    "SELECT name FROM sqlite_master WHERE name = 'parcial'"), [])
                self.assertEqual(self.consultar("SELECT versao FROM esquema_migracoes"), [(1,)])

    def test_pragma_attach_e_adulteracao_historico_proibidos(self):
        banco.aplicar_migracoes(self.caminho)
        for comando in ("PRAGMA user_version = 10", "ATTACH ':memory:' AS externo",
                        "DELETE FROM esquema_migracoes"):
            with self.subTest(comando=comando):
                with patch.object(banco, "MIGRACOES", banco.MIGRACOES + (
                    (2, "proibida", (comando,)),
                )):
                    with self.assertRaises(sqlite3.DatabaseError):
                        banco.aplicar_migracoes(self.caminho)
                self.assertEqual(self.consultar("SELECT versao FROM esquema_migracoes"), [(1,)])

    def test_conexao_fechada_apos_excecao(self):
        conexao = sqlite3.connect(self.caminho)
        with patch.object(banco.sqlite3, "connect", return_value=conexao):
            with patch.object(banco, "MIGRACOES", ((1, "falha", ("SQL INVALIDO",)),)):
                with self.assertRaises(sqlite3.DatabaseError):
                    banco.aplicar_migracoes(self.caminho)
        with self.assertRaises(sqlite3.ProgrammingError):
            conexao.execute("SELECT 1")
        self.assertEqual(self.consultar(
            "SELECT name FROM sqlite_master WHERE type = 'table'"), [])


if __name__ == "__main__":
    unittest.main()
