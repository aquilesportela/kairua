import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import banco
import migracao_3
import test_esquema_hibrido as etapa2


class TestMigracao3(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = Path(pasta.name) / 'etapa3_teste.db'
        ambiente = patch.dict(os.environ, {'KAIRUA_DB_PATH': str(self.caminho)})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.catalogo = banco.MIGRACOES
        etapa2.TestEsquemaHibrido.preparar_legado(self)
        with patch.object(banco, 'MIGRACOES', self.catalogo[:2]):
            banco.aplicar_migracoes(self.caminho)
        self.numero = 0

    def chave(self):
        self.numero += 1
        return f'teste:{self.numero}'

    def conectar(self, fk=1, recursivos=1):
        conexao = banco.abrir_conexao()
        self.addCleanup(conexao.close)
        conexao.execute(f'PRAGMA foreign_keys = {fk}')
        conexao.execute(f'PRAGMA recursive_triggers = {recursivos}')
        self.assertEqual(conexao.execute('PRAGMA foreign_keys').fetchone(), (fk,))
        self.assertEqual(conexao.execute('PRAGMA recursive_triggers').fetchone(), (recursivos,))
        return conexao

    def migrar(self, fk=1, recursivos=1):
        banco.aplicar_migracoes(self.caminho)
        return self.conectar(fk, recursivos)

    def op(self, c, tipo, estado='aberta'):
        return c.execute('INSERT INTO operacoes_hibridas '
                         '(chave, tipo, requisicao_canonica, estado) VALUES (?, ?, ?, ?)',
                         (self.chave(), tipo, '{}', estado)).lastrowid

    def evento(self, c, operacao=None, **mudancas):
        if operacao is None:
            operacao = self.op(c, 'registrar_evento')
        campos = dict(tipo='despesa', descricao='Manual', categoria_id=1, valor_centavos=1000,
                      data_competencia='2026-11-01', situacao_competencia='confirmada',
                      chave_origem=self.chave(), operacao_hibrida_id=operacao,
                      data_vencimento='2026-12-01', origem_tipo='manual')
        campos.update(mudancas)
        return self.inserir(c, 'eventos_financeiros', campos)

    def inserir(self, c, tabela, campos, prefixo='INSERT'):
        return c.execute(f'{prefixo} INTO {tabela} ({", ".join(campos)}) '
                         f'VALUES ({", ".join("?" for _ in campos)})', tuple(campos.values())).lastrowid

    def caixa(self, c, operacao=None, centavos=1000, **mudancas):
        if operacao is None:
            operacao = self.op(c, 'liquidar_evento' if centavos > 0 else 'estornar_liquidacao')
        campos = dict(data='2026-11-01', descricao='Caixa manual', tipo='despesa', categoria_id=1,
                      categoria=c.execute('SELECT nome FROM categorias WHERE id = 1').fetchone()[0],
                      operacao_hibrida_id=operacao, valor_centavos=centavos)
        campos.update(mudancas)
        # O valor REAL e somente projecao: a fonte do teste e o inteiro.
        if 'valor' not in campos:
            colunas = ', '.join(campos)
            parametros = ', '.join('?' for _ in campos)
            return c.execute(f'INSERT INTO lancamentos ({colunas}, valor) '
                             f'VALUES ({parametros}, CAST(? AS REAL) / 100.0)',
                             (*campos.values(), centavos)).lastrowid
        return self.inserir(c, 'lancamentos', campos)

    def liquidar(self, c, evento, valor, lancamento=None):
        if lancamento is None:
            lancamento = self.caixa(c, centavos=valor)
        return c.execute('INSERT INTO liquidacoes_eventos '
                         '(evento_id, lancamento_id, valor_centavos) VALUES (?, ?, ?)',
                         (evento, lancamento, valor)).lastrowid

    def estornar(self, c, liquidacao, valor, natureza='devolucao_real', data='2026-11-02'):
        original = c.execute('SELECT l.tipo, l.categoria_id, l.categoria FROM lancamentos l '
                             'JOIN liquidacoes_eventos q ON q.lancamento_id = l.id WHERE q.id = ?',
                             (liquidacao,)).fetchone()
        retorno = self.caixa(c, centavos=-valor, tipo=original[0], categoria_id=original[1],
                            categoria=original[2], data=data)
        return self.inserir(c, 'estornos_liquidacoes', dict(liquidacao_id=liquidacao,
            lancamento_estorno_id=retorno, natureza=natureza, motivo='Motivo documentado'))

    def reverter(self, c, evento, operacao=None):
        if operacao is None:
            operacao = self.op(c, 'reverter_evento')
        categoria = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id = ?',
                              (evento,)).fetchone()[0]
        return self.inserir(c, 'reversoes_eventos', dict(evento_id=evento,
            operacao_hibrida_id=operacao, data_competencia='2026-11-01', categoria_id=categoria, motivo='Reversao'))

    def reclassificar(self, c, evento, nova, **mudancas):
        anterior = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id = ?',
                             (evento,)).fetchone()[0]
        campos = dict(evento_id=evento, operacao_hibrida_id=self.op(c, 'reclassificar_evento'),
                      categoria_anterior_id=anterior, categoria_nova_id=nova, motivo='Reclassificacao')
        campos.update(mudancas)
        return self.inserir(c, 'reclassificacoes_eventos', campos)

    def test_aplicacao_reexecucao_e_preservacao_historica(self):
        with closing(banco.abrir_conexao()) as c:
            tabelas = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            antes = {t: c.execute(f'SELECT * FROM "{t}"').fetchall() for t in tabelas}
            c.execute("INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                      "situacao_competencia,chave_origem) VALUES (50,'despesa','Historico',1,100,'pendente','legado')")
            c.commit()
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [3])
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [])
        c = self.conectar()
        for tabela, dados in antes.items():
            if tabela in ('eventos_financeiros', 'esquema_migracoes'):
                continue
            depois = c.execute(f'SELECT * FROM "{tabela}"').fetchall()
            if tabela == 'lancamentos':
                self.assertEqual([r[:-2] for r in depois], dados)
                self.assertTrue(all(r[-2:] == (None, None) for r in depois))
            else:
                self.assertEqual(depois, dados)
        self.assertEqual(c.execute('SELECT operacao_hibrida_id,data_vencimento,origem_tipo '
                                   'FROM eventos_financeiros WHERE id = 50').fetchone(), (None, None, None))
        self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (0,))

    def test_rollback_em_diferentes_pontos_do_ddl(self):
        sql = migracao_3.SQL_MIGRACAO_3
        for ponto in (1, 4, 10, len(sql) // 2, len(sql)):
            with self.subTest(ponto=ponto):
                quebrada = sql[:ponto] + ('SQL INVALIDO',) + sql[ponto:]
                with patch.object(banco, 'MIGRACOES', self.catalogo[:2] + ((3, self.catalogo[2][1], quebrada),)):
                    with self.assertRaises(sqlite3.DatabaseError):
                        banco.aplicar_migracoes(self.caminho)
                with closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT versao FROM esquema_migracoes').fetchall(), [(1,), (2,)])
                    objetos = {r[0] for r in c.execute('SELECT name FROM sqlite_master')}
                    self.assertFalse(objetos & migracao_3.OBJETOS_MIGRACAO_3)
                    self.assertNotIn('valor_centavos', {r[1] for r in c.execute('PRAGMA table_info(lancamentos)')})
                    self.assertEqual(c.execute('SELECT valor FROM lancamentos WHERE id = 1').fetchone(), (12.34,))
        self.assertEqual(banco.aplicar_migracoes(self.caminho), [3])

    def clone(self, nome):
        destino = self.caminho.with_name(nome + '.db')
        with closing(banco.abrir_conexao()) as origem, closing(sqlite3.connect(destino)) as copia:
            origem.backup(copia)
        return destino

    def test_precondicao_rejeita_incompatibilidades_sem_criar_objetos(self):
        for numero, sql in enumerate((
            'DROP TABLE recorrencias',
            'DROP INDEX idx_eventos_competencia',
            'CREATE VIEW OPERACOES_HIBRIDAS AS SELECT 1',
            'ALTER TABLE lancamentos ADD COLUMN valor_centavos INTEGER',
            'ALTER TABLE categorias RENAME COLUMN tipo TO natureza',
            'CREATE TRIGGER gatilho_desconhecido AFTER INSERT ON lancamentos BEGIN SELECT 1; END',
        )):
            with self.subTest(sql=sql):
                destino = self.clone(f'incompativel_{numero}')
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        c.execute(sql)
                        c.commit()
                    with self.assertRaisesRegex(ValueError, 'Esquema incompativel para migracao 3'):
                        banco.aplicar_migracoes(destino)
                    with closing(banco.abrir_conexao()) as c:
                        self.assertEqual(c.execute('SELECT versao FROM esquema_migracoes').fetchall(), [(1,), (2,)])
                        self.assertNotIn('origem_tipo', {r[1] for r in c.execute('PRAGMA table_info(eventos_financeiros)')})

    def test_datas_valores_e_projecao_canonica(self):
        c = self.migrar()
        for mudancas in ({'data_competencia': '2026-02-29'}, {'data_vencimento': '2026-02-30'},
                         {'data_vencimento': None}, {'situacao_competencia': 'estimada'},
                         {'origem_tipo': None}, {'compra_cartao_id': 1}, {'valor_centavos': 1.5},
                         {'valor_centavos': 0}, {'categoria_id': 999}):
            with self.subTest(mudancas=mudancas):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.evento(c, **mudancas)
        self.evento(c, data_competencia='2024-02-29', data_vencimento='2024-03-01')
        for mudancas in ({'valor': 10.001}, {'valor': None}, {'valor_centavos': None},
                         {'valor_centavos': 'abc'}, {'centavos': 0}, {'centavos': -(2**63)},
                         {'data': '2026-02-29'}, {'tipo': 'receita'}, {'recorrencia_id': 1}):
            with self.subTest(caixa=mudancas):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.caixa(c, **mudancas)
        for centavos in (1, 101, 12345):
            linha = self.caixa(c, centavos=centavos)
            self.assertEqual(c.execute('SELECT valor = CAST(valor_centavos AS REAL)/100.0 '
                                       'FROM lancamentos WHERE id = ?', (linha,)).fetchone(), (1,))

    def test_limites_liquidacao_estorno_e_reversao_em_todas_as_configuracoes(self):
        banco.aplicar_migracoes(self.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                with self.subTest(fk=fk, recursive_triggers=rt):
                    c = self.conectar(fk, rt)
                    evento = self.evento(c)
                    q = self.liquidar(c, evento, 700)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.liquidar(c, evento, 301)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.reverter(c, evento)
                    self.estornar(c, q, 200)
                    self.assertEqual(c.execute('SELECT valor_liquido FROM _hibrido_liquidacoes WHERE id = ?', (q,)).fetchone(), (500,))
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.estornar(c, q, 501)
                    self.estornar(c, q, 500)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.estornar(c, q, 1)
                    self.reverter(c, evento)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.reverter(c, evento)
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.liquidar(c, evento, 1)
                    c.rollback()

    def test_liquidacao_integral_e_caixa_nao_reutilizavel(self):
        c = self.migrar()
        evento = self.evento(c)
        lanc = self.caixa(c)
        q = self.liquidar(c, evento, 1000, lanc)
        with self.assertRaises(sqlite3.IntegrityError):
            self.liquidar(c, evento, 1)
        self.estornar(c, q, 1000)
        outro = self.evento(c)
        with self.assertRaises(sqlite3.IntegrityError):
            self.liquidar(c, outro, 1, lanc)
        self.liquidar(c, evento, 1000)

    def test_estorno_distingue_devolucao_e_correcao_sem_receita_artificial(self):
        c = self.migrar()
        evento = self.evento(c)
        q = self.liquidar(c, evento, 1000)
        with self.assertRaises(sqlite3.IntegrityError):
            self.estornar(c, q, 100, natureza='correcao_registro', data='2026-11-02')
        with self.assertRaises(sqlite3.IntegrityError):
            self.estornar(c, q, 100, data='2026-10-31')
        self.estornar(c, q, 100, natureza='correcao_registro', data='2026-11-01')
        self.estornar(c, q, 100, natureza='devolucao_real', data='2026-11-02')
        self.assertEqual(c.execute('SELECT DISTINCT l.tipo FROM estornos_liquidacoes s '
                                   'JOIN lancamentos l ON l.id = s.lancamento_estorno_id').fetchall(), [('despesa',)])
        self.assertEqual(c.execute('SELECT valor_liquido FROM _hibrido_liquidacoes WHERE id = ?', (q,)).fetchone(), (800,))
        estorno = c.execute('SELECT * FROM estornos_liquidacoes LIMIT 1').fetchone()
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute('INSERT INTO estornos_liquidacoes (liquidacao_id,lancamento_estorno_id,natureza,motivo) '
                      'VALUES (?,?,?,?)', estorno[1:])

    def test_reclassificacao_sequencial_sem_alterar_evento_ou_caixa(self):
        c = self.migrar()
        evento = self.evento(c)
        q = self.liquidar(c, evento, 500)
        original = c.execute('SELECT * FROM eventos_financeiros WHERE id = ?', (evento,)).fetchone()
        self.reclassificar(c, evento, 2, id=100)
        self.reclassificar(c, evento, 3)
        self.assertEqual(c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id = ?', (evento,)).fetchone(), (3,))
        self.assertEqual(c.execute('SELECT * FROM eventos_financeiros WHERE id = ?', (evento,)).fetchone(), original)
        with self.assertRaises(sqlite3.IntegrityError):
            self.reclassificar(c, evento, 2, id=50)
        with self.assertRaises(sqlite3.IntegrityError):
            self.reclassificar(c, evento, 2, categoria_anterior_id=1)
        receita = c.execute("SELECT id FROM categorias WHERE tipo = 'receita' LIMIT 1").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.reclassificar(c, evento, receita)
        self.estornar(c, q, 500)
        self.reverter(c, evento)
        with self.assertRaises(sqlite3.IntegrityError):
            self.reclassificar(c, evento, 2)

    def test_imutabilidade_e_replace_com_flags_ligadas_e_desligadas(self):
        banco.aplicar_migracoes(self.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                with self.subTest(fk=fk, rt=rt):
                    c = self.conectar(fk, rt)
                    evento = self.evento(c)
                    q = self.liquidar(c, evento, 500)
                    self.reclassificar(c, evento, 2)
                    self.estornar(c, q, 500)
                    self.reverter(c, evento)
                    for tabela, campo in (
                        ('eventos_financeiros', 'descricao'), ('liquidacoes_eventos', 'valor_centavos'),
                        ('estornos_liquidacoes', 'motivo'), ('reversoes_eventos', 'motivo'),
                        ('reclassificacoes_eventos', 'motivo'),
                    ):
                        for sql in (f'UPDATE {tabela} SET {campo} = {campo}', f'DELETE FROM {tabela}',
                                    f'INSERT OR REPLACE INTO {tabela} SELECT * FROM {tabela} LIMIT 1'):
                            with self.subTest(sql=sql):
                                with self.assertRaises(sqlite3.IntegrityError):
                                    c.execute(sql)
                    for sql in (
                        'UPDATE operacoes_hibridas SET chave = chave', 'DELETE FROM operacoes_hibridas',
                        'INSERT OR REPLACE INTO operacoes_hibridas SELECT * FROM operacoes_hibridas LIMIT 1',
                        'UPDATE lancamentos SET valor = 99 WHERE operacao_hibrida_id IS NOT NULL',
                        'DELETE FROM lancamentos WHERE operacao_hibrida_id IS NOT NULL',
                        'INSERT OR REPLACE INTO lancamentos SELECT * FROM lancamentos WHERE operacao_hibrida_id IS NOT NULL LIMIT 1',
                    ):
                        with self.subTest(sql=sql):
                            with self.assertRaises(sqlite3.IntegrityError):
                                c.execute(sql)
                    c.rollback()

    def test_referencias_inexistentes_sao_rejeitadas_com_fk_off(self):
        c = self.migrar(fk=0, recursivos=0)
        for acao in (
            lambda: self.evento(c, operacao=999), lambda: self.caixa(c, operacao=999),
            lambda: self.liquidar(c, 999, 100),
            lambda: self.inserir(c, 'estornos_liquidacoes', dict(liquidacao_id=999,
                lancamento_estorno_id=999, natureza='devolucao_real', motivo='x')),
            lambda: self.inserir(c, 'reversoes_eventos', dict(evento_id=999,
                operacao_hibrida_id=999, data_competencia='2026-11-01', categoria_id=1, motivo='x')),
            lambda: self.inserir(c, 'reclassificacoes_eventos', dict(evento_id=999,
                operacao_hibrida_id=999, categoria_anterior_id=1, categoria_nova_id=2, motivo='x')),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                acao()

    def test_operacao_concluida_recusa_novos_efeitos(self):
        c = self.migrar()
        for tipo in ('registrar_evento', 'registrar_imediata', 'liquidar_evento',
                     'estornar_liquidacao', 'reverter_evento', 'reclassificar_evento'):
            op = self.op(c, tipo)
            c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE operacoes_hibridas SET estado = 'aberta' WHERE id = ?", (op,))
            with self.assertRaises(sqlite3.IntegrityError):
                self.evento(c, operacao=op)
            with self.assertRaises(sqlite3.IntegrityError):
                self.caixa(c, operacao=op, centavos=-100 if tipo == 'estornar_liquidacao' else 100)
        evento = self.evento(c)
        op = self.op(c, 'liquidar_evento')
        lanc = self.caixa(c, op, 100)
        c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.liquidar(c, evento, 100, lanc)
        q = self.liquidar(c, evento, 100)
        op = self.op(c, 'estornar_liquidacao')
        retorno = self.caixa(c, op, -100)
        c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.inserir(c, 'estornos_liquidacoes', dict(liquidacao_id=q, lancamento_estorno_id=retorno,
                natureza='devolucao_real', motivo='x'))
        op = self.op(c, 'reverter_evento')
        c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.reverter(c, evento, op)
        op = self.op(c, 'reclassificar_evento')
        c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.reclassificar(c, evento, 2, operacao_hibrida_id=op)

    def test_multiplos_efeitos_identificadores_e_chave_idempotente(self):
        c = self.migrar()
        op = self.op(c, 'registrar_imediata')
        evento = self.evento(c, op)
        lanc = self.caixa(c, op)
        q = self.liquidar(c, evento, 1000, lanc)
        c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        self.assertEqual(c.execute('SELECT e.id,l.id,q.id FROM eventos_financeiros e '
            'JOIN lancamentos l ON l.operacao_hibrida_id = e.operacao_hibrida_id '
            'JOIN liquidacoes_eventos q ON q.evento_id = e.id AND q.lancamento_id = l.id '
            'WHERE e.operacao_hibrida_id = ?', (op,)).fetchall(), [(evento, lanc, q)])
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute('INSERT INTO operacoes_hibridas (chave,tipo,requisicao_canonica) '
                      'SELECT chave,tipo,requisicao_canonica FROM operacoes_hibridas WHERE id = ?', (op,))
        sem_caixa = self.op(c, 'registrar_evento')
        e = self.evento(c, sem_caixa)
        self.assertEqual(c.execute('SELECT id FROM eventos_financeiros WHERE operacao_hibrida_id = ?',
                                  (sem_caixa,)).fetchall(), [(e,)])

    def test_categorias_usadas_inicializacao_legada_e_replace(self):
        c = self.migrar(fk=0, recursivos=0)
        evento = self.evento(c)
        self.reclassificar(c, evento, 2)
        c.commit()
        antes = c.execute('SELECT * FROM categorias ORDER BY id').fetchall()
        banco.criar_categorias()
        self.assertEqual(c.execute('SELECT * FROM categorias ORDER BY id').fetchall(), antes)
        for sql in ("UPDATE categorias SET tipo = 'receita' WHERE id = 2", 'DELETE FROM categorias WHERE id = 2',
                    "UPDATE categorias SET id = 999 WHERE id = 2",
                    "INSERT OR REPLACE INTO categorias VALUES (2,'Substituida','despesa')",
                    "INSERT OR REPLACE INTO categorias (nome,tipo) SELECT nome,'receita' FROM categorias WHERE id = 2"):
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute(sql)
        # Somente a repeticao exatamente identica e um no-op reconhecido.
        self.assertEqual(c.execute('INSERT OR REPLACE INTO categorias SELECT * FROM categorias WHERE id = 2').rowcount, 0)
        self.assertEqual(c.execute('SELECT * FROM categorias ORDER BY id').fetchall(), antes)

    def test_origens_legadas_e_colisoes_de_chaves_compostas(self):
        with closing(banco.abrir_conexao()) as c:
            for numero, campo in enumerate(('compra_cartao_id', 'parcelamento_id', 'parcela_comum_id',
                                            'ocorrencia_id', 'lancamento_legado_id'), start=100):
                c.execute(f"INSERT INTO eventos_financeiros (id,tipo,descricao,categoria_id,valor_centavos,"
                          f"situacao_competencia,chave_origem,{campo}) VALUES (?,'despesa','Antigo',1,100,'pendente',?,1)",
                          (numero, f'origem:{numero}'))
            c.commit()
        banco.aplicar_migracoes(self.caminho)
        for fk in (0, 1):
            for rt in (0, 1):
                c = self.conectar(fk, rt)
                for tabela in ('compras_cartao', 'parcelamentos', 'parcelamento_parcelas', 'recorrencia_ocorrencias', 'lancamentos'):
                    for sql in (f'DELETE FROM {tabela} WHERE id = 1', f'UPDATE {tabela} SET id = 999 WHERE id = 1',
                                f'INSERT OR REPLACE INTO {tabela} SELECT * FROM {tabela} WHERE id = 1'):
                        with self.subTest(fk=fk, rt=rt, sql=sql):
                            with self.assertRaises(sqlite3.IntegrityError):
                                c.execute(sql)
                for tabela, campos in (
                    ('parcelamento_parcelas', dict(id=999, parcelamento_id=1, numero_parcela=1,
                                                  data_vencimento='2026-11-01', valor=20)),
                    ('recorrencia_ocorrencias', dict(id=999, recorrencia_id=1, data_vencimento='2026-11-01', valor=20)),
                ):
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.inserir(c, tabela, campos, 'INSERT OR REPLACE')
                c.rollback()

    def test_funcoes_legadas_continuam_operando_sem_eventos_automaticos(self):
        c = self.migrar()
        banco.adicionar_lancamento('2026-11-01', 'Legado', 'despesa', 1, 5.25)
        linha = c.execute("SELECT id FROM lancamentos WHERE descricao = 'Legado'").fetchone()[0]
        self.assertTrue(banco.atualizar_lancamento(linha, '2026-11-02', 'Legado editado', 'despesa', 1, 6.25))
        self.assertTrue(banco.excluir_lancamento(linha))
        self.assertEqual(c.execute('SELECT count(*) FROM eventos_financeiros').fetchone(), (0,))

    def test_inicializacao_legada_completa_depois_da_migracao(self):
        c = self.migrar()
        self.evento(c)
        c.commit()
        antes = c.execute('SELECT * FROM eventos_financeiros').fetchall()
        for funcao in (banco.criar_banco, banco.criar_categorias, banco.migrar_categorias,
                       banco.migrar_datas, banco.criar_recorrencias,
                       banco.migrar_lancamentos_recorrencia, banco.criar_parcelamentos,
                       banco.migrar_lancamentos_parcelamento, banco.criar_cartoes,
                       banco.criar_faturas, banco.criar_compras_cartao, banco.criar_parcelas_cartao):
            funcao()
        self.assertEqual(c.execute('SELECT * FROM eventos_financeiros').fetchall(), antes)

    def test_receita_estornada_preserva_tipo_e_classificacao_registrada(self):
        c = self.migrar(fk=0, recursivos=0)
        categoria = c.execute("SELECT id FROM categorias WHERE tipo = 'receita' LIMIT 1").fetchone()[0]
        evento = self.evento(c, tipo='receita', categoria_id=categoria)
        op = self.op(c, 'liquidar_evento')
        lanc = self.caixa(c, op, 1000, tipo='receita', categoria_id=categoria,
                          categoria=c.execute('SELECT nome FROM categorias WHERE id = ?', (categoria,)).fetchone()[0])
        q = self.liquidar(c, evento, 1000, lanc)
        c.execute("UPDATE categorias SET nome = 'Nome novo' WHERE id = ?", (categoria,))
        self.estornar(c, q, 1000)
        self.assertEqual(c.execute('SELECT valor_liquido FROM _hibrido_liquidacoes WHERE id = ?', (q,)).fetchone(), (0,))
        self.assertEqual(c.execute('SELECT tipo, SUM(valor_centavos) FROM lancamentos '
                                   'WHERE operacao_hibrida_id IS NOT NULL GROUP BY tipo').fetchall(), [('receita', 0)])
        errado = self.caixa(c, centavos=1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.liquidar(c, evento, 1, errado)

    def test_permissao_interna_quick_check_nao_libera_sql_arbitrario(self):
        for instrucao in (
            'PRAGMA quick_check(lancamentos)', 'PRAGMA quick_check(eventos_financeiros)',
            'PRAGMA foreign_keys = OFF', 'COMMIT', '-- comentario\nSAVEPOINT proibido',
            '/* comentario */ RoLlBaCk', 'BEGIN', 'RELEASE inexistente',
            "ATTACH ':memory:' AS externo",
        ):
            with self.subTest(instrucao=instrucao):
                catalogo = self.catalogo[:2] + ((3, self.catalogo[2][1],
                    migracao_3.SQL_MIGRACAO_3 + (instrucao,)),)
                with patch.object(banco, 'MIGRACOES', catalogo):
                    with self.assertRaisesRegex(sqlite3.DatabaseError, 'authorized'):
                        banco.aplicar_migracoes(self.caminho)
                with closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT versao FROM esquema_migracoes').fetchall(), [(1,), (2,)])
                    self.assertNotIn('valor_centavos', {r[1] for r in c.execute('PRAGMA table_info(lancamentos)')})

    def test_varios_eventos_e_caixas_podem_apontar_para_a_mesma_operacao(self):
        c = self.migrar()
        op = self.op(c, 'registrar_imediata')
        efeitos = []
        for _ in range(2):
            e = self.evento(c, op)
            l = self.caixa(c, op)
            q = self.liquidar(c, e, 1000, l)
            efeitos.append((e, l, q))
        recuperados = c.execute('SELECT e.id,l.id,q.id FROM eventos_financeiros e '
            'JOIN liquidacoes_eventos q ON q.evento_id = e.id JOIN lancamentos l ON l.id = q.lancamento_id '
            'WHERE e.operacao_hibrida_id = ? AND l.operacao_hibrida_id = ? ORDER BY e.id', (op, op)).fetchall()
        self.assertEqual(recuperados, efeitos)

    def test_integridade_indices_e_gatilhos_nao_fazem_updates_financeiros(self):
        c = self.migrar()
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
        for indice, colunas in (
            ('idx_lancamentos_operacao_hibrida', ['operacao_hibrida_id']),
            ('idx_eventos_operacao_hibrida', ['operacao_hibrida_id']),
            ('idx_eventos_manuais_vencimento', ['data_vencimento']),
            ('idx_estornos_liquidacao', ['liquidacao_id']),
            ('idx_reclassificacoes_evento', ['evento_id', 'id']),
        ):
            self.assertEqual([r[2] for r in c.execute('SELECT * FROM pragma_index_info(?)', (indice,))], colunas)
        for sql, in c.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger'"):
            corpo = sql.split('BEGIN', 1)[1].upper()
            self.assertNotIn('UPDATE ', corpo)
            self.assertNotIn('DELETE ', corpo)
            self.assertNotIn('INSERT ', corpo)

    def test_limites_int64_nao_usam_soma_float(self):
        c = self.migrar()
        maximo = 2**63 - 1
        evento = self.evento(c, valor_centavos=maximo)
        self.liquidar(c, evento, maximo)
        with self.assertRaises(sqlite3.IntegrityError):
            self.liquidar(c, evento, 1)
        self.caixa(c, centavos=maximo)
        with self.assertRaisesRegex(sqlite3.OperationalError, 'integer overflow'):
            c.execute('SELECT SUM(valor_centavos) FROM lancamentos').fetchone()
        self.assertEqual(c.execute('SELECT typeof(valor_centavos) FROM lancamentos '
                                   'WHERE operacao_hibrida_id IS NOT NULL LIMIT 1').fetchone(), ('integer',))

    def test_guard_de_servico_futuro_deve_desfazer_operacoes_abertas(self):
        c = self.migrar()
        # Modelo apenas de teste: SQLite nao possui uma CHECK diferida de COMMIT.
        # Um servico futuro precisa executar esta guarda antes de confirmar.
        with self.assertRaisesRegex(RuntimeError, 'operacao aberta'):
            with c:
                self.op(c, 'registrar_evento')
                if c.execute("SELECT 1 FROM operacoes_hibridas WHERE estado = 'aberta'").fetchone():
                    raise RuntimeError('operacao aberta')
        self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (0,))

    def test_conclusao_e_rollback_nao_sao_bloqueados_por_imutabilidade(self):
        c = self.migrar()
        with c:
            op = self.op(c, 'registrar_imediata')
            e = self.evento(c, op)
            l = self.caixa(c, op)
            self.liquidar(c, e, 1000, l)
            c.execute("UPDATE operacoes_hibridas SET estado = 'concluida' WHERE id = ?", (op,))
        self.assertEqual(c.execute("SELECT count(*) FROM operacoes_hibridas WHERE estado = 'aberta'").fetchone(), (0,))
        with self.assertRaises(RuntimeError):
            with c:
                self.evento(c)
                raise RuntimeError('falha depois do evento')
        self.assertEqual(c.execute('SELECT count(*) FROM eventos_financeiros').fetchone(), (1,))


if __name__ == '__main__':
    unittest.main()
