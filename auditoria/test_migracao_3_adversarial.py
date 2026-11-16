"""Regressoes adversariais: PASS exige o bloqueio dos achados F01-F04.

Isolado da descoberta normal em tests/. Nao modifica producao. Todos os bancos
sao temporarios e configurados pelo fixture existente com KAIRUA_DB_PATH.
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
import test_migracao_3 as base
import banco
import migracao_3


class AuditoriaAdversarial(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()

    def test_f01_rejeita_reversao_null_omitida_negativa_ou_de_evento_pago(self):
        # Preserva um evento negativo legitimo da etapa 2, sem reclassifica-lo.
        with self.f.conectar(fk=0) as c:
            c.execute("INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                      "data_competencia,situacao_competencia,chave_origem) "
                      "VALUES (-1,'despesa','Historico negativo',1,100,'2026-11-01','confirmada','negativo')")
        banco.aplicar_migracoes(self.f.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                for identificador in ('omitido', None, -1, 1):
                    with self.subTest(fk=fk, rt=rt, evento_id=identificador):
                        c = self.f.conectar(fk, rt)
                        pago = self.f.evento(c, id=1)
                        self.f.liquidar(c, pago, 1000)
                        op = self.f.op(c, 'reverter_evento')
                        campos = dict(operacao_hibrida_id=op, data_competencia='2026-11-01',
                                      categoria_id=1, motivo='Reproducao de auditoria')
                        if identificador != 'omitido':
                            campos['evento_id'] = identificador
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.f.inserir(c, 'reversoes_eventos', campos)
                        self.assertEqual(c.execute('SELECT count(*) FROM reversoes_eventos').fetchone(), (0,))
                        self.assertEqual(c.execute('SELECT SUM(valor_liquido) FROM _hibrido_liquidacoes '
                                                  'WHERE evento_id = ?', (pago,)).fetchone(), (1000,))
                        c.rollback()
        c = self.f.conectar()
        info = {r[1]: r for r in c.execute('PRAGMA table_info(reversoes_eventos)')}
        self.assertEqual(info['id'][5], 1)
        self.assertEqual(info['evento_id'][5], 0)
        self.assertEqual(info['evento_id'][3], 1)
        self.assertEqual(c.execute("SELECT origem_tipo FROM eventos_financeiros WHERE id = -1").fetchone(), (None,))

    def assert_rejeita_sem_alteracoes(self, destino=None):
        destino = destino or self.f.caminho
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            self._assert_rejeita_destino_isolado(destino)

    def _assert_rejeita_destino_isolado(self, destino):
        with closing(banco.abrir_conexao()) as c:
            esquema = c.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
            antes = {r[1]: c.execute(f'SELECT * FROM "{r[1]}"').fetchall()
                     for r in esquema if r[0] == 'table'}
        with self.assertRaisesRegex(ValueError, 'Esquema incompativel para migracao 3'):
            banco.aplicar_migracoes(destino)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall(), esquema)
            for tabela, dados in antes.items():
                self.assertEqual(c.execute(f'SELECT * FROM "{tabela}"').fetchall(), dados)
            self.assertEqual(c.execute('SELECT versao FROM esquema_migracoes').fetchall(), [(1,), (2,)])
            self.assertFalse({r[1] for r in esquema} & migracao_3.OBJETOS_MIGRACAO_3)

    def test_f02_rejeita_unique_expressao_em_categorias_antes_do_ddl(self):
        with self.f.conectar(fk=0) as c:
            c.execute('CREATE UNIQUE INDEX auditoria_categoria_lower ON categorias(lower(nome))')
        self.assert_rejeita_sem_alteracoes()

    def test_f02_rejeita_unique_adicional_em_compras_antes_do_ddl(self):
        with self.f.conectar(fk=0) as c:
            c.execute('CREATE UNIQUE INDEX auditoria_compra_descricao ON compras_cartao(descricao)')
            c.execute("INSERT INTO eventos_financeiros (tipo,descricao,categoria_id,valor_centavos,"
                      "situacao_competencia,chave_origem,compra_cartao_id) "
                      "VALUES ('despesa','Legado auditado',1,100,'pendente','origem:auditada',1)")
        self.assert_rejeita_sem_alteracoes()

    def test_f02_rejeita_unique_adicional_em_caixa_antes_do_ddl(self):
        with self.f.conectar(fk=0) as c:
            c.execute('CREATE UNIQUE INDEX auditoria_caixa_descricao ON lancamentos(descricao)')
        self.assert_rejeita_sem_alteracoes()

    def test_f03_identificadores_operacoes_e_chaves_idempotentes(self):
        c = self.f.migrar()
        for identificador in (-1, -10, 0):
            with self.subTest(id=identificador):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.f.inserir(c, 'operacoes_hibridas', dict(id=identificador, chave=self.f.chave(),
                        tipo='registrar_evento', requisicao_canonica='{}'))
        self.assertGreater(self.f.op(c, 'registrar_evento'), 0)
        self.assertGreater(self.f.inserir(c, 'operacoes_hibridas', dict(id=None, chave=self.f.chave(),
            tipo='registrar_evento', requisicao_canonica='{}')), 0)
        self.f.inserir(c, 'operacoes_hibridas', dict(id=100, chave='explicita',
            tipo='registrar_evento', requisicao_canonica='{}'))
        for campos in (dict(id=100, chave='outra'), dict(chave='explicita')):
            with self.assertRaises(sqlite3.IntegrityError):
                self.f.inserir(c, 'operacoes_hibridas', dict(tipo='registrar_evento', requisicao_canonica='{}', **campos))
        self.assertGreater(self.f.op(c, 'registrar_evento'), 100)

    def test_f04_rejeita_indice_esperado_instalado_na_tabela_errada(self):
        with self.f.conectar(fk=0) as c:
            c.execute('DROP INDEX idx_eventos_competencia')
            c.execute('CREATE TABLE auditoria_outra (data_competencia TEXT)')
            c.execute('CREATE INDEX idx_eventos_competencia ON auditoria_outra(data_competencia)')
        self.assert_rejeita_sem_alteracoes()

    def test_f02_rejeita_unicidades_nao_cobertas_em_todas_as_tabelas(self):
        alvos = {
            'categorias': 'lower(nome)', 'lancamentos': 'descricao', 'compras_cartao': 'descricao',
            'parcelamentos': 'descricao', 'recorrencias': 'descricao', 'parcelamento_parcelas': 'valor',
            'recorrencia_ocorrencias': 'valor', 'eventos_financeiros': 'categoria_id',
            'liquidacoes_eventos': 'valor_centavos',
        }
        for tabela, expressao in alvos.items():
            with self.subTest(tabela=tabela):
                destino = self.f.clone('unicidade_' + tabela)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        c.execute(f'CREATE UNIQUE INDEX adicional ON {tabela}({expressao})')
                        c.commit()
                self.assert_rejeita_sem_alteracoes(destino)

    def test_f02_rejeita_indices_unicos_parciais_collations_e_expressoes(self):
        for numero, alvo in enumerate((
            'lancamentos(descricao) WHERE valor > 0',
            'categorias(nome COLLATE NOCASE)',
            'categorias(nome DESC)',
            'categorias(substr(nome,1,100))',
            'categorias(nome) WHERE id > 0',
        )):
            with self.subTest(alvo=alvo):
                destino = self.f.clone(f'unico_metadados_{numero}')
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        c.execute(f'CREATE UNIQUE INDEX adicional ON {alvo}')
                        c.commit()
                self.assert_rejeita_sem_alteracoes(destino)

    def test_f02_rejeita_restricao_unique_declarada_no_ddl_legado(self):
        with self.f.conectar(fk=0) as c:
            dados = c.execute('SELECT * FROM compras_cartao').fetchall()
            c.execute('DROP TABLE compras_cartao')
            c.execute('CREATE TABLE compras_cartao (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                      'cartao_id INTEGER NOT NULL, fatura_id INTEGER NOT NULL, categoria_id INTEGER NOT NULL, '
                      'descricao TEXT NOT NULL UNIQUE, data_compra TEXT NOT NULL, valor REAL NOT NULL)')
            c.executemany('INSERT INTO compras_cartao VALUES (?,?,?,?,?,?,?)', dados)
        self.assert_rejeita_sem_alteracoes()

    def test_f02_aceita_indices_nao_unicos_e_unicidade_equivalente_coberta(self):
        with self.f.conectar(fk=0) as c:
            c.execute('CREATE INDEX pesquisa_descricao ON lancamentos(descricao)')
            c.execute('CREATE INDEX pesquisa_expressao ON compras_cartao(lower(descricao)) WHERE valor > 0')
            c.execute('CREATE UNIQUE INDEX duplicata_coberta ON categorias(nome)')
        self.assertEqual(banco.aplicar_migracoes(self.f.caminho), [3])
        self.assertEqual(banco.aplicar_migracoes(self.f.caminho), [])

    def test_f04_rejeita_ordem_unicidade_parcialidade_expressao_e_collation(self):
        for numero, (nome, alvo, unico) in enumerate((
            ('idx_eventos_competencia', 'eventos_financeiros(data_competencia DESC)', False),
            ('idx_eventos_competencia', 'eventos_financeiros(data_competencia COLLATE NOCASE)', False),
            ('idx_eventos_competencia', 'eventos_financeiros(data_competencia) WHERE id > 0', False),
            ('idx_eventos_competencia', 'eventos_financeiros(lower(data_competencia))', False),
            ('idx_eventos_competencia', 'eventos_financeiros(data_competencia)', True),
            ('idx_eventos_categoria_competencia', 'eventos_financeiros(data_competencia,categoria_id)', False),
        )):
            with self.subTest(nome=nome, alvo=alvo):
                destino = self.f.clone(f'identidade_{numero}')
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        c.execute(f'DROP INDEX {nome}')
                        c.execute(f'CREATE {"UNIQUE " if unico else ""}INDEX {nome} ON {alvo}')
                        c.commit()
                self.assert_rejeita_sem_alteracoes(destino)

    def test_f03_ids_hibridos_negativos_zero_positivos_e_automaticos(self):
        c = self.f.migrar()
        for identificador in (-1, -7, 0):
            with self.subTest(id=identificador):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.f.evento(c, id=identificador)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.f.caixa(c, id=identificador)
        e = self.f.evento(c, id=100)
        l = self.f.caixa(c, id=100)
        for identificador in (-1, -7, 0):
            with self.assertRaises(sqlite3.IntegrityError):
                self.f.inserir(c, 'liquidacoes_eventos', dict(id=identificador, evento_id=e,
                    lancamento_id=l, valor_centavos=1000))
        q = self.f.inserir(c, 'liquidacoes_eventos', dict(id=100, evento_id=e, lancamento_id=l, valor_centavos=1000))
        retorno = self.f.caixa(c, centavos=-1000)
        for identificador in (-1, -7, 0):
            with self.assertRaises(sqlite3.IntegrityError):
                self.f.inserir(c, 'estornos_liquidacoes', dict(id=identificador, liquidacao_id=q,
                    lancamento_estorno_id=retorno, natureza='correcao_registro', motivo='x'))
        self.f.inserir(c, 'estornos_liquidacoes', dict(id=100, liquidacao_id=q,
            lancamento_estorno_id=retorno, natureza='correcao_registro', motivo='x'))
        op = self.f.op(c, 'reverter_evento')
        for identificador in (-1, -7, 0):
            with self.assertRaises(sqlite3.IntegrityError):
                self.f.inserir(c, 'reversoes_eventos', dict(id=identificador, evento_id=e,
                    operacao_hibrida_id=op, data_competencia='2026-11-01', categoria_id=1, motivo='x'))
        self.f.inserir(c, 'reversoes_eventos', dict(id=100, evento_id=e, operacao_hibrida_id=op,
            data_competencia='2026-11-01', categoria_id=1, motivo='x'))
        outro = self.f.evento(c)
        self.assertGreater(outro, 100)
        for identificador in (-1, -7, 0):
            with self.assertRaises(sqlite3.IntegrityError):
                self.f.reclassificar(c, outro, 2, id=identificador)
        self.f.reclassificar(c, outro, 2, id=100)
        self.f.reclassificar(c, outro, 3)
        with self.assertRaises(sqlite3.IntegrityError):
            self.f.evento(c, id=100)
        with self.assertRaises(sqlite3.IntegrityError):
            self.f.caixa(c, id=100)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'liquidacao_duplicada'):
            self.f.inserir(c, 'liquidacoes_eventos', dict(id=100, evento_id=outro,
                lancamento_id=self.f.caixa(c), valor_centavos=1000), 'INSERT OR REPLACE')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'estorno_duplicado'):
            self.f.inserir(c, 'estornos_liquidacoes', dict(id=100, liquidacao_id=q,
                lancamento_estorno_id=self.f.caixa(c, centavos=-100),
                natureza='correcao_registro', motivo='x'), 'INSERT OR REPLACE')
        outro_evento = self.f.evento(c)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'evento_ja_revertido'):
            self.f.inserir(c, 'reversoes_eventos', dict(id=100, evento_id=outro_evento,
                operacao_hibrida_id=self.f.op(c, 'reverter_evento'), data_competencia='2026-11-01',
                categoria_id=1, motivo='x'), 'INSERT OR REPLACE')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'reclassificacao_duplicada'):
            self.f.reclassificar(c, outro_evento, 2, id=100)

    def test_f03_dominio_positivo_nao_reinterpreta_historico_somente_negativo(self):
        # Nao se reconstroi a tabela nem se semeia um evento artificial para
        # alterar o alocador de rowid do SQLite em uma base historica negativa.
        with self.f.conectar(fk=0) as c:
            c.execute("INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                      "situacao_competencia,chave_origem) VALUES (-1,'despesa','Antigo',1,100,'pendente','negativo')")
        c = self.f.migrar()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'identificador_hibrido_invalido'):
            self.f.evento(c)  # SQLite atribuiria 0, fora do dominio hibrido.
        self.assertEqual(self.f.evento(c, id=1), 1)
        self.assertGreater(self.f.evento(c), 1)
        self.assertEqual(c.execute('SELECT origem_tipo FROM eventos_financeiros WHERE id = -1').fetchone(), (None,))

    def test_f03_ids_negativos_legados_nao_bloqueiam_cadastro_e_ficam_protegidos(self):
        with self.f.conectar(fk=0) as c:
            c.execute("INSERT INTO lancamentos (id,data,descricao,tipo,categoria,valor,categoria_id) "
                      "VALUES (-1,'2026-11-01','Negativo','despesa','Antiga',1,1)")
            c.execute("INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                      "situacao_competencia,chave_origem,lancamento_legado_id) "
                      "VALUES (-1,'despesa','Antigo',1,100,'pendente','antigo:caixa',-1)")
            c.execute("INSERT INTO categorias VALUES (-1,'Negativa usada','despesa')")
            c.execute("INSERT INTO compras_cartao VALUES (-1,1,1,-1,'Negativa','2026-11-01',1)")
            c.execute("INSERT INTO parcelamentos (id,descricao,tipo,categoria_id,valor_total,quantidade_parcelas,data_inicio) "
                      "VALUES (-1,'Negativo','despesa',1,100,1,'2026-11-01')")
            c.execute("INSERT INTO parcelamento_parcelas (id,parcelamento_id,numero_parcela,data_vencimento,valor) "
                      "VALUES (-1,1,2,'2026-12-01',20)")
            c.execute("INSERT INTO recorrencia_ocorrencias (id,recorrencia_id,data_vencimento,valor) "
                      "VALUES (-1,1,'2026-12-01',20)")
            for i, campo in enumerate(('compra_cartao_id','parcelamento_id','parcela_comum_id','ocorrencia_id'), 50):
                c.execute(f"INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                          f"situacao_competencia,chave_origem,{campo}) VALUES (?,'despesa','Antigo',1,100,'pendente',?,-1)",
                          (i, f'antigo:{campo}'))
        banco.aplicar_migracoes(self.f.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                with self.subTest(fk=fk, rt=rt):
                    c = self.f.conectar(fk, rt)
                    novos = {
                        'categorias': dict(nome='Categoria nova', tipo='despesa'),
                        'lancamentos': dict(data='2026-11-01', descricao='Novo legado', tipo='despesa',
                                            categoria='Antiga', categoria_id=1, valor=1),
                        'compras_cartao': dict(cartao_id=1,fatura_id=1,categoria_id=1,descricao='Nova',data_compra='2026-11-01',valor=1),
                        'parcelamentos': dict(descricao='Novo',tipo='despesa',categoria_id=1,valor_total=1,
                                               quantidade_parcelas=1,data_inicio='2026-11-01'),
                        'parcelamento_parcelas': dict(parcelamento_id=1,numero_parcela=3,data_vencimento='2027-01-01',valor=1),
                        'recorrencia_ocorrencias': dict(recorrencia_id=1,data_vencimento='2027-01-01',valor=1),
                    }
                    for tabela, campos in novos.items():
                        registro = c.execute(f'SELECT * FROM {tabela} WHERE id = -1').fetchone()
                        novo = self.f.inserir(c, tabela, campos)
                        self.assertGreater(novo, 0)
                        campos['id'] = -1
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.f.inserir(c, tabela, campos, 'INSERT OR REPLACE')
                        with self.assertRaises(sqlite3.IntegrityError):
                            c.execute(f'UPDATE OR REPLACE {tabela} SET id = -1 WHERE id = ?', (novo,))
                        self.assertEqual(c.execute(f'SELECT * FROM {tabela} WHERE id = -1').fetchone(), registro)
                    self.assertGreater(self.f.evento(c), 0)
                    c.rollback()

    def test_controle_autorizador_excecao_restrita_e_rollback(self):
        permitido = next(iter(migracao_3.ALTERS_COM_CHECK_MIGRACAO_3))
        tabela = migracao_3.ALTERS_COM_CHECK_MIGRACAO_3[permitido]
        for versao, nome, sql in (
            (3, 'contrato_operacoes_hibridas', permitido + ' -- alterado'),
            (2, 'esquema_financeiro_hibrido', permitido),
            (3, 'nome_errado', permitido),
            (3, 'contrato_operacoes_hibridas', f'PRAGMA quick_check({tabela})'),
        ):
            autorizar = banco._autorizar_instrucao_migracao(versao, nome, sql)
            self.assertEqual(autorizar(sqlite3.SQLITE_PRAGMA, 'quick_check', tabela, 'main', None), sqlite3.SQLITE_DENY)
        autorizar = banco._autorizar_instrucao_migracao(3, 'contrato_operacoes_hibridas', permitido)
        self.assertEqual(autorizar(sqlite3.SQLITE_PRAGMA, 'quick_check', tabela, 'main', None), sqlite3.SQLITE_OK)
        for acao, a, b, schema, origem in (
            (sqlite3.SQLITE_TRANSACTION, 'COMMIT', None, None, None),
            (sqlite3.SQLITE_SAVEPOINT, 'BEGIN', 'x', None, None),
            (sqlite3.SQLITE_PRAGMA, 'foreign_keys', 'OFF', None, None),
            (sqlite3.SQLITE_PRAGMA, 'quick_check', 'outra', 'main', None),
            (sqlite3.SQLITE_PRAGMA, 'quick_check', tabela, 'temp', None),
        ):
            self.assertEqual(autorizar(acao, a, b, schema, origem), sqlite3.SQLITE_DENY)
        # Controle de execucao real, alem dos callbacks acima.
        self.f.test_permissao_interna_quick_check_nao_libera_sql_arbitrario()
        print('C01: PRAGMAs explicitos/transacoes bloqueados e rollback da versao 3 confirmado.')

    def test_controle_concorrencia_e_revalidacao_do_saldo(self):
        c1 = self.f.migrar()
        evento = self.f.evento(c1)
        c1.commit()
        c2 = self.f.conectar()
        c2.execute('PRAGMA busy_timeout = 0')
        c1.execute('BEGIN IMMEDIATE')
        self.f.liquidar(c1, evento, 700)
        with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
            self.f.liquidar(c2, evento, 301)
        c2.rollback()
        c1.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.f.liquidar(c2, evento, 301)
        self.assertEqual(c2.execute('SELECT SUM(valor_liquido) FROM _hibrido_liquidacoes WHERE evento_id = ?',
                                   (evento,)).fetchone(), (700,))
        print('C02: escritas serializadas; excesso rejeitado depois de adquirir a escrita.')

    def test_controle_updates_replace_e_limites_originalmente_previstos(self):
        banco.aplicar_migracoes(self.f.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                c = self.f.conectar(fk, rt)
                evento = self.f.evento(c)
                lanc = self.f.caixa(c)
                q = self.f.liquidar(c, evento, 1000, lanc)
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute('UPDATE OR REPLACE lancamentos SET id = ? WHERE id = 2', (lanc,))
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute("UPDATE OR REPLACE categorias SET nome = (SELECT nome FROM categorias WHERE id = 1) WHERE id = 11")
                self.f.estornar(c, q, 400)
                self.f.estornar(c, q, 600)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.f.estornar(c, q, 1)
                c.rollback()
        print('C03: UPDATE OR REPLACE por chaves conhecidas e excesso de estorno bloqueados nas quatro configuracoes.')

    def test_inventario_dos_gatilhos_apos_as_correcoes(self):
        c = self.f.migrar()
        esperados = {'tr_operacoes_bi', 'tr_operacoes_bu', 'tr_operacoes_bd', 'tr_reclassificacoes_ai'}
        for prefixo in ('eventos', 'lancamentos', 'liquidacoes', 'estornos', 'reversoes', 'reclassificacoes', 'categorias'):
            esperados.update(f'tr_{prefixo}_{s}' for s in ('bi', 'bu', 'bd'))
        for prefixo in ('compras', 'parcelamentos', 'parcelas', 'ocorrencias'):
            esperados.update(f'tr_{prefixo}_origem_{s}' for s in ('bi', 'bu', 'bd'))
            esperados.add(f'tr_{prefixo}_origem_ai')
        esperados.update(('tr_eventos_ai', 'tr_lancamentos_ai', 'tr_liquidacoes_ai', 'tr_categorias_ai'))
        atuais = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        self.assertEqual(len(esperados), 45)
        self.assertEqual(atuais, esperados)


if __name__ == '__main__':
    unittest.main()
