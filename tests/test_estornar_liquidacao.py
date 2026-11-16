"""Estornos publicos: fixtures reais isoladas, sem app ou base de producao."""
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
import inspect
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch

import banco
import servicos_financeiros as sf
import test_liquidar_evento as pagamentos


class TestEstornarLiquidacao(unittest.TestCase):
    def setUp(self):
        self.h = pagamentos.TestLiquidarEvento()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()
        self.f = self.h.f
        self.e = self.h.evento
        self.r = sf.liquidar_evento(**self.h.p(valor_centavos=1000))
        self.q = self.r.liquidacao_ids[0]

    def p(self, numero=3, **mudancas):
        return dict(chave=pagamentos.chave(numero), liquidacao_id=self.q,
            valor_centavos=400, natureza='devolucao_real', motivo='Produto devolvido',
            data_estorno=date(2026, 11, 2), confirmar_datas_divergentes=True) | mudancas

    def foto(self):
        return self.h.foto()

    def conferir(self, p, r, antes):
        self.assertEqual(r.tipo_operacao, 'estornar_liquidacao')
        self.assertEqual(r.liquidacao_ids, (p['liquidacao_id'],))
        self.assertEqual((len(r.evento_ids), len(r.lancamento_ids), len(r.estorno_ids)), (1, 1, 1))
        self.assertEqual((r.reversao_ids, r.reclassificacao_ids), ((), ()))
        self.assertGreater(r.lancamento_ids[0], 0)
        self.assertGreater(r.estorno_ids[0], 0)
        with closing(banco.abrir_conexao()) as c:
            q = c.execute('SELECT evento_id,lancamento_id FROM liquidacoes_eventos WHERE id=?',
                (p['liquidacao_id'],)).fetchone()
            self.assertEqual(r.evento_ids, (q[0],))
            original = c.execute('SELECT tipo,categoria_id,categoria FROM lancamentos WHERE id=?', (q[1],)).fetchone()
            self.assertEqual(c.execute('SELECT tipo,categoria_id,categoria,descricao,valor_centavos,'
                'typeof(valor_centavos),valor=CAST(valor_centavos AS REAL)/100.0,data,operacao_hibrida_id '
                'FROM lancamentos WHERE id=?', r.lancamento_ids).fetchone(),
                (*original, f"Estorno L#{p['liquidacao_id']} [{p['natureza']}]: {sf.normalizar_texto(p['motivo'])}",
                 -p['valor_centavos'], 'integer', 1, p['data_estorno'].isoformat(), r.operacao_id))
            self.assertEqual(c.execute('SELECT liquidacao_id,lancamento_estorno_id,natureza,motivo '
                'FROM estornos_liquidacoes WHERE id=?', r.estorno_ids).fetchone(),
                (p['liquidacao_id'], r.lancamento_ids[0], p['natureza'], sf.normalizar_texto(p['motivo'])))
            self.assertEqual(c.execute('SELECT estado FROM operacoes_hibridas WHERE id=?',
                (r.operacao_id,)).fetchone(), ('concluida',))
        depois = self.foto()
        for t, dados in antes.items():
            if t in ('operacoes_hibridas', 'lancamentos', 'estornos_liquidacoes'):
                self.assertEqual(len(depois[t]), len(dados)+1, t)
                self.assertTrue(all(linha in depois[t] for linha in dados), t)
            elif t != 'sqlite_sequence':
                self.assertEqual(depois[t], dados, t)

    def test_assinatura_obrigatoria_e_sem_servicos_adicionais(self):
        sig = inspect.signature(sf.estornar_liquidacao)
        self.assertEqual(set(sig.parameters), set(self.p()))
        self.assertIs(sig.return_annotation, sf.ResultadoOperacao)
        for p in sig.parameters.values():
            self.assertIs(p.kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(p.default, inspect.Parameter.empty)
        self.assertTrue(callable(sf.reverter_evento))
        self.assertTrue(callable(sf.reclassificar_evento))

    def test_parciais_sucessivos_integral_e_saldo_zero(self):
        for numero, valor in ((3, 200), (4, 300), (5, 500)):
            p = self.p(numero, valor_centavos=valor)
            antes = self.foto()
            self.conferir(p, sf.estornar_liquidacao(**p), antes)
        antes = self.foto()
        with self.assertRaises(sf.EstornoExcessivo):
            sf.estornar_liquidacao(**self.p(6, valor_centavos=1))
        self.assertEqual(self.foto(), antes)

    def test_integral_e_excesso_rejeitado_sem_efeitos(self):
        antes = self.foto()
        with self.assertRaises(sf.EstornoExcessivo):
            sf.estornar_liquidacao(**self.p(valor_centavos=1001))
        self.assertEqual(self.foto(), antes)
        p = self.p(valor_centavos=1000)
        self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_receita_permanece_receita_negativa(self):
        with closing(banco.abrir_conexao()) as c:
            cat = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
        e = self.h.criar_evento(10, tipo='receita', categoria=cat).evento_ids[0]
        r = sf.liquidar_evento(**self.h.p(11, evento_id=e))
        p = self.p(liquidacao_id=r.liquidacao_ids[0])
        antes = self.foto()
        self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_validacoes_estaticas_nao_abrem_conexao(self):
        casos = [dict(liquidacao_id=v) for v in (0, -1, True, 1.0, '1', 2**63)]
        casos += [dict(valor_centavos=v) for v in (0, -1, -2**63, 2**63, True, 1.0, Decimal(1), '1')]
        casos += [dict(natureza='outra'), dict(motivo=' '), dict(motivo=None),
            dict(data_estorno=datetime(2026, 11, 2)), dict(data_estorno='2026-11-02'),
            dict(confirmar_datas_divergentes=1), dict(chave='invalida')]
        antes = self.foto()
        for caso in casos:
            with self.subTest(caso=caso), patch.object(banco, 'abrir_conexao', side_effect=AssertionError('abriu')):
                with self.assertRaises(sf.ParametroInvalido): sf.estornar_liquidacao(**self.p(**caso))
        self.assertEqual(self.foto(), antes)

    def test_datas_duas_naturezas_e_confirmacao(self):
        casos = [dict(data_estorno=date(2026, 10, 31)),
                 dict(natureza='correcao_registro', data_estorno=date(2026, 11, 2))]
        for caso in casos:
            antes = self.foto()
            with self.assertRaises(sf.DataInvalida): sf.estornar_liquidacao(**self.p(**caso))
            self.assertEqual(self.foto(), antes)
        antes = self.foto()
        with self.assertRaises(sf.ConfirmacaoNecessaria):
            sf.estornar_liquidacao(**self.p(confirmar_datas_divergentes=False))
        self.assertEqual(self.foto(), antes)
        for numero, caso in ((3, dict(natureza='correcao_registro', data_estorno=date(2026, 11, 1),
                                     confirmar_datas_divergentes=False)),
                             (4, dict(data_estorno=date.max))):
            p = self.p(numero, **caso)
            antes = self.foto()
            self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_classificacao_original_apos_renomear_e_reclassificar(self):
        self.h.reclassificar_fixture(2)
        with self.f.conectar() as c:
            c.execute("UPDATE categorias SET nome='Nome atualizado' WHERE id=1")
        p = self.p(motivo='  Cafe\u0301  devolvido  ')
        antes = self.foto()
        self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_correcao_na_data_original_divergente_da_competencia(self):
        e = self.h.criar_evento(10).evento_ids[0]
        pagamento = sf.liquidar_evento(**self.h.p(11, evento_id=e,
            data_liquidacao=date(2026, 11, 15), confirmar_datas_divergentes=True))
        p = self.p(liquidacao_id=pagamento.liquidacao_ids[0], natureza='correcao_registro',
            data_estorno=date(2026, 11, 15), confirmar_datas_divergentes=False)
        antes = self.foto()
        with self.assertRaises(sf.ConfirmacaoNecessaria): sf.estornar_liquidacao(**p)
        self.assertEqual(self.foto(), antes)
        p['confirmar_datas_divergentes'] = True
        self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_saldo_reaberto_pode_ser_liquidado_com_novo_caixa(self):
        sf.estornar_liquidacao(**self.p(valor_centavos=600))
        p = self.h.p(4, valor_centavos=600)
        antes = self.foto()
        r = sf.liquidar_evento(**p)
        self.h.conferir(p, r, antes)
        self.assertNotEqual(r.lancamento_ids, self.r.lancamento_ids)

    def test_inexistente_inelegivel_e_revertido(self):
        antes = self.foto()
        with self.assertRaises(sf.LiquidacaoInexistente): sf.estornar_liquidacao(**self.p(liquidacao_id=999))
        self.assertEqual(self.foto(), antes)
        for campo, valor in (('origem_tipo', None), ('situacao_competencia', 'estimada')):
            destino = self.f.clone(campo)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('eventos_financeiros',), lambda c:
                    c.execute(f'UPDATE eventos_financeiros SET {campo}=? WHERE id=?', (valor, self.e)))
                antes = self.foto()
                with self.assertRaises(sf.EventoNaoElegivel): sf.estornar_liquidacao(**self.p())
                self.assertEqual(self.foto(), antes)
        sf.estornar_liquidacao(**self.p(valor_centavos=1000))
        with self.f.conectar() as c:
            self.f.reverter(c, self.e)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        with self.assertRaises(sf.EventoRevertido): sf.estornar_liquidacao(**self.p(4))
        self.assertEqual(self.foto(), antes)

    def test_replay_canonico_conflito_e_operacao_aberta(self):
        p = self.p(motivo=' Cafe\u0301 ')
        r = sf.estornar_liquidacao(**p)
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('revalidou')):
            self.assertEqual(sf.estornar_liquidacao(**(p | {'motivo': 'Café'})), r)
        self.assertEqual(self.foto(), antes)
        for mudanca in (dict(valor_centavos=401), dict(motivo='Outro'), dict(liquidacao_id=999),
                        dict(natureza='correcao_registro'), dict(confirmar_datas_divergentes=False)):
            with self.assertRaises(sf.ConflitoIdempotencia): sf.estornar_liquidacao(**(p | mudanca))
            self.assertEqual(self.foto(), antes)
        req = sf.canonicalizar_requisicao('estornar_liquidacao', **self.p(4))
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**self.p(4))
        self.assertEqual(self.foto(), antes)

    def test_replay_apos_integral_reclassificacao_e_reversao(self):
        p = self.p(valor_centavos=1000)
        r = sf.estornar_liquidacao(**p)
        self.h.reclassificar_fixture(2)
        with self.f.conectar() as c:
            self.f.reverter(c, self.e)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('revalidou')):
            self.assertEqual(sf.estornar_liquidacao(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_replay_confere_descricao_persistida(self):
        p = self.p()
        r = sf.estornar_liquidacao(**p)
        self.h.corromper_fixture(('lancamentos',), lambda c:
            c.execute("UPDATE lancamentos SET descricao='Adulterada' WHERE id=?", r.lancamento_ids))
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**p)
        self.assertEqual(self.foto(), antes)

    def test_replay_recusa_efeito_ausente_ou_extra(self):
        p = self.p()
        r = sf.estornar_liquidacao(**p)
        for caso in ('ausente', 'extra'):
            destino = self.f.clone('replay_'+caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                if caso == 'ausente':
                    self.h.corromper_fixture(('estornos_liquidacoes',), lambda c:
                        c.execute('DELETE FROM estornos_liquidacoes WHERE id=?', r.estorno_ids))
                else:
                    self.h.corromper_fixture(('lancamentos',), lambda c:
                        self.f.caixa(c, r.operacao_id, centavos=-1))
                antes = self.foto()
                with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**p)
                self.assertEqual(self.foto(), antes)

    def test_int64_parciais_assimetricos_e_um_centavo_residual(self):
        e = self.h.criar_evento(10, valor=sf.MAX_CENTAVOS).evento_ids[0]
        r = sf.liquidar_evento(**self.h.p(11, evento_id=e, valor_centavos=sf.MAX_CENTAVOS))
        q = r.liquidacao_ids[0]
        for numero, valor in ((12, sf.MAX_CENTAVOS-2), (13, 1), (14, 1)):
            p = self.p(numero, liquidacao_id=q, valor_centavos=valor)
            antes = self.foto()
            self.conferir(p, sf.estornar_liquidacao(**p), antes)
        antes = self.foto()
        with self.assertRaises(sf.EstornoExcessivo): sf.estornar_liquidacao(**self.p(15, liquidacao_id=q, valor_centavos=1))
        self.assertEqual(self.foto(), antes)

    def test_rateio_original_limite_por_liquidacao(self):
        outro = self.h.criar_evento(10).evento_ids[0]
        with self.f.conectar() as c:
            op = self.f.op(c, 'liquidar_evento')
            caixa = self.f.caixa(c, op, centavos=1000)
            q = self.f.liquidar(c, outro, 300, caixa)
            terceiro = self.f.evento(c)
            self.f.liquidar(c, terceiro, 700, caixa)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        with self.assertRaises(sf.EstornoExcessivo): sf.estornar_liquidacao(**self.p(liquidacao_id=q, valor_centavos=301))
        self.assertEqual(self.foto(), antes)
        p = self.p(liquidacao_id=q, valor_centavos=300)
        self.conferir(p, sf.estornar_liquidacao(**p), antes)

    def test_grafo_inconsistente_rejeitado_antes_de_escrever(self):
        casos = {
            'evento_orfao': (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET evento_id=999 WHERE id=?', self.q),
            'caixa_orfao': (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET lancamento_id=999 WHERE id=?', self.q),
            'liquidacao_zero': (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET valor_centavos=0 WHERE id=?', self.q),
            'sinal': (('lancamentos',), 'UPDATE lancamentos SET valor_centavos=-1000,valor=-10 WHERE id=?', self.r.lancamento_ids[0]),
            'real': (('lancamentos',), 'UPDATE lancamentos SET valor=0 WHERE id=?', self.r.lancamento_ids[0]),
        }
        for nome, (tabelas, sql, id_alvo) in casos.items():
            destino = self.f.clone(nome)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(tabelas, lambda c: c.execute(sql, (id_alvo,)))
                antes = self.foto()
                with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
                    with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_estorno_anterior_corrompido_e_acumulado_excessivo(self):
        r = sf.estornar_liquidacao(**self.p(valor_centavos=100))
        for caso in ('orfao', 'positivo', 'excesso'):
            destino = self.f.clone(caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                if caso == 'orfao':
                    self.h.corromper_fixture(('estornos_liquidacoes',), lambda c:
                        c.execute('UPDATE estornos_liquidacoes SET lancamento_estorno_id=999 WHERE id=?', r.estorno_ids))
                else:
                    valor = 100 if caso == 'positivo' else -1001
                    self.h.corromper_fixture(('lancamentos',), lambda c:
                        c.execute('UPDATE lancamentos SET valor_centavos=?,valor=CAST(? AS REAL)/100.0 WHERE id=?',
                            (valor, valor, r.lancamento_ids[0])))
                antes = self.foto()
                with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
                    with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**self.p(4, valor_centavos=1))
                self.assertEqual(self.foto(), antes)

    def test_ids_historicos_nao_positivos_preservados(self):
        for identificador in (-10, 0):
            destino = self.f.clone('id_'+str(identificador))
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                # Apenas fixture adversarial: nova tabela nao admite esses IDs
                # normalmente. O alocador nao deve reescrever registros existentes.
                self.h.corromper_fixture(('estornos_liquidacoes',), lambda c:
                    c.execute('INSERT INTO estornos_liquidacoes(id,liquidacao_id,lancamento_estorno_id,natureza,motivo) '
                        "VALUES(?,999,999,'devolucao_real','Historico')", (identificador,)))
                antes = self.foto()
                p = self.p()
                r = sf.estornar_liquidacao(**p)
                self.assertEqual(r.estorno_ids, (1,))
                self.conferir(p, r, antes)

    def test_esgotamento_de_id_estorno(self):
        self.h.corromper_fixture(('estornos_liquidacoes',), lambda c:
            c.execute('INSERT INTO estornos_liquidacoes(id,liquidacao_id,lancamento_estorno_id,natureza,motivo) '
                "VALUES(?,999,999,'devolucao_real','Historico')", (sf.MAX_CENTAVOS,)))
        antes = self.foto()
        with self.assertRaises(sf.IdentificadoresEsgotados): sf.estornar_liquidacao(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_rollback_apos_inserts_conclusao_e_falha_commit_fecha_conexao(self):
        abrir = banco.abrir_conexao
        antes = self.foto()
        for ponto in ('operacoes_hibridas', 'lancamentos', 'estornos_liquidacoes', 'conclusao', 'commit'):
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
                with self.assertRaises(sf.FalhaPersistencia) as erro: sf.estornar_liquidacao(**self.p())
            self.assertEqual(str(erro.exception.__cause__), 'injetada:'+ponto)
            self.assertTrue(proxy.fechada)
            self.assertEqual(self.foto(), antes)

    def test_resposta_perdida_apos_commit(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self): real.commit(); raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.estornar_liquidacao(**self.p())
        antes = self.foto()
        r = sf.estornar_liquidacao(**self.p())
        self.assertEqual(sf.estornar_liquidacao(**self.p()), r)
        self.assertEqual(self.foto(), antes)

    def test_completude_real_rejeita_ausente_extra_e_valor_divergente(self):
        abrir = banco.abrir_conexao
        for caso in ('ausente', 'extra', 'valor'):
            antes = self.foto()
            real = abrir()
            class Incompleta:
                def __getattr__(self, nome): return getattr(real, nome)
                def execute(self, sql, *args):
                    if sql.startswith('INSERT INTO lancamentos') and caso == 'valor':
                        valores = list(args[0]); valores[6] = valores[7] = -399
                        return real.execute(sql, valores)
                    if sql.startswith('INSERT INTO estornos_liquidacoes'):
                        if caso == 'ausente':
                            real.execute('SAVEPOINT fixture')
                            cur = real.execute(sql, *args)
                            real.execute('ROLLBACK TO fixture'); real.execute('RELEASE fixture')
                            return cur
                        cur = real.execute(sql, *args)
                        if caso == 'extra':
                            op = args[0][2]
                            op = real.execute('SELECT operacao_hibrida_id FROM lancamentos WHERE id=?', (op,)).fetchone()[0]
                            self_outer.f.caixa(real, op, centavos=-1)
                        return cur
                    return real.execute(sql, *args)
            self_outer = self
            with patch.object(banco, 'abrir_conexao', return_value=Incompleta()):
                with self.assertRaises(sf.OperacaoIncompleta): sf.estornar_liquidacao(**self.p())
            self.assertEqual(self.foto(), antes)

    def test_concorrencia_real_mesma_chave_e_saldo_disputado(self):
        for mesmo in (True, False):
            destino = self.f.clone('concorrente_'+str(mesmo))
            pronta, liberar, terminou, ocupado = (threading.Event() for _ in range(4))
            resultados, erros = {}, {}
            abrir = banco.abrir_conexao
            def abrir_controlada():
                real = abrir(); real.execute('PRAGMA busy_timeout=1')
                if threading.current_thread().name != 'estorno-a': return real
                class Suspensa:
                    def __getattr__(self, nome): return getattr(real, nome)
                    def commit(self):
                        pronta.set()
                        if not liberar.wait(10): raise AssertionError('nao liberou')
                        real.commit()
                return Suspensa()
            p_a = self.p(valor_centavos=700)
            p_b = self.p(3 if mesmo else 4, valor_centavos=700)
            def a():
                try: resultados['a'] = sf.estornar_liquidacao(**p_a)
                except BaseException as erro: erros['a'] = erro
                finally: terminou.set()
            def b():
                try:
                    if not pronta.wait(10): raise AssertionError('A nao chegou ao commit')
                    try:
                        sf.estornar_liquidacao(**p_b)
                        raise AssertionError('Nao disputou lock')
                    except sf.BancoOcupado as erro:
                        if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                        ocupado.set()
                    if not terminou.wait(10): raise AssertionError('A nao terminou')
                    resultados['b'] = sf.estornar_liquidacao(**p_b)
                except BaseException as erro: erros['b'] = erro
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), \
                    patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
                ta, tb = threading.Thread(target=a, name='estorno-a'), threading.Thread(target=b, name='estorno-b')
                ta.start(); tb.start()
                try: self.assertTrue(ocupado.wait(10), 'Sem disputa SQLite comprovada')
                finally: liberar.set(); ta.join(15); tb.join(15)
                self.assertFalse(ta.is_alive() or tb.is_alive())
            self.assertNotIn('a', erros)
            if mesmo:
                self.assertFalse(erros)
                self.assertEqual(resultados['a'], resultados['b'])
            else: self.assertIsInstance(erros.get('b'), sf.EstornoExcessivo)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), closing(banco.abrir_conexao()) as c:
                self.assertEqual(c.execute('SELECT l.valor_centavos FROM estornos_liquidacoes s '
                    'JOIN lancamentos l ON l.id=s.lancamento_estorno_id WHERE s.liquidacao_id=?', (self.q,)).fetchall(), [(-700,)])
                self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (3,))


if __name__ == '__main__':
    unittest.main()
