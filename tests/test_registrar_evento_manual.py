"""Contrato publico 3.2B.2; todo SQLite e temporario via KAIRUA_DB_PATH."""
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
import inspect
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

import banco
import servicos_financeiros as sf
import test_migracao_3 as base


def parametros(numero=1):
    return dict(chave='kairua:v1:'+str(UUID(int=numero)), tipo='despesa',
                descricao='  Cafe\u0301  mensal  ', categoria_id=1, valor_centavos=1250,
                data_competencia=date(2026, 11, 1), data_vencimento=date(2026, 12, 15),
                confirmar_ocorrencia=True)


class TestRegistrarEventoManual(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.legado_v2 = self.f.clone('antes_da_versao_3')
        self.f.migrar()

    def foto(self):
        with closing(banco.abrir_conexao()) as c:
            return {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def assert_sem_caixa_nem_outros_efeitos(self, antes):
        depois = self.foto()
        for tabela, dados in antes.items():
            if tabela not in ('operacoes_hibridas', 'eventos_financeiros'):
                self.assertEqual(depois[tabela], dados, tabela)

    def test_assinatura_obrigatoria_e_somente_servicos_autorizados(self):
        assinatura = inspect.signature(sf.registrar_evento_manual)
        self.assertEqual(set(assinatura.parameters), set(parametros()))
        for p in assinatura.parameters.values():
            self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(p.default, inspect.Parameter.empty)
        self.assertTrue(callable(sf.registrar_operacao_imediata))
        self.assertTrue(callable(sf.liquidar_evento))
        self.assertTrue(callable(sf.estornar_liquidacao))
        self.assertTrue(callable(sf.reverter_evento))
        self.assertTrue(callable(sf.reclassificar_evento))

    def test_despesa_confirmada_normalizada_e_sem_caixa(self):
        antes = self.foto()
        p = parametros()
        resultado = sf.registrar_evento_manual(**p)
        self.assertGreater(resultado.operacao_id, 0)
        self.assertEqual(len(resultado.evento_ids), 1)
        self.assertGreater(resultado.evento_ids[0], 0)
        for campo in ('lancamento_ids', 'liquidacao_ids', 'estorno_ids', 'reversao_ids', 'reclassificacao_ids'):
            self.assertEqual(getattr(resultado, campo), ())
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT tipo,descricao,categoria_id,valor_centavos,'
                'typeof(valor_centavos),data_competencia,data_vencimento,situacao_competencia,'
                'origem_tipo,chave_origem,operacao_hibrida_id,compra_cartao_id,parcelamento_id,'
                'parcela_comum_id,ocorrencia_id,lancamento_legado_id FROM eventos_financeiros').fetchall(),
                [('despesa', 'Café  mensal', 1, 1250, 'integer', '2026-11-01', '2026-12-15',
                  'confirmada', 'manual', 'manual:'+p['chave']+':evento:0', resultado.operacao_id,
                  None, None, None, None, None)])
            self.assertEqual(c.execute('SELECT tipo,estado FROM operacoes_hibridas').fetchall(),
                             [('registrar_evento', 'concluida')])
        self.assert_sem_caixa_nem_outros_efeitos(antes)

    def test_receita_e_valores_extremos_int64_sem_conversao_real(self):
        with closing(banco.abrir_conexao()) as c:
            categoria = c.execute("SELECT id FROM categorias WHERE tipo='receita' ORDER BY id LIMIT 1").fetchone()[0]
        for i, valor in enumerate((1, sf.MAX_CENTAVOS), start=1):
            with self.subTest(valor=valor):
                p = parametros(i) | dict(tipo='receita', categoria_id=categoria, valor_centavos=valor)
                recibo = sf.registrar_evento_manual(**p)
                with closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT tipo,categoria_id,valor_centavos FROM eventos_financeiros WHERE id=?',
                        recibo.evento_ids).fetchone(), ('receita', categoria, valor))

    def test_datas_passadas_futuras_e_vencimento_independente(self):
        for i, (competencia, vencimento) in enumerate(((date.min, date.max),
                (date.max, date.min), (date(2024, 2, 29), date(2025, 1, 1))), start=1):
            with self.subTest(competencia=competencia):
                r = sf.registrar_evento_manual(**(parametros(i) | dict(
                    data_competencia=competencia, data_vencimento=vencimento)))
                with closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT data_competencia,data_vencimento FROM eventos_financeiros WHERE id=?',
                        r.evento_ids).fetchone(), (competencia.isoformat(), vencimento.isoformat()))

    def test_entradas_invalidas_rejeitadas_antes_de_abrir_conexao(self):
        casos = [({'confirmar_ocorrencia': False}, sf.ConfirmacaoNecessaria),
            ({'confirmar_ocorrencia': None}, sf.ParametroInvalido),
            ({'confirmar_ocorrencia': 1}, sf.ParametroInvalido),
            ({'tipo': 'estimada'}, sf.ParametroInvalido),
            ({'categoria_id': True}, sf.ParametroInvalido),
            ({'categoria_id': 1.0}, sf.ParametroInvalido),
            ({'descricao': ' \t\n '}, sf.ParametroInvalido),
            ({'data_competencia': '2023-02-29'}, sf.DataInvalida),
            ({'data_vencimento': datetime(2026, 1, 1)}, sf.DataInvalida),
            ({'chave': 'kairua:v1:invalida'}, sf.ParametroInvalido)]
        casos += [({'valor_centavos': valor}, sf.ValorInvalido)
                  for valor in (0, -1, 2**63, True, False, 12.5, Decimal('12.50'), '1250')]
        antes = self.foto()
        for mudancas, erro in casos:
            with self.subTest(mudancas=mudancas), patch.object(banco, 'abrir_conexao',
                    side_effect=AssertionError('nao pode abrir')):
                with self.assertRaises(erro): sf.registrar_evento_manual(**(parametros() | mudancas))
        self.assertEqual(self.foto(), antes)

    def test_confirmacao_omitida_nao_tem_default(self):
        p = parametros()
        del p['confirmar_ocorrencia']
        with patch.object(banco, 'abrir_conexao', side_effect=AssertionError('nao pode abrir')):
            with self.assertRaises(TypeError): sf.registrar_evento_manual(**p)

    def test_categoria_inexistente_ou_incompativel_sem_operacao_persistida(self):
        antes = self.foto()
        for mudancas, erro in (({'categoria_id': 99999}, sf.CategoriaInexistente),
                               ({'tipo': 'receita'}, sf.CategoriaIncompativel)):
            with self.subTest(mudancas=mudancas), self.assertRaises(erro):
                sf.registrar_evento_manual(**(parametros() | mudancas))
            self.assertEqual(self.foto(), antes)

    def test_categoria_legada_negativa_existente_e_valida(self):
        with closing(banco.abrir_conexao()) as c:
            c.execute("INSERT INTO categorias(id,nome,tipo) VALUES(-5,'Legada negativa','despesa')")
            c.commit()
        r = sf.registrar_evento_manual(**(parametros() | {'categoria_id': -5}))
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_id FROM eventos_financeiros WHERE id=?',
                                       r.evento_ids).fetchone(), (-5,))

    def test_replay_normalizado_sem_gravacoes_e_payload_conflitante(self):
        p = parametros()
        primeiro = sf.registrar_evento_manual(**p)
        antes = self.foto()
        with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('replay gravou')):
            self.assertEqual(sf.registrar_evento_manual(**(p | {'descricao': 'Café  mensal'})), primeiro)
        for mudancas in ({'valor_centavos': 1251}, {'descricao': 'Café mensal'},
                         {'data_vencimento': date(2027, 1, 1)}, {'categoria_id': 99999}):
            with self.subTest(mudancas=mudancas), self.assertRaises(sf.ConflitoIdempotencia):
                sf.registrar_evento_manual(**(p | mudancas))
        self.assertEqual(self.foto(), antes)

    def test_operacao_aberta_persistida_nao_e_completada(self):
        p = parametros()
        req = sf.canonicalizar_requisicao('registrar_evento_manual', **p)
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                      (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.registrar_evento_manual(**p)
        self.assertEqual(self.foto(), antes)

    def test_replay_apos_liquidacao_reclassificacao_reversao_e_renomeacao(self):
        p = parametros()
        esperado = sf.registrar_evento_manual(**p)
        evento = esperado.evento_ids[0]
        with self.f.conectar() as c:
            q = self.f.liquidar(c, evento, 100)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        self.assertEqual(sf.registrar_evento_manual(**p), esperado)
        with self.f.conectar() as c:
            self.f.estornar(c, q, 100)
            self.f.reclassificar(c, evento, 2)
            self.f.reverter(c, evento)
            c.execute("UPDATE categorias SET nome='Nome atualizado' WHERE id=1")
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        self.assertEqual(sf.registrar_evento_manual(**p), esperado)
        self.assertEqual(self.foto(), antes)

    def preparar_historico(self, ids, nome, origem=None):
        destino = self.f.caminho.with_name(nome+'.db')
        with closing(sqlite3.connect(self.legado_v2)) as fonte, closing(sqlite3.connect(destino)) as copia:
            fonte.backup(copia)
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            with closing(banco.abrir_conexao()) as c:
                for id_legado in ids:
                    c.execute('INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,'
                        'situacao_competencia,chave_origem) VALUES(?,?,?,?,?,?,?)',
                        (id_legado, 'despesa', 'Historico', 1, 99, 'pendente',
                         origem or 'historico:'+str(id_legado)))
                c.commit()
            banco.aplicar_migracoes(destino)
        return destino

    def test_ids_legados_negativos_zero_e_alocacao_positiva_sem_reescrever(self):
        for i, ids in enumerate(([-10], [-1], [0], [-10, -1, 0])):
            with self.subTest(ids=ids):
                destino = self.preparar_historico(ids, f'legado_{i}')
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    antes = self.foto()
                    r = sf.registrar_evento_manual(**parametros())
                    r2 = sf.registrar_evento_manual(**parametros(2))
                    self.assertEqual(r.evento_ids, (1,))
                    self.assertEqual(r2.evento_ids, (2,))
                    with closing(banco.abrir_conexao()) as c:
                        self.assertEqual(c.execute('SELECT * FROM eventos_financeiros WHERE id<=0 ORDER BY id').fetchall(),
                                         antes['eventos_financeiros'])
                        self.assertEqual(c.execute('SELECT origem_tipo FROM eventos_financeiros WHERE id<=0').fetchall(),
                                         [(None,)] * len(ids))
                    self.assert_sem_caixa_nem_outros_efeitos(antes)

    def test_id_evento_esgotado_rejeita_antes_de_inserir_operacao(self):
        destino = self.preparar_historico([sf.MAX_CENTAVOS], 'esgotado')
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            antes = self.foto()
            with self.assertRaises(sf.IdentificadoresEsgotados):
                sf.registrar_evento_manual(**parametros())
            self.assertEqual(self.foto(), antes)

    def test_ultimo_id_positivo_e_replay_permitidos_antes_de_esgotamento(self):
        destino = self.preparar_historico([sf.MAX_CENTAVOS - 1], 'ultimo_id')
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            r = sf.registrar_evento_manual(**parametros())
            self.assertEqual(r.evento_ids, (sf.MAX_CENTAVOS,))
            antes = self.foto()
            self.assertEqual(sf.registrar_evento_manual(**parametros()), r)
            with self.assertRaises(sf.IdentificadoresEsgotados):
                sf.registrar_evento_manual(**parametros(2))
            self.assertEqual(self.foto(), antes)

    def test_colisao_de_origem_historica_nao_e_replay_nem_adocao(self):
        p = parametros()
        destino = self.preparar_historico([5], 'origem_ocupada', 'manual:'+p['chave']+':evento:0')
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            antes = self.foto()
            with self.assertRaises(sf.FalhaPersistencia): sf.registrar_evento_manual(**p)
            self.assertEqual(self.foto(), antes)

    def test_ordem_real_do_sql_categoria_validada_sob_lock(self):
        abrir = banco.abrir_conexao
        sqls = []
        conexoes = []
        def abrir_rastreada():
            c = abrir()
            c.set_trace_callback(sqls.append)
            conexoes.append(c)
            return c
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_rastreada):
            sf.registrar_evento_manual(**parametros())
        def posicao(texto):
            return next(i for i, sql in enumerate(sqls) if texto in sql)
        self.assertLess(posicao('BEGIN IMMEDIATE'), posicao('FROM operacoes_hibridas WHERE chave='))
        self.assertLess(posicao('FROM operacoes_hibridas WHERE chave='), posicao('SELECT tipo FROM categorias'))
        self.assertLess(posicao('SELECT tipo FROM categorias'), posicao('INSERT INTO operacoes_hibridas'))
        self.assertLess(posicao('INSERT INTO operacoes_hibridas'), posicao('INSERT INTO eventos_financeiros'))
        self.assertLess(posicao('INSERT INTO eventos_financeiros'), posicao("SET estado='concluida'"))
        self.assertLess(posicao("SET estado='concluida'"), posicao('COMMIT'))
        with self.assertRaises(sqlite3.ProgrammingError): conexoes[0].execute('SELECT 1')

    def test_rollback_integral_entre_insercoes_conclusao_e_commit(self):
        antes = self.foto()
        abrir = banco.abrir_conexao
        for ponto in ('apos_operacao', 'antes_evento', 'apos_evento', 'conclusao', 'commit'):
            with self.subTest(ponto=ponto):
                real = abrir()
                class FalhaControlada:
                    fechada = False
                    def __getattr__(self, nome): return getattr(real, nome)
                    def execute(self, sql, *args):
                        if ponto == 'antes_evento' and sql.startswith('INSERT INTO eventos_financeiros'):
                            raise sqlite3.OperationalError('falha antes do evento')
                        cursor = real.execute(sql, *args)
                        if ((ponto == 'apos_operacao' and sql.startswith('INSERT INTO operacoes_hibridas')) or
                            (ponto == 'apos_evento' and sql.startswith('INSERT INTO eventos_financeiros')) or
                            (ponto == 'conclusao' and sql.startswith('UPDATE operacoes_hibridas'))):
                            raise sqlite3.OperationalError('falha apos escrita')
                        return cursor
                    def commit(self):
                        if ponto == 'commit': raise sqlite3.OperationalError('falha no commit')
                        real.commit()
                    def close(self):
                        self.fechada = True
                        real.close()
                proxy = FalhaControlada()
                with patch.object(banco, 'abrir_conexao', return_value=proxy):
                    with self.assertRaises(sf.FalhaPersistencia): sf.registrar_evento_manual(**parametros())
                self.assertTrue(proxy.fechada)
                self.assertEqual(self.foto(), antes)

    def test_guarda_de_completude_reverte_evento_extra_injetado(self):
        antes = self.foto()
        real = banco.abrir_conexao()
        class EventoExtra:
            def __getattr__(self, nome): return getattr(real, nome)
            def execute(self, sql, *args):
                cursor = real.execute(sql, *args)
                if sql.startswith('INSERT INTO eventos_financeiros'):
                    real.execute('INSERT INTO eventos_financeiros(tipo,descricao,categoria_id,valor_centavos,'
                        'data_competencia,situacao_competencia,chave_origem,operacao_hibrida_id,data_vencimento,origem_tipo) '
                        "SELECT tipo,descricao,categoria_id,valor_centavos,data_competencia,situacao_competencia,"
                        "chave_origem||':extra',operacao_hibrida_id,data_vencimento,origem_tipo "
                        'FROM eventos_financeiros WHERE id=?', (cursor.lastrowid,))
                return cursor
        with patch.object(banco, 'abrir_conexao', return_value=EventoExtra()):
            with self.assertRaises(sf.OperacaoIncompleta): sf.registrar_evento_manual(**parametros())
        self.assertEqual(self.foto(), antes)

    def test_perda_de_resposta_apos_commit_recupera_mesma_intencao(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self):
                real.commit()
                raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.registrar_evento_manual(**parametros())
        antes = self.foto()
        r = sf.registrar_evento_manual(**parametros())
        self.assertEqual(sf.registrar_evento_manual(**parametros()), r)
        self.assertEqual(len(antes['operacoes_hibridas']), 1)
        self.assertEqual(len(antes['eventos_financeiros']), 1)
        self.assertEqual(self.foto(), antes)

    def test_concorrencia_mesma_chave_disputa_real_e_retry_sem_duplicar(self):
        # A mantem lock no commit; B precisa observar SQLITE_BUSY antes da
        # liberacao de A. A mesma chave/payload e repetida explicitamente em B.
        pronta, ocupado, liberar, confirmou = (threading.Event() for _ in range(4))
        resultados, erros = {}, {}
        abrir = banco.abrir_conexao
        def abrir_controlada():
            real = abrir()
            real.execute('PRAGMA busy_timeout=1')
            if threading.current_thread().name != 'evento-a': return real
            class SegurarCommit:
                def __getattr__(self, nome): return getattr(real, nome)
                def commit(self):
                    pronta.set()
                    if not liberar.wait(10): raise AssertionError('Commit nao liberado')
                    real.commit()
            return SegurarCommit()
        def executar_a():
            try: resultados['a'] = sf.registrar_evento_manual(**parametros())
            except BaseException as erro: erros['a'] = erro
            finally: confirmou.set()
        def executar_b():
            try:
                if not pronta.wait(10): raise AssertionError('A nao segurou commit')
                try:
                    sf.registrar_evento_manual(**parametros())
                    raise AssertionError('B deveria disputar o lock')
                except sf.BancoOcupado as erro:
                    if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                    ocupado.set()
                if not confirmou.wait(10): raise AssertionError('A nao terminou')
                resultados['b'] = sf.registrar_evento_manual(**parametros())
            except BaseException as erro: erros['b'] = erro
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
            a = threading.Thread(target=executar_a, name='evento-a')
            b = threading.Thread(target=executar_b, name='evento-b')
            a.start(); b.start()
            try:
                self.assertTrue(ocupado.wait(10), 'Nao houve disputa SQLite comprovada')
            finally:
                liberar.set(); a.join(15); b.join(15)
            self.assertFalse(a.is_alive() or b.is_alive())
        self.assertFalse(erros)
        self.assertEqual(resultados['a'], resultados['b'])
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (1,))
            self.assertEqual(c.execute('SELECT count(*) FROM eventos_financeiros').fetchone(), (1,))


if __name__ == '__main__':
    unittest.main()
