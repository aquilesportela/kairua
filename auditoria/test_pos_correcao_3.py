"""Auditoria adicional; somente fixtures SQLite temporarias, sem alterar producao.

O teste de nomes de tabelas exige rejeicao segura, independentemente da caixa.
Os mutantes em memoria verificam sensibilidade das regressoes, nao sao patches.
"""
import io
import sqlite3
import unittest
from unittest.mock import patch

import test_migracao_3_adversarial as anterior

banco = anterior.banco
migracao_3 = anterior.migracao_3


class PosCorrecao(unittest.TestCase):
    def setUp(self):
        self.a = anterior.AuditoriaAdversarial()
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.f = self.a.f

    def test_f01_identidade_explicita_automatica_e_reversao_duplicada(self):
        self.f.migrar()
        for fk in (0, 1):
            for rt in (0, 1):
                with self.subTest(fk=fk, rt=rt):
                    c = self.f.conectar(fk, rt)
                    e = self.f.evento(c, id=17)
                    op = self.f.op(c, 'reverter_evento')
                    campos = dict(id=500, evento_id=e, operacao_hibrida_id=op,
                                  data_competencia='2026-11-01', categoria_id=1, motivo='Auditoria')
                    self.f.inserir(c, 'reversoes_eventos', campos)
                    self.assertEqual(c.execute('SELECT id,evento_id FROM reversoes_eventos').fetchall(), [(500, 17)])
                    for prefixo in ('INSERT', 'INSERT OR REPLACE'):
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.f.inserir(c, 'reversoes_eventos', {**campos, 'id': 501}, prefixo)
                    outro = self.f.evento(c, id=18)
                    self.f.reverter(c, outro)
                    self.assertEqual(c.execute('SELECT evento_id FROM reversoes_eventos ORDER BY id').fetchall(), [(17,), (18,)])
                    c.rollback()

    def test_f02_unique_composto_com_nome_inesperado(self):
        with self.f.conectar(fk=0) as c:
            c.execute('CREATE UNIQUE INDEX "indice estranho '' detalhe" ON compras_cartao(descricao,valor)')
        self.a.assert_rejeita_sem_alteracoes()

    def recriar_com_capitalizacao(self, c, tabela, nome):
        sql = c.execute('SELECT sql FROM sqlite_master WHERE name=?', (tabela,)).fetchone()[0]
        dados = c.execute(f'SELECT * FROM "{tabela}"').fetchall()
        c.execute(f'DROP TABLE "{tabela}"')
        c.execute(sql.replace(tabela, nome, 1))
        for linha in dados:
            c.execute(f'INSERT INTO "{nome}" VALUES (' + ','.join('?' for _ in linha) + ')', linha)

    def test_n01_rejeita_gatilho_desconhecido_com_tabela_em_maiusculas(self):
        tabelas = ('compras_cartao', 'lancamentos', 'categorias', 'parcelamentos',
                   'recorrencias', 'parcelamento_parcelas', 'recorrencia_ocorrencias')
        for tabela in tabelas:
            mista = ''.join(c.upper() if i % 2 else c.lower() for i, c in enumerate(tabela))
            for nome in (tabela, tabela.upper(), tabela.title(), mista):
                with self.subTest(tabela=tabela, nome=nome):
                    destino = self.f.clone(self.f.chave().replace(':', '_'))
                    with anterior.closing(sqlite3.connect(destino)) as c:
                        self.recriar_com_capitalizacao(c, tabela, nome)
                        c.execute(f'CREATE TRIGGER externo AFTER INSERT ON "{nome}" BEGIN '
                                  "INSERT INTO lancamentos(data,descricao,tipo,categoria,valor,categoria_id) "
                                  "VALUES('2026-11-01','efeito externo','despesa','Teste',9,1); END")
                        c.commit()
                    with patch.object(banco, '_autorizar_instrucao_migracao',
                                      wraps=banco._autorizar_instrucao_migracao) as autorizar:
                        self.a.assert_rejeita_sem_alteracoes(destino)
                    # A recusa deve ser pelo gatilho e anteceder todo SQL da versao 3.
                    with patch.dict(anterior.os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                        with self.assertRaisesRegex(ValueError, 'Gatilhos legados desconhecidos'):
                            banco.aplicar_migracoes(destino)
                    autorizar.assert_not_called()

    def test_n01_aceita_esquemas_sem_gatilhos_adicionais(self):
        for nome in ('compras_cartao', 'COMPRAS_CARTAO', 'Compras_Cartao', 'cOmPrAs_cArTaO'):
            with self.subTest(nome=nome):
                destino = self.f.clone(self.f.chave().replace(':', '_'))
                with anterior.closing(sqlite3.connect(destino)) as c:
                    self.recriar_com_capitalizacao(c, 'compras_cartao', nome)
                    antes = c.execute(f'SELECT * FROM "{nome}"').fetchall()
                    c.commit()
                with patch.dict(anterior.os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    self.assertEqual(banco.aplicar_migracoes(destino), [3])
                    self.assertEqual(banco.aplicar_migracoes(destino), [])
                with anterior.closing(sqlite3.connect(destino)) as c:
                    self.assertEqual(c.execute(f'SELECT * FROM "{nome}"').fetchall(), antes)


class Sensibilidade(unittest.TestCase):
    def verificar_mutante(self, teste, contexto):
        # PASS somente se a regressao detectar a remocao da protecao.
        caso = anterior.AuditoriaAdversarial(teste)
        with contexto:
            resultado = unittest.TextTestRunner(stream=io.StringIO()).run(caso)
        self.assertEqual(resultado.testsRun, 1)
        self.assertFalse(resultado.wasSuccessful(), 'Regressao nao detectou o mutante')

    def test_f01_detecta_chave_primaria_antiga(self):
        sql = list(migracao_3.SQL_MIGRACAO_3)
        for i, instrucao in enumerate(sql):
            if instrucao.startswith('CREATE TABLE reversoes_eventos'):
                sql[i] = instrucao.replace('id INTEGER PRIMARY KEY CHECK (id > 0),\n    evento_id INTEGER NOT NULL UNIQUE', 'evento_id INTEGER PRIMARY KEY')
            if instrucao.startswith('CREATE TRIGGER tr_reversoes_bi'):
                sql[i] = instrucao.replace('(NEW.id > 0 AND id = NEW.id) OR ', '')
        catalogo = banco.MIGRACOES[:2] + ((3, banco.MIGRACOES[2][1], tuple(sql)),)
        # A parte estrutural isola F01 das novas protecoes de IDs de F03.
        class ContratoF01(unittest.TestCase):
            def runTest(caso):
                f = anterior.base.TestMigracao3()
                caso.addCleanup(f.doCleanups)
                f.setUp()
                c = f.migrar()
                info = {r[1]: r for r in c.execute('PRAGMA table_info(reversoes_eventos)')}
                caso.assertIn('id', info)
                caso.assertEqual(info['evento_id'][3:6:2], (1, 0))
        with patch.object(banco, 'MIGRACOES', catalogo):
            resultado = unittest.TextTestRunner(stream=io.StringIO()).run(ContratoF01())
        self.assertEqual(len(resultado.failures), 1)
        self.assertEqual(len(resultado.errors), 0)

    def test_f02_detecta_ausencia_de_validacao_unique(self):
        self.verificar_mutante('test_f02_rejeita_unique_expressao_em_categorias_antes_do_ddl',
                              patch.object(migracao_3, '_UNICIDADES_COBERTAS', {}))

    def test_f03_detecta_operacoes_sem_dominio_positivo(self):
        sql = tuple(s.replace('id INTEGER PRIMARY KEY CHECK (id > 0)', 'id INTEGER PRIMARY KEY')
                    if s.startswith('CREATE TABLE operacoes_hibridas') else s
                    for s in migracao_3.SQL_MIGRACAO_3)
        catalogo = banco.MIGRACOES[:2] + ((3, banco.MIGRACOES[2][1], sql),)
        self.verificar_mutante('test_f03_identificadores_operacoes_e_chaves_idempotentes',
                              patch.object(banco, 'MIGRACOES', catalogo))

    def test_f04_detecta_ausencia_da_tabela_proprietaria(self):
        original = migracao_3._identidade_indice
        def sem_proprietario(c, nome):
            identidade = original(c, nome)
            if nome == 'idx_eventos_competencia':
                return ('eventos_financeiros', *identidade[1:])
            return identidade
        self.verificar_mutante('test_f04_rejeita_indice_esperado_instalado_na_tabela_errada',
                              patch.object(migracao_3, '_identidade_indice', sem_proprietario))


if __name__ == '__main__':
    unittest.main()
