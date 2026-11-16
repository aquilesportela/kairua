"""Consolidacao 3.2B.7: servicos publicos, SQLite temporario e locks reais."""
from contextlib import closing
from datetime import date
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

import banco
import servicos_financeiros as sf
import test_migracao_3 as base


def chave(numero):
    return 'kairua:v1:' + str(UUID(int=numero))


def foto_conexao(c):
    tabelas = c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for (t,) in tabelas}


class TestIntegracaoServicosFinanceiros(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()  # KAIRUA_DB_PATH temporario antes de qualquer inicializacao.
        self.v2 = self.f.clone('antes_da_migracao_3')
        self.f.migrar()

    def foto(self):
        with closing(banco.abrir_conexao()) as c:
            return foto_conexao(c)

    def p_evento(self, numero=1, valor=1000):
        return dict(chave=chave(numero), tipo='despesa', descricao='Evento integrado',
            categoria_id=1, valor_centavos=valor, data_competencia=date(2026, 11, 1),
            data_vencimento=date(2026, 12, 15), confirmar_ocorrencia=True)

    def p_liquidacao(self, evento, numero=2, valor=400):
        return dict(chave=chave(numero), evento_id=evento, valor_centavos=valor,
            data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)

    def p_reversao(self, evento, numero=3):
        return dict(chave=chave(numero), evento_id=evento, data_reversao=date(2026, 11, 10),
            motivo='Ocorrencia cancelada')

    def p_reclassificacao(self, evento, numero=3):
        return dict(chave=chave(numero), evento_id=evento, categoria_nova_id=2,
            motivo='Categoria revisada', categoria_anterior_esperada_id=1)

    def p_estorno(self, liquidacao, numero=3, valor=400):
        return dict(chave=chave(numero), liquidacao_id=liquidacao, valor_centavos=valor,
            natureza='devolucao_real', motivo='Devolucao integrada',
            data_estorno=date(2026, 11, 2), confirmar_datas_divergentes=True)

    def conferir_delta(self, antes, depois, novos):
        self.assertEqual(set(antes), set(depois))
        for tabela, dados in antes.items():
            if tabela in novos:
                self.assertEqual(len(depois[tabela]), len(dados)+1, tabela)
                self.assertTrue(all(linha in depois[tabela] for linha in dados), tabela)
            elif tabela != 'sqlite_sequence':
                self.assertEqual(depois[tabela], dados, tabela)

    def executar(self, servico, parametros, novos):
        antes = self.foto()
        r = servico(**parametros)
        self.conferir_delta(antes, self.foto(), ('operacoes_hibridas', *novos))
        return r

    def estado(self, evento):
        """Oraculo independente: linhas inteiras, sem SUM/REAL ou helper privado."""
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            valor, = c.execute('SELECT valor_centavos FROM eventos_financeiros WHERE id=?', (evento,)).fetchone()
            self.assertIs(type(valor), int)
            liquido = 0
            for q, magnitude in c.execute('SELECT id,valor_centavos FROM liquidacoes_eventos WHERE evento_id=? ORDER BY id', (evento,)):
                self.assertIs(type(magnitude), int)
                self.assertGreater(magnitude, 0)
                parcial = magnitude
                for (id_caixa,) in c.execute('SELECT lancamento_estorno_id FROM estornos_liquidacoes WHERE liquidacao_id=?', (q,)):
                    retorno, = c.execute('SELECT valor_centavos FROM lancamentos WHERE id=?', (id_caixa,)).fetchone()
                    self.assertIs(type(retorno), int)
                    self.assertLess(retorno, 0)
                    parcial += retorno
                self.assertGreaterEqual(parcial, 0)
                self.assertLessEqual(parcial, magnitude)
                liquido += parcial
            self.assertLessEqual(liquido, valor)
            categoria, = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?', (evento,)).fetchone()
            revertido = c.execute('SELECT 1 FROM reversoes_eventos WHERE evento_id=?', (evento,)).fetchone() is not None
            return valor, liquido, valor-liquido, categoria, revertido

    def conferir_caixa(self, recibo, valor, categoria):
        self.assertEqual(len(recibo.lancamento_ids), 1)
        with closing(banco.abrir_conexao()) as c:
            nome, = c.execute('SELECT nome FROM categorias WHERE id=?', (categoria,)).fetchone()
            self.assertEqual(c.execute('SELECT valor_centavos,typeof(valor_centavos),tipo,categoria_id,categoria,'
                'valor=CAST(valor_centavos AS REAL)/100.0,operacao_hibrida_id FROM lancamentos WHERE id=?',
                recibo.lancamento_ids).fetchone(), (valor, 'integer', 'despesa', categoria, nome, 1, recibo.operacao_id))

    def disputar(self, primeiro, p_primeiro, segundo, p_segundo):
        """A segura commit ate B demonstrar SQLITE_BUSY; B repete a mesma chave.

        Events ordenam o teste. Os timeouts apenas detectam travamento; nao ha
        sleeps nem simulacao de excecao financeira ou de lock SQLite.
        """
        pronta, liberar, terminou, ocupado = (threading.Event() for _ in range(4))
        resultados, erros, fotos, conexoes = {}, {}, {}, []
        abrir = banco.abrir_conexao

        def abrir_controlada():
            c = abrir()
            conexoes.append(c)
            c.execute('PRAGMA busy_timeout=1')
            if threading.current_thread().name != 'integracao-a': return c
            class CommitSuspenso:
                def __getattr__(self, nome): return getattr(c, nome)
                def commit(self):
                    pronta.set()
                    if not liberar.wait(15): raise AssertionError('Commit nao liberado')
                    c.commit()
                    fotos['primeiro'] = foto_conexao(c)
            return CommitSuspenso()

        def a():
            try: resultados['a'] = primeiro(**p_primeiro)
            except BaseException as erro: erros['a'] = erro
            finally: terminou.set()

        def b():
            try:
                if not pronta.wait(15): raise AssertionError('Primeiro servico nao chegou ao commit')
                try:
                    segundo(**p_segundo)
                    raise AssertionError('Segunda conexao nao disputou o lock')
                except sf.BancoOcupado as erro:
                    if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                    ocupado.set()
                if not terminou.wait(15): raise AssertionError('Primeiro servico nao terminou')
                resultados['b'] = segundo(**p_segundo)
            except BaseException as erro: erros['b'] = erro

        with patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
            ta = threading.Thread(target=a, name='integracao-a')
            tb = threading.Thread(target=b, name='integracao-b')
            ta.start(); tb.start()
            try: self.assertTrue(ocupado.wait(15), 'Disputa real de lock nao comprovada')
            finally: liberar.set(); ta.join(20); tb.join(20)
            self.assertFalse(ta.is_alive() or tb.is_alive(), 'Thread nao terminou')
        self.assertNotIn('a', erros)
        self.assertIn('a', resultados)
        self.assertIn('primeiro', fotos)
        # Uma conexao de A, uma tentativa ocupada de B e uma nova tentativa B.
        self.assertEqual(len(conexoes), 3)
        self.assertEqual(len({id(c) for c in conexoes}), 3)
        for c in conexoes:
            with self.assertRaises(sqlite3.ProgrammingError): c.execute('SELECT 1')
        return resultados, erros, fotos['primeiro']

    def test_a1_liquidacao_vence_reversao_sem_historico_de_reversao(self):
        e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
        antes = self.foto()
        resultados, erros, apos_primeiro = self.disputar(sf.liquidar_evento, self.p_liquidacao(e),
            sf.reverter_evento, self.p_reversao(e))
        self.assertIsInstance(erros.get('b'), sf.EventoAindaLiquidado)
        self.assertNotIn('b', resultados)
        self.assertEqual(self.foto(), apos_primeiro)
        self.conferir_delta(antes, apos_primeiro, ('operacoes_hibridas', 'lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (1000, 400, 600, 1, False))
        self.conferir_caixa(resultados['a'], 400, 1)
        self.assertEqual(apos_primeiro['reversoes_eventos'], [])

    def test_a2_reversao_vence_liquidacao_sem_caixa_ou_vinculo(self):
        e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
        antes = self.foto()
        resultados, erros, apos_primeiro = self.disputar(sf.reverter_evento, self.p_reversao(e),
            sf.liquidar_evento, self.p_liquidacao(e))
        self.assertIsInstance(erros.get('b'), sf.EventoRevertido)
        self.assertNotIn('b', resultados)
        self.assertEqual(self.foto(), apos_primeiro)
        self.conferir_delta(antes, apos_primeiro, ('operacoes_hibridas', 'reversoes_eventos'))
        self.assertEqual(apos_primeiro['liquidacoes_eventos'], [])
        self.assertEqual(self.estado(e), (1000, 0, 1000, 1, True))
        self.assertEqual((resultados['a'].lancamento_ids, resultados['a'].liquidacao_ids), ((), ()))

    def test_b1_reclassificacao_vence_liquidacao_captura_categoria_nova(self):
        e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
        antes = self.foto()
        resultados, erros, apos_primeiro = self.disputar(sf.reclassificar_evento, self.p_reclassificacao(e),
            sf.liquidar_evento, self.p_liquidacao(e))
        self.assertFalse(erros)
        self.conferir_delta(antes, apos_primeiro, ('operacoes_hibridas', 'reclassificacoes_eventos'))
        self.conferir_delta(apos_primeiro, self.foto(), ('operacoes_hibridas', 'lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (1000, 400, 600, 2, False))
        self.conferir_caixa(resultados['b'], 400, 2)

    def test_b2_liquidacao_vence_reclassificacao_preserva_categoria_anterior(self):
        e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
        antes = self.foto()
        resultados, erros, apos_primeiro = self.disputar(sf.liquidar_evento, self.p_liquidacao(e),
            sf.reclassificar_evento, self.p_reclassificacao(e))
        self.assertFalse(erros)
        self.conferir_delta(antes, apos_primeiro, ('operacoes_hibridas', 'lancamentos', 'liquidacoes_eventos'))
        self.conferir_delta(apos_primeiro, self.foto(), ('operacoes_hibridas', 'reclassificacoes_eventos'))
        self.assertEqual(self.estado(e), (1000, 400, 600, 2, False))
        self.conferir_caixa(resultados['a'], 400, 1)

    def test_liquidacoes_parciais_proximas_de_int64_com_estorno_e_centavo_residual(self):
        m = sf.MAX_CENTAVOS
        e = sf.registrar_evento_manual(**self.p_evento(valor=m)).evento_ids[0]
        a = self.executar(sf.liquidar_evento, self.p_liquidacao(e, valor=m-2), ('lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (m, m-2, 2, 1, False))
        self.conferir_caixa(a, m-2, 1)
        self.executar(sf.estornar_liquidacao, self.p_estorno(a.liquidacao_ids[0], numero=3, valor=1),
            ('lancamentos', 'estornos_liquidacoes'))
        self.assertEqual(self.estado(e), (m, m-3, 3, 1, False))
        b = self.executar(sf.liquidar_evento, self.p_liquidacao(e, numero=4, valor=2), ('lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (m, m-1, 1, 1, False))
        self.conferir_caixa(b, 2, 1)
        antes = self.foto()
        with self.assertRaises(sf.SaldoInsuficiente): sf.liquidar_evento(**self.p_liquidacao(e, numero=5, valor=2))
        self.assertEqual(self.foto(), antes)
        c = self.executar(sf.liquidar_evento, self.p_liquidacao(e, numero=5, valor=1), ('lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (m, m, 0, 1, False))
        self.conferir_caixa(c, 1, 1)
        self.assertEqual(len({a.lancamento_ids[0], b.lancamento_ids[0], c.lancamento_ids[0]}), 3)

    def test_liquidar_evento_aloca_ids_positivos_preservando_historicos_nao_positivos(self):
        for numero, ids in enumerate(((-10,), (-1,), (0,), (-10, -1, 0))):
            destino = self.f.caminho.with_name('ids_legados_'+str(numero)+'.db')
            with closing(sqlite3.connect(self.v2)) as fonte, closing(sqlite3.connect(destino)) as c:
                fonte.backup(c)
                c.execute('DELETE FROM lancamentos')  # Apenas legado sintetico temporario v2.
                for ident in ids:
                    c.execute('INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,'
                        'situacao_competencia,chave_origem) VALUES(?,?,?,?,?,?,?)',
                        (ident, 'despesa', 'Legado', 1, 1, 'pendente', 'legado:'+str(ident)))
                    c.execute('INSERT INTO lancamentos(id,data,descricao,tipo,categoria,categoria_id,valor) '
                        "VALUES(?,'2026-01-01','Legado','despesa','Legado',1,1)", (ident,))
                    c.execute('INSERT INTO liquidacoes_eventos(id,evento_id,lancamento_id,valor_centavos) VALUES(?,?,?,1)',
                        (ident, ident, ident))
                c.commit()
            with self.subTest(ids=ids), patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                banco.aplicar_migracoes(destino)
                e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
                self.assertGreater(e, 0)
                antes = self.foto()
                r = self.executar(sf.liquidar_evento, self.p_liquidacao(e), ('lancamentos', 'liquidacoes_eventos'))
                self.assertEqual(r.evento_ids, (e,))
                self.assertEqual(r.liquidacao_ids, (1,))
                # O AUTOINCREMENT conserva a sequencia 2 da fixture legada,
                # mesmo apos exclusao das linhas positivas do legado sintetico.
                self.assertEqual(r.lancamento_ids, (3,))
                self.conferir_caixa(r, 400, 1)
                self.assertEqual(self.estado(e), (1000, 400, 600, 1, False))
                with closing(banco.abrir_conexao()) as c:
                    for t in ('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'):
                        self.assertEqual(c.execute(f'SELECT * FROM {t} WHERE id<=0 ORDER BY id').fetchall(),
                            [linha for linha in antes[t] if linha[0] <= 0])

    def test_devolucao_real_aceita_exatamente_data_do_caixa_original(self):
        e = sf.registrar_evento_manual(**self.p_evento()).evento_ids[0]
        pago = sf.liquidar_evento(**self.p_liquidacao(e))
        p = self.p_estorno(pago.liquidacao_ids[0], valor=100)
        p.update(data_estorno=date(2026, 11, 1), confirmar_datas_divergentes=False)
        r = self.executar(sf.estornar_liquidacao, p, ('lancamentos', 'estornos_liquidacoes'))
        self.conferir_caixa(r, -100, 1)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT data FROM lancamentos WHERE id=?', r.lancamento_ids).fetchone(), ('2026-11-01',))
            self.assertEqual(c.execute('SELECT natureza FROM estornos_liquidacoes WHERE id=?', r.estorno_ids).fetchone(), ('devolucao_real',))
        self.assertEqual(self.estado(e), (1000, 300, 700, 1, False))

    def test_estorno_integral_de_max_centavos_em_uma_chamada(self):
        m = sf.MAX_CENTAVOS
        e = sf.registrar_evento_manual(**self.p_evento(valor=m)).evento_ids[0]
        pago = sf.liquidar_evento(**self.p_liquidacao(e, valor=m))
        p = self.p_estorno(pago.liquidacao_ids[0], valor=m)
        r = self.executar(sf.estornar_liquidacao, p, ('lancamentos', 'estornos_liquidacoes'))
        self.conferir_caixa(r, -m, 1)
        self.assertEqual(self.estado(e), (m, 0, m, 1, False))
        antes = self.foto()
        self.assertEqual(sf.estornar_liquidacao(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_fluxo_publico_manual_ate_reversao_com_replay_de_todas_as_operacoes(self):
        operacoes = []
        def fazer(servico, p, novos):
            r = self.executar(servico, p, novos)
            operacoes.append((servico, p, r))
            return r
        cadastro = fazer(sf.registrar_evento_manual, self.p_evento(), ('eventos_financeiros',))
        e = cadastro.evento_ids[0]
        self.assertEqual(self.estado(e), (1000, 0, 1000, 1, False))
        a = fazer(sf.liquidar_evento, self.p_liquidacao(e, valor=300), ('lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (1000, 300, 700, 1, False))
        self.conferir_caixa(a, 300, 1)
        fazer(sf.reclassificar_evento, self.p_reclassificacao(e), ('reclassificacoes_eventos',))
        self.assertEqual(self.estado(e), (1000, 300, 700, 2, False))
        b = fazer(sf.liquidar_evento, self.p_liquidacao(e, numero=4, valor=700), ('lancamentos', 'liquidacoes_eventos'))
        self.assertEqual(self.estado(e), (1000, 1000, 0, 2, False))
        self.conferir_caixa(b, 700, 2)
        s_a = fazer(sf.estornar_liquidacao, self.p_estorno(a.liquidacao_ids[0], numero=5, valor=300),
            ('lancamentos', 'estornos_liquidacoes'))
        self.assertEqual(self.estado(e), (1000, 700, 300, 2, False))
        self.conferir_caixa(s_a, -300, 1)
        s_b = fazer(sf.estornar_liquidacao, self.p_estorno(b.liquidacao_ids[0], numero=6, valor=700),
            ('lancamentos', 'estornos_liquidacoes'))
        self.assertEqual(self.estado(e), (1000, 0, 1000, 2, False))
        self.conferir_caixa(s_b, -700, 2)
        antes_reversao = self.foto()
        reversao = fazer(sf.reverter_evento, self.p_reversao(e, numero=7), ('reversoes_eventos',))
        self.assertEqual((reversao.evento_ids, len(reversao.reversao_ids)), ((e,), 1))
        self.assertEqual((reversao.lancamento_ids, reversao.liquidacao_ids, reversao.estorno_ids,
                          reversao.reclassificacao_ids), ((), (), (), ()))
        # Saldo aritmetico nao representa compromisso ativo apos reversao.
        self.assertEqual(self.estado(e), (1000, 0, 1000, 2, True))
        depois = self.foto()
        for t in ('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos', 'estornos_liquidacoes', 'reclassificacoes_eventos'):
            self.assertEqual(depois[t], antes_reversao[t], t)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_id,valor_centavos FROM eventos_financeiros WHERE id=?', (e,)).fetchone(), (1, 1000))
            self.assertEqual(c.execute('SELECT categoria_anterior_id,categoria_nova_id FROM reclassificacoes_eventos').fetchall(), [(1, 2)])
            self.assertEqual(c.execute('SELECT categoria_id,data_competencia FROM reversoes_eventos WHERE id=?', reversao.reversao_ids).fetchone(), (2, '2026-11-10'))
            movimentos = c.execute('SELECT valor_centavos FROM lancamentos WHERE operacao_hibrida_id IS NOT NULL').fetchall()
            self.assertEqual(sum(v for (v,) in movimentos), 0)
            self.assertEqual(c.execute("SELECT count(*) FROM operacoes_hibridas WHERE estado<>'concluida'").fetchone(), (0,))
        for servico, p, r in operacoes:
            self.assertEqual(servico(**p), r)
            self.assertEqual(self.foto(), depois)
        with self.assertRaises(sf.EventoRevertido): sf.liquidar_evento(**self.p_liquidacao(e, numero=8, valor=1))
        self.assertEqual(self.foto(), depois)

    def test_operacao_imediata_reclassificacao_estorno_e_reversao(self):
        p = self.p_evento()
        p.update(data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)
        imediato = self.executar(sf.registrar_operacao_imediata, p,
            ('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'))
        e = imediato.evento_ids[0]
        self.assertEqual(self.estado(e), (1000, 1000, 0, 1, False))
        self.executar(sf.reclassificar_evento, self.p_reclassificacao(e, numero=2), ('reclassificacoes_eventos',))
        retorno = self.executar(sf.estornar_liquidacao, self.p_estorno(imediato.liquidacao_ids[0], valor=1000),
            ('lancamentos', 'estornos_liquidacoes'))
        self.conferir_caixa(retorno, -1000, 1)
        self.executar(sf.reverter_evento, self.p_reversao(e, numero=4), ('reversoes_eventos',))
        self.assertEqual(self.estado(e), (1000, 0, 1000, 2, True))
        depois = self.foto()
        self.assertEqual(sf.registrar_operacao_imediata(**p), imediato)
        self.assertEqual(self.foto(), depois)


if __name__ == '__main__':
    unittest.main()
