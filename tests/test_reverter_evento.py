"""Reversao publica: apenas SQLite temporario, sem app ou base de producao."""
from contextlib import closing
from datetime import date, datetime
import inspect
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch

import banco
import servicos_financeiros as sf
import test_liquidar_evento as pagamentos


class TestReverterEvento(unittest.TestCase):
    def setUp(self):
        self.h = pagamentos.TestLiquidarEvento()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()
        self.f = self.h.f
        self.e = self.h.evento

    def p(self, numero=2, **mudancas):
        return dict(chave=pagamentos.chave(numero), evento_id=self.e,
            data_reversao=date(2026, 11, 10), motivo='Ocorrencia cancelada') | mudancas

    def foto(self):
        return self.h.foto()

    def pagar(self, numero=10, valor=1000, evento=None):
        return sf.liquidar_evento(**self.h.p(numero, evento_id=self.e if evento is None else evento,
            valor_centavos=valor))

    def estornar(self, q, valor, numero=11):
        return sf.estornar_liquidacao(chave=pagamentos.chave(numero), liquidacao_id=q,
            valor_centavos=valor, natureza='devolucao_real', motivo='Devolvido',
            data_estorno=date(2026, 11, 2), confirmar_datas_divergentes=True)

    def conferir(self, p, r, antes, categoria=1):
        self.assertEqual((r.tipo_operacao, r.chave, r.evento_ids),
            ('reverter_evento', p['chave'], (p['evento_id'],)))
        self.assertEqual((r.lancamento_ids, r.liquidacao_ids, r.estorno_ids, r.reclassificacao_ids),
            ((), (), (), ()))
        self.assertEqual(len(r.reversao_ids), 1)
        self.assertGreater(r.reversao_ids[0], 0)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT evento_id,operacao_hibrida_id,data_competencia,categoria_id,motivo '
                'FROM reversoes_eventos WHERE id=?', r.reversao_ids).fetchone(),
                (p['evento_id'], r.operacao_id, p['data_reversao'].isoformat(), categoria,
                 sf.normalizar_texto(p['motivo'])))
            self.assertEqual(c.execute('SELECT tipo,estado FROM operacoes_hibridas WHERE id=?',
                (r.operacao_id,)).fetchone(), ('reverter_evento', 'concluida'))
        depois = self.foto()
        for tabela, dados in antes.items():
            if tabela in ('operacoes_hibridas', 'reversoes_eventos'):
                self.assertEqual(len(depois[tabela]), len(dados)+1, tabela)
                self.assertTrue(all(linha in depois[tabela] for linha in dados), tabela)
            elif tabela != 'sqlite_sequence':
                self.assertEqual(depois[tabela], dados, tabela)

    def test_assinatura_exata_e_seis_servicos(self):
        sig = inspect.signature(sf.reverter_evento)
        self.assertEqual(tuple(sig.parameters), ('chave', 'evento_id', 'data_reversao', 'motivo'))
        self.assertIs(sig.return_annotation, sf.ResultadoOperacao)
        for parametro in sig.parameters.values():
            self.assertIs(parametro.kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(parametro.default, inspect.Parameter.empty)
        self.assertTrue(callable(sf.reclassificar_evento))

    def test_evento_nunca_pago_reverte_sem_caixa_nem_alteracao_original(self):
        antes = self.foto()
        self.conferir(self.p(), sf.reverter_evento(**self.p()), antes)

    def test_pagamento_integral_totalmente_estornado(self):
        pagamento = self.pagar()
        self.estornar(pagamento.liquidacao_ids[0], 1000)
        antes = self.foto()
        self.conferir(self.p(), sf.reverter_evento(**self.p()), antes)

    def test_multiplas_liquidacoes_e_estornos_parciais_integralizados(self):
        a = self.pagar(10, 300)
        b = self.pagar(11, 700)
        self.estornar(a.liquidacao_ids[0], 100, 12)
        self.estornar(a.liquidacao_ids[0], 200, 13)
        self.estornar(b.liquidacao_ids[0], 700, 14)
        antes = self.foto()
        self.conferir(self.p(), sf.reverter_evento(**self.p()), antes)

    def test_liquidacao_parcial_integral_ou_estorno_parcial_impedem_reversao(self):
        for caso in ('parcial', 'integral', 'estorno_parcial'):
            destino = self.f.clone(caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                pagamento = self.pagar(valor=300 if caso == 'parcial' else 1000)
                if caso == 'estorno_parcial': self.estornar(pagamento.liquidacao_ids[0], 999)
                antes = self.foto()
                with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
                    with self.assertRaises(sf.EventoAindaLiquidado): sf.reverter_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_compensacao_invalida_que_aparenta_liquido_zero_e_rejeitada(self):
        a = self.pagar(10, 400)
        self.pagar(11, 600)
        estorno = self.estornar(a.liquidacao_ids[0], 100, 12)
        self.h.corromper_fixture(('lancamentos',), lambda c:
            c.execute('UPDATE lancamentos SET valor_centavos=-1000,valor=CAST(-1000 AS REAL)/100.0 '
                'WHERE id=?', estorno.lancamento_ids))
        # O SUM simples e zero, mas a primeira liquidacao tem estorno excessivo
        # e a segunda ainda tem 600 ativos. Deve falhar por inconsistência real.
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT SUM(valor_liquido) FROM _hibrido_liquidacoes '
                'WHERE evento_id=?', (self.e,)).fetchone(), (0,))
        antes = self.foto()
        with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
            with self.assertRaises(sf.OperacaoIncompleta): sf.reverter_evento(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_grafo_orfao_sinal_categoria_ou_operacao_inconsistente(self):
        a = self.pagar()
        estorno = self.estornar(a.liquidacao_ids[0], 1000)
        casos = {
            'caixa_orfao': (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET lancamento_id=999 WHERE id=?', a.liquidacao_ids[0]),
            'retorno_orfao': (('estornos_liquidacoes',), 'UPDATE estornos_liquidacoes SET lancamento_estorno_id=999 WHERE id=?', estorno.estorno_ids[0]),
            'sinal': (('lancamentos',), 'UPDATE lancamentos SET valor_centavos=1000,valor=10 WHERE id=?', estorno.lancamento_ids[0]),
            'categoria': (('lancamentos',), 'UPDATE lancamentos SET categoria_id=2 WHERE id=?', estorno.lancamento_ids[0]),
            'aberta': (('operacoes_hibridas',), "UPDATE operacoes_hibridas SET estado='aberta' WHERE id=?", a.operacao_id),
            'q_zero': (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET valor_centavos=0 WHERE id=?', a.liquidacao_ids[0]),
        }
        for nome, (tabelas, sql, id_alvo) in casos.items():
            destino = self.f.clone(nome)
            with self.subTest(caso=nome), patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(tabelas, lambda c: c.execute(sql, (id_alvo,)))
                antes = self.foto()
                with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
                    with self.assertRaises(sf.OperacaoIncompleta): sf.reverter_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_evento_inexistente_e_entradas_invalidas_sem_conexao(self):
        antes = self.foto()
        with self.assertRaises(sf.EventoInexistente): sf.reverter_evento(**self.p(evento_id=999))
        self.assertEqual(self.foto(), antes)
        casos = [dict(evento_id=v) for v in (0, -1, True, False, 1.0, '1', 2**63)]
        casos += [dict(motivo=v) for v in ('', '  ', None, 'a\x00b', '\ud800')]
        casos += [dict(data_reversao=v) for v in ('2026-11-10', None, datetime(2026, 11, 10))]
        casos += [dict(chave='invalida')]
        for caso in casos:
            with self.subTest(caso=caso), patch.object(banco, 'abrir_conexao', side_effect=AssertionError('abriu')):
                with self.assertRaises(sf.ParametroInvalido): sf.reverter_evento(**self.p(**caso))
        self.assertEqual(self.foto(), antes)

    def test_historico_legado_real_nao_e_adotado(self):
        destino = self.f.caminho.with_name('legado_sem_origem.db')
        with closing(sqlite3.connect(self.h.v2)) as fonte, closing(sqlite3.connect(destino)) as c:
            fonte.backup(c)
            c.execute('INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,'
                'situacao_competencia,data_competencia,chave_origem) '
                "VALUES(77,'despesa','Historico',1,1000,'confirmada','2026-11-01','historico')")
            c.commit()
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            banco.aplicar_migracoes(destino)
            antes = self.foto()
            with self.assertRaises(sf.EventoNaoElegivel): sf.reverter_evento(**self.p(evento_id=77))
            self.assertEqual(self.foto(), antes)

    def test_evento_inelegivel_ou_origem_incompativel(self):
        for campo, valor, erro in (('situacao_competencia', 'estimada', sf.EventoNaoElegivel),
                                  ('tipo', 'outro', sf.EventoNaoElegivel),
                                  ('valor_centavos', 0, sf.EventoNaoElegivel),
                                  ('compra_cartao_id', 999, sf.OperacaoIncompleta),
                                  ('operacao_hibrida_id', 999, sf.OperacaoIncompleta)):
            destino = self.f.clone(campo)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('eventos_financeiros',), lambda c:
                    c.execute(f'UPDATE eventos_financeiros SET {campo}=? WHERE id=?', (valor, self.e)))
                antes = self.foto()
                with self.assertRaises(erro): sf.reverter_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_categoria_corrente_capturada_apos_reclassificacao(self):
        self.h.reclassificar_fixture(2)
        antes = self.foto()
        self.conferir(self.p(), sf.reverter_evento(**self.p()), antes, categoria=2)

    def test_categoria_corrente_ausente_ou_incompativel(self):
        self.h.reclassificar_fixture(2)
        for caso, erro in (('ausente', sf.CategoriaInexistente), ('tipo', sf.CategoriaIncompativel)):
            destino = self.f.clone(caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('categorias',), lambda c:
                    c.execute('DELETE FROM categorias WHERE id=2' if caso == 'ausente' else
                              "UPDATE categorias SET tipo='receita' WHERE id=2"))
                antes = self.foto()
                with self.assertRaises(erro): sf.reverter_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_receita_e_datas_passadas_futuras_explicitas(self):
        with closing(banco.abrir_conexao()) as c:
            categoria = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
        for numero, data in ((10, date.min), (11, date.max)):
            e = self.h.criar_evento(numero, tipo='receita', categoria=categoria).evento_ids[0]
            p = self.p(numero+10, evento_id=e, data_reversao=data, motivo='  Cafe\u0301  cancelado  ')
            antes = self.foto()
            self.conferir(p, sf.reverter_evento(**p), antes, categoria=categoria)

    def test_replay_canonico_sem_revalidar_saldo_e_conflito_payload(self):
        p = self.p(motivo=' Cafe\u0301 ')
        r = sf.reverter_evento(**p)
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('revalidou')):
            self.assertEqual(sf.reverter_evento(**(p | {'motivo': 'Café'})), r)
        self.assertEqual(self.foto(), antes)
        for mudanca in (dict(evento_id=999), dict(motivo='Outro'), dict(data_reversao=date(2026, 11, 11))):
            with self.assertRaises(sf.ConflitoIdempotencia): sf.reverter_evento(**(p | mudanca))
            self.assertEqual(self.foto(), antes)

    def test_nova_chave_para_evento_ja_revertido(self):
        sf.reverter_evento(**self.p())
        antes = self.foto()
        with self.assertRaises(sf.EventoJaRevertido): sf.reverter_evento(**self.p(3))
        self.assertEqual(self.foto(), antes)

    def test_operacao_aberta_persistida_nao_e_completada(self):
        req = sf.canonicalizar_requisicao('reverter_evento', **self.p())
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.reverter_evento(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_replay_apos_renomeacao_e_mudanca_controlada_da_classificacao(self):
        p = self.p()
        r = sf.reverter_evento(**p)
        with self.f.conectar() as c:
            c.execute("UPDATE categorias SET nome='Nome posterior' WHERE id=1")
        self.assertEqual(sf.reverter_evento(**p), r)
        # Reclassificar evento revertido e proibido pelo banco. Esta fixture
        # adversarial simula estado corrente alterado externamente, restaura
        # os gatilhos e prova que replay depende dos efeitos originais imutaveis.
        def mudar(c):
            id_historico = self.f.reclassificar(c, self.e, 2)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id="
                      '(SELECT operacao_hibrida_id FROM reclassificacoes_eventos WHERE id=?)', (id_historico,))
        self.h.corromper_fixture(('reclassificacoes_eventos',), mudar)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                (self.e,)).fetchone(), (2,))
            self.assertEqual(c.execute('SELECT categoria_id FROM reversoes_eventos WHERE id=?',
                r.reversao_ids).fetchone(), (1,))
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('revalidou')):
            self.assertEqual(sf.reverter_evento(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_limites_int64_e_somas_brutas_acima_do_limite(self):
        for numero, valor in ((20, 1), (21, sf.MAX_CENTAVOS)):
            e = self.h.criar_evento(numero, valor=valor).evento_ids[0]
            if valor == sf.MAX_CENTAVOS:
                for n in (30, 32):
                    pago = self.pagar(n, valor, e)
                    self.estornar(pago.liquidacao_ids[0], valor, n+1)
            p = self.p(numero+30, evento_id=e)
            antes = self.foto()
            self.conferir(p, sf.reverter_evento(**p), antes)

    def test_ids_historicos_nao_positivos_preservados(self):
        for id_antigo in (-10, 0):
            destino = self.f.clone('id_'+str(id_antigo))
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                # IDs invalidos nao surgem no esquema aprovado; fixture apenas
                # exercita defesa do alocador sem reescrever dados existentes.
                self.h.corromper_fixture(('reversoes_eventos',), lambda c:
                    c.execute('INSERT INTO reversoes_eventos(id,evento_id,operacao_hibrida_id,data_competencia,categoria_id,motivo) '
                        "VALUES(?,999,999,'2026-11-01',1,'Historico')", (id_antigo,)))
                antes = self.foto()
                r = sf.reverter_evento(**self.p())
                self.assertEqual(r.reversao_ids, (1,))
                self.conferir(self.p(), r, antes)

    def test_ultimo_id_disponivel_e_esgotamento_sem_efeitos(self):
        self.h.corromper_fixture(('reversoes_eventos',), lambda c:
            c.execute('INSERT INTO reversoes_eventos(id,evento_id,operacao_hibrida_id,data_competencia,categoria_id,motivo) '
                "VALUES(?,999,999,'2026-11-01',1,'Historico')", (sf.MAX_CENTAVOS-1,)))
        antes = self.foto()
        r = sf.reverter_evento(**self.p())
        self.assertEqual(r.reversao_ids, (sf.MAX_CENTAVOS,))
        self.conferir(self.p(), r, antes)
        self.assertEqual(sf.reverter_evento(**self.p()), r)
        outro = self.h.criar_evento(10).evento_ids[0]
        antes = self.foto()
        with self.assertRaises(sf.IdentificadoresEsgotados): sf.reverter_evento(**self.p(3, evento_id=outro))
        self.assertEqual(self.foto(), antes)

    def test_falhas_apos_inserts_conclusao_e_commit_revertem_e_fecham(self):
        abrir = banco.abrir_conexao
        antes = self.foto()
        for ponto in ('operacoes_hibridas', 'reversoes_eventos', 'conclusao', 'commit'):
            real = abrir()
            class Falha:
                fechada = False
                def __getattr__(self, nome): return getattr(real, nome)
                def execute(self, sql, *args):
                    cur = real.execute(sql, *args)
                    if sql.startswith('INSERT INTO '+ponto) or (ponto == 'conclusao' and sql.startswith('UPDATE operacoes_hibridas')):
                        raise sqlite3.OperationalError('injetada:'+ponto)
                    return cur
                def commit(self):
                    if ponto == 'commit': raise sqlite3.OperationalError('injetada:commit')
                    real.commit()
                def close(self): self.fechada = True; real.close()
            proxy = Falha()
            with self.subTest(ponto=ponto), patch.object(banco, 'abrir_conexao', return_value=proxy):
                with self.assertRaises(sf.FalhaPersistencia) as erro: sf.reverter_evento(**self.p())
            self.assertEqual(str(erro.exception.__cause__), 'injetada:'+ponto)
            self.assertTrue(proxy.fechada)
            self.assertEqual(self.foto(), antes)

    def test_resposta_perdida_apos_commit_e_recuperavel(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self): real.commit(); raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.reverter_evento(**self.p())
        antes = self.foto()
        r = sf.reverter_evento(**self.p())
        self.assertEqual(sf.reverter_evento(**self.p()), r)
        self.assertEqual(self.foto(), antes)

    def test_completude_rejeita_ausente_duplicada_extra_e_dados_divergentes(self):
        abrir = banco.abrir_conexao
        outro = self.h.criar_evento(10).evento_ids[0]
        for caso in ('ausente', 'duplicada', 'extra', 'data', 'motivo', 'alvo'):
            real = abrir()
            antes = self.foto()
            self_outer = self
            class Incompleta:
                def __getattr__(self, nome): return getattr(real, nome)
                def execute(self, sql, *args):
                    if sql.startswith('INSERT INTO reversoes_eventos'):
                        valores = list(args[0])
                        if caso == 'data': valores[3] = '2026-11-11'
                        if caso == 'motivo': valores[5] = 'Outro motivo'
                        if caso == 'alvo': valores[1] = outro
                        if caso == 'ausente': real.execute('SAVEPOINT fixture')
                        cur = real.execute(sql, valores)
                        if caso == 'ausente':
                            real.execute('ROLLBACK TO fixture'); real.execute('RELEASE fixture')
                        elif caso == 'duplicada':
                            # Outra reversao valida para outro evento, mesma
                            # operacao: o perfil do servico deve rejeitar duas.
                            real.execute('INSERT INTO reversoes_eventos(evento_id,operacao_hibrida_id,data_competencia,categoria_id,motivo) '
                                "VALUES(?,?,'2026-11-10',1,'Extra')", (outro, valores[2]))
                        elif caso == 'extra':
                            # Outro tipo de efeito em uma segunda operacao criada
                            # nesta transacao e deixada aberta: deve ser revertida.
                            self_outer.f.evento(real)
                        return cur
                    return real.execute(sql, *args)
            with self.subTest(caso=caso), patch.object(banco, 'abrir_conexao', return_value=Incompleta()):
                with self.assertRaises(sf.OperacaoIncompleta): sf.reverter_evento(**self.p())
            self.assertEqual(self.foto(), antes)

    def test_replay_recusa_reversao_ausente_dados_adulterados_ou_efeitos_extras(self):
        p = self.p()
        r = sf.reverter_evento(**p)
        for caso in ('ausente', 'motivo', 'data', 'categoria', 'extra'):
            destino = self.f.clone('replay_'+caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                if caso == 'extra':
                    def mutacao(c):
                        self.f.caixa(c, r.operacao_id, centavos=-1)
                    self.h.corromper_fixture(('lancamentos',), mutacao)
                else:
                    sql = {'ausente': 'DELETE FROM reversoes_eventos WHERE id=?',
                           'motivo': "UPDATE reversoes_eventos SET motivo='Adulterado' WHERE id=?",
                           'data': "UPDATE reversoes_eventos SET data_competencia='2026-11-11' WHERE id=?",
                           'categoria': 'UPDATE reversoes_eventos SET categoria_id=999 WHERE id=?'}[caso]
                    self.h.corromper_fixture(('reversoes_eventos',), lambda c: c.execute(sql, r.reversao_ids))
                antes = self.foto()
                with self.assertRaises(sf.OperacaoIncompleta): sf.reverter_evento(**p)
                self.assertEqual(self.foto(), antes)

    def test_ordem_sql_e_resultado_somente_apos_commit(self):
        real = banco.abrir_conexao()
        sqls, commit_efetivado = [], []
        real.set_trace_callback(sqls.append)
        class Observada:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self):
                real.commit()
                commit_efetivado.append(True)
        with patch.object(banco, 'abrir_conexao', return_value=Observada()):
            r = sf.reverter_evento(**self.p())
        self.assertEqual(commit_efetivado, [True])
        begin = sqls.index('BEGIN IMMEDIATE')
        consultas = [i for i, sql in enumerate(sqls) if sql.startswith('SELECT * FROM eventos_financeiros WHERE id=')
                     or sql.startswith('SELECT categoria_atual_id') or sql.startswith('INSERT INTO reversoes_eventos')]
        self.assertTrue(consultas)
        self.assertTrue(all(i > begin for i in consultas))
        self.assertGreater(r.operacao_id, 0)
        with self.assertRaises(sqlite3.ProgrammingError): real.execute('SELECT 1')

    def test_concorrencia_real_mesma_chave_e_reversao_duplicada(self):
        for mesmo in (True, False):
            destino = self.f.clone('concorrente_'+str(mesmo))
            pronta, liberar, terminou, ocupado = (threading.Event() for _ in range(4))
            resultados, erros = {}, {}
            abrir = banco.abrir_conexao
            def abrir_controlada():
                real = abrir(); real.execute('PRAGMA busy_timeout=1')
                if threading.current_thread().name != 'reversao-a': return real
                class Suspensa:
                    def __getattr__(self, nome): return getattr(real, nome)
                    def commit(self):
                        pronta.set()
                        if not liberar.wait(10): raise AssertionError('nao liberou')
                        real.commit()
                return Suspensa()
            p_a, p_b = self.p(), self.p(2 if mesmo else 3)
            def a():
                try: resultados['a'] = sf.reverter_evento(**p_a)
                except BaseException as erro: erros['a'] = erro
                finally: terminou.set()
            def b():
                try:
                    if not pronta.wait(10): raise AssertionError('A nao chegou ao commit')
                    try:
                        sf.reverter_evento(**p_b)
                        raise AssertionError('Nao disputou lock')
                    except sf.BancoOcupado as erro:
                        if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                        ocupado.set()
                    if not terminou.wait(10): raise AssertionError('A nao terminou')
                    resultados['b'] = sf.reverter_evento(**p_b)
                except BaseException as erro: erros['b'] = erro
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), \
                    patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
                ta, tb = threading.Thread(target=a, name='reversao-a'), threading.Thread(target=b, name='reversao-b')
                ta.start(); tb.start()
                try: self.assertTrue(ocupado.wait(10), 'Sem disputa SQLite comprovada')
                finally: liberar.set(); ta.join(15); tb.join(15)
                self.assertFalse(ta.is_alive() or tb.is_alive())
            self.assertNotIn('a', erros)
            if mesmo:
                self.assertFalse(erros)
                self.assertEqual(resultados['a'], resultados['b'])
            else: self.assertIsInstance(erros.get('b'), sf.EventoJaRevertido)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), closing(banco.abrir_conexao()) as c:
                self.assertEqual(c.execute('SELECT evento_id FROM reversoes_eventos').fetchall(), [(self.e,)])
                self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (2,))
                self.assertEqual(c.execute('SELECT count(*) FROM lancamentos WHERE operacao_hibrida_id IS NOT NULL').fetchone(), (0,))


if __name__ == '__main__':
    unittest.main()
