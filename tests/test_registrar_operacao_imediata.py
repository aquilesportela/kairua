"""3.2B.3A: persistencia e concorrencia reais, somente SQLite temporario."""
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
        data_liquidacao=date(2026, 11, 1), confirmar_ocorrencia=True,
        confirmar_datas_divergentes=False)


class TestRegistrarOperacaoImediata(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.v2 = self.f.clone('legado_v2')
        self.f.migrar()

    def foto(self):
        with closing(banco.abrir_conexao()) as c:
            return {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def conferir_persistencia(self, p, recibo, antes):
        self.assertEqual(recibo.tipo_operacao, 'registrar_imediata')
        for ids in (recibo.evento_ids, recibo.lancamento_ids, recibo.liquidacao_ids):
            self.assertEqual(len(ids), 1)
            self.assertGreater(ids[0], 0)
        self.assertEqual((recibo.estorno_ids, recibo.reversao_ids, recibo.reclassificacao_ids), ((), (), ()))
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT tipo,descricao,categoria_id,valor_centavos,'
                'data_competencia,data_vencimento,situacao_competencia,origem_tipo,chave_origem,'
                'operacao_hibrida_id,compra_cartao_id,parcelamento_id,parcela_comum_id,ocorrencia_id,'
                'lancamento_legado_id FROM eventos_financeiros WHERE id=?', recibo.evento_ids).fetchone(),
                (p['tipo'], 'Café  mensal', p['categoria_id'], p['valor_centavos'],
                 p['data_competencia'].isoformat(), p['data_vencimento'].isoformat(), 'confirmada',
                 'manual', 'manual:'+p['chave']+':evento:0', recibo.operacao_id, None, None, None, None, None))
            nome = c.execute('SELECT nome FROM categorias WHERE id=?', (p['categoria_id'],)).fetchone()[0]
            self.assertEqual(c.execute('SELECT tipo,descricao,categoria_id,categoria,valor_centavos,'
                'typeof(valor_centavos),valor=CAST(valor_centavos AS REAL)/100.0,data,operacao_hibrida_id,'
                'recorrencia_id,parcelamento_id FROM lancamentos WHERE id=?', recibo.lancamento_ids).fetchone(),
                (p['tipo'], 'Café  mensal', p['categoria_id'], nome, p['valor_centavos'], 'integer', 1,
                 p['data_liquidacao'].isoformat(), recibo.operacao_id, None, None))
            self.assertEqual(c.execute('SELECT evento_id,lancamento_id,valor_centavos FROM liquidacoes_eventos '
                'WHERE id=?', recibo.liquidacao_ids).fetchone(),
                (recibo.evento_ids[0], recibo.lancamento_ids[0], p['valor_centavos']))
            self.assertEqual(c.execute('SELECT chave,tipo,estado FROM operacoes_hibridas WHERE id=?',
                (recibo.operacao_id,)).fetchone(), (p['chave'], 'registrar_imediata', 'concluida'))
        depois = self.foto()
        for t in ('operacoes_hibridas', 'eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'):
            self.assertEqual(len(depois[t]), len(antes[t])+1, t)
            self.assertTrue(all(linha in depois[t] for linha in antes[t]), t)
        for t, linhas in antes.items():
            if t not in ('operacoes_hibridas', 'eventos_financeiros', 'lancamentos', 'liquidacoes_eventos', 'sqlite_sequence'):
                self.assertEqual(depois[t], linhas, t)

    def test_assinatura_obrigatoria_sem_outros_servicos(self):
        assinatura = inspect.signature(sf.registrar_operacao_imediata)
        self.assertEqual(set(assinatura.parameters), set(parametros()))
        self.assertIs(assinatura.return_annotation, sf.ResultadoOperacao)
        for p in assinatura.parameters.values():
            self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(p.default, inspect.Parameter.empty)
        self.assertTrue(callable(sf.liquidar_evento))
        self.assertTrue(callable(sf.estornar_liquidacao))
        self.assertTrue(callable(sf.reverter_evento))
        self.assertTrue(callable(sf.reclassificar_evento))

    def test_despesa_integral_uma_competencia_um_caixa_um_vinculo(self):
        antes = self.foto()
        p = parametros()
        with patch.object(sf, 'registrar_evento_manual', side_effect=AssertionError('transacao separada')):
            recibo = sf.registrar_operacao_imediata(**p)
        self.conferir_persistencia(p, recibo, antes)

    def test_receita_integral_e_categoria_capturada_do_cadastro(self):
        with closing(banco.abrir_conexao()) as c:
            categoria = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
        p = parametros() | dict(tipo='receita', categoria_id=categoria)
        antes = self.foto()
        self.conferir_persistencia(p, sf.registrar_operacao_imediata(**p), antes)

    def test_tres_datas_independentes_confirmadas(self):
        p = parametros() | dict(data_competencia=date(2026, 11, 5),
            data_vencimento=date(2027, 3, 1), data_liquidacao=date(2026, 12, 2),
            confirmar_datas_divergentes=True)
        antes = self.foto()
        self.conferir_persistencia(p, sf.registrar_operacao_imediata(**p), antes)

    def test_datas_passadas_futuras_sem_inferencias(self):
        for i, (competencia, caixa, vencimento) in enumerate(((date.min, date.max, date(2024, 2, 29)),
                (date.max, date.min, date(2020, 1, 1))), start=1):
            with self.subTest(competencia=competencia):
                p = parametros(i) | dict(data_competencia=competencia, data_liquidacao=caixa,
                    data_vencimento=vencimento, confirmar_datas_divergentes=True)
                antes = self.foto()
                self.conferir_persistencia(p, sf.registrar_operacao_imediata(**p), antes)

    def test_confirmacoes_tipo_invalido_ou_divergencia_nao_confirmada(self):
        casos = [dict(confirmar_ocorrencia=False), dict(confirmar_ocorrencia=1),
            dict(confirmar_ocorrencia=None), dict(confirmar_datas_divergentes=1),
            dict(confirmar_datas_divergentes=None),
            dict(data_liquidacao=date(2027, 1, 1), confirmar_datas_divergentes=False)]
        for mudanca in casos:
            with self.subTest(mudanca=mudanca), patch.object(banco, 'abrir_conexao',
                    side_effect=AssertionError('abriu com entrada invalida')):
                with self.assertRaises(sf.ParametroInvalido):
                    sf.registrar_operacao_imediata(**(parametros() | mudanca))

    def test_campos_obrigatorios_sem_defaults(self):
        for campo in parametros():
            p = parametros(); del p[campo]
            with self.subTest(campo=campo), self.assertRaises(TypeError):
                sf.registrar_operacao_imediata(**p)

    def test_valores_tipos_textos_datas_e_chaves_invalidos(self):
        mudancas = [dict(valor_centavos=v) for v in (0, -1, 2**63, True, False, 1.5, '100', Decimal('1'))]
        mudancas += [dict(tipo='outro'), dict(categoria_id=True), dict(descricao=' \n '),
                     dict(data_liquidacao='2026-11-01'), dict(data_competencia=datetime(2026, 1, 1)),
                     dict(data_vencimento=None), dict(chave='chave invalida')]
        antes = self.foto()
        for mudanca in mudancas:
            with self.subTest(mudanca=mudanca), patch.object(banco, 'abrir_conexao',
                    side_effect=AssertionError('abriu com entrada invalida')):
                with self.assertRaises(sf.ParametroInvalido):
                    sf.registrar_operacao_imediata(**(parametros() | mudanca))
        self.assertEqual(self.foto(), antes)

    def test_categoria_inexistente_ou_incompativel_nao_grava(self):
        antes = self.foto()
        for mudanca, erro in ((dict(categoria_id=99999), sf.CategoriaInexistente),
                               (dict(tipo='receita'), sf.CategoriaIncompativel)):
            with self.subTest(mudanca=mudanca), self.assertRaises(erro):
                sf.registrar_operacao_imediata(**(parametros() | mudanca))
            self.assertEqual(self.foto(), antes)

    def test_limites_monetarios_e_projecao_real_sem_float_no_dominio(self):
        for i, valor in enumerate((1, 2**53+1, sf.MAX_CENTAVOS), start=1):
            with self.subTest(valor=valor):
                p = parametros(i) | dict(valor_centavos=valor)
                antes = self.foto()
                self.conferir_persistencia(p, sf.registrar_operacao_imediata(**p), antes)

    def test_replay_mesmos_ids_sem_gravacoes_e_conflito_payload(self):
        p = parametros()
        r = sf.registrar_operacao_imediata(**p)
        antes = self.foto()
        with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('replay gravou')):
            self.assertEqual(sf.registrar_operacao_imediata(**(p | dict(descricao='Café  mensal'))), r)
        for mudanca in (dict(valor_centavos=1251), dict(descricao='Café mensal'),
                dict(data_vencimento=date(2027, 1, 1)), dict(categoria_id=99999),
                dict(confirmar_datas_divergentes=True)):
            with self.subTest(mudanca=mudanca), self.assertRaises(sf.ConflitoIdempotencia):
                sf.registrar_operacao_imediata(**(p | mudanca))
        self.assertEqual(self.foto(), antes)

    def test_chave_de_competencia_manual_nao_pode_ser_reusada_para_imediata(self):
        p = parametros()
        manual = {k: v for k, v in p.items() if k not in ('data_liquidacao', 'confirmar_datas_divergentes')}
        sf.registrar_evento_manual(**manual)
        antes = self.foto()
        with self.assertRaises(sf.ConflitoIdempotencia): sf.registrar_operacao_imediata(**p)
        self.assertEqual(self.foto(), antes)

    def test_operacao_aberta_preexistente_nao_e_retomada(self):
        req = sf.canonicalizar_requisicao('registrar_operacao_imediata', **parametros())
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.registrar_operacao_imediata(**parametros())
        self.assertEqual(self.foto(), antes)

    def test_replay_apos_estorno_reclassificacao_reversao_e_renomeacao(self):
        p = parametros()
        r = sf.registrar_operacao_imediata(**p)
        with self.f.conectar() as c:
            self.f.estornar(c, r.liquidacao_ids[0], p['valor_centavos'])
            self.f.reclassificar(c, r.evento_ids[0], 2)
            self.f.reverter(c, r.evento_ids[0])
            c.execute("UPDATE categorias SET nome='Novo nome' WHERE id=1")
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        self.assertEqual(sf.registrar_operacao_imediata(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_ordem_sql_e_recibo_somente_apos_commit(self):
        abrir = banco.abrir_conexao
        sqls, conexoes = [], []
        def abrir_rastreada():
            c = abrir(); c.set_trace_callback(sqls.append); conexoes.append(c); return c
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_rastreada):
            r = sf.registrar_operacao_imediata(**parametros())
        partes = ('BEGIN IMMEDIATE', 'FROM operacoes_hibridas WHERE chave=', 'SELECT nome,tipo FROM categorias',
            'INSERT INTO operacoes_hibridas', 'INSERT INTO eventos_financeiros', 'INSERT INTO lancamentos',
            'INSERT INTO liquidacoes_eventos', "SET estado='concluida'", 'COMMIT')
        posicoes = [next(i for i, sql in enumerate(sqls) if parte in sql) for parte in partes]
        self.assertEqual(posicoes, sorted(set(posicoes)))
        self.assertIsInstance(r, sf.ResultadoOperacao)
        with self.assertRaises(sqlite3.ProgrammingError): conexoes[0].execute('SELECT 1')

    def test_falhas_apos_cada_insert_conclusao_e_antes_commit_revertem_tudo(self):
        antes = self.foto()
        abrir = banco.abrir_conexao
        for ponto in ('operacoes_hibridas', 'eventos_financeiros', 'lancamentos',
                      'liquidacoes_eventos', 'conclusao', 'commit'):
            with self.subTest(ponto=ponto):
                real = abrir()
                class FalhaControlada:
                    fechada = False
                    def __getattr__(self, nome): return getattr(real, nome)
                    def execute(self, sql, *args):
                        cursor = real.execute(sql, *args)
                        if sql.startswith('INSERT INTO '+ponto) or (ponto == 'conclusao' and
                                sql.startswith('UPDATE operacoes_hibridas')):
                            raise sqlite3.OperationalError('injetada:'+ponto)
                        return cursor
                    def commit(self):
                        if ponto == 'commit': raise sqlite3.OperationalError('injetada:commit')
                        real.commit()
                    def close(self): self.fechada = True; real.close()
                proxy = FalhaControlada()
                with patch.object(banco, 'abrir_conexao', return_value=proxy):
                    with self.assertRaises(sf.FalhaPersistencia) as erro:
                        sf.registrar_operacao_imediata(**parametros())
                self.assertEqual(str(erro.exception.__cause__), 'injetada:'+ponto)
                self.assertTrue(proxy.fechada)
                self.assertEqual(self.foto(), antes)

    def test_guardas_reais_rejeitam_liquidacao_parcial_e_caixa_extra(self):
        abrir = banco.abrir_conexao
        antes = self.foto()
        for caso in ('parcial', 'extra'):
            with self.subTest(caso=caso):
                real = abrir()
                class EfeitoIncorreto:
                    def __getattr__(self, nome): return getattr(real, nome)
                    def execute(self, sql, *args):
                        if caso == 'parcial' and sql.startswith('INSERT INTO liquidacoes_eventos'):
                            valores = list(args[0]); valores[-1] -= 1
                            return real.execute(sql, valores)
                        cursor = real.execute(sql, *args)
                        if caso == 'extra' and sql.startswith('INSERT INTO lancamentos'):
                            real.execute('INSERT INTO lancamentos(data,descricao,tipo,categoria,categoria_id,'
                                'valor,valor_centavos,operacao_hibrida_id) SELECT data,descricao,tipo,categoria,'
                                'categoria_id,valor,valor_centavos,operacao_hibrida_id FROM lancamentos WHERE id=?',
                                (cursor.lastrowid,))
                        return cursor
                with patch.object(banco, 'abrir_conexao', return_value=EfeitoIncorreto()):
                    with self.assertRaises(sf.OperacaoIncompleta): sf.registrar_operacao_imediata(**parametros())
                self.assertEqual(self.foto(), antes)

    def test_perda_de_resposta_de_commit_nao_duplica(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self):
                real.commit(); raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.registrar_operacao_imediata(**parametros())
        antes = self.foto()
        r = sf.registrar_operacao_imediata(**parametros())
        self.assertEqual(sf.registrar_operacao_imediata(**parametros()), r)
        self.assertEqual(self.foto(), antes)

    def legado(self, nome, preparar):
        destino = self.f.caminho.with_name(nome+'.db')
        with closing(sqlite3.connect(self.v2)) as fonte, closing(sqlite3.connect(destino)) as c:
            fonte.backup(c)
            preparar(c)
            c.commit()
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            banco.aplicar_migracoes(destino)
        return destino

    def inserir_legado(self, c, id_evento, id_caixa, id_q):
        c.execute('INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,'
            'situacao_competencia,chave_origem) VALUES(?,?,?,?,?,?,?)',
            (id_evento, 'despesa', 'Legado', 1, 1, 'pendente', 'legado:'+str(id_evento)))
        c.execute("INSERT INTO lancamentos(id,data,descricao,tipo,categoria,categoria_id,valor) "
            "VALUES(?,'2026-01-01','Legado','despesa','Legado',1,1)", (id_caixa,))
        c.execute('INSERT INTO liquidacoes_eventos(id,evento_id,lancamento_id,valor_centavos) VALUES(?,?,?,1)',
                  (id_q, id_evento, id_caixa))

    def test_historicos_nao_positivos_em_tres_tabelas_preservados(self):
        for i, ids in enumerate(([-10], [-1], [0], [-10, -1, 0])):
            with self.subTest(ids=ids):
                def preparar(c):
                    c.execute('DELETE FROM lancamentos')
                    for ident in ids: self.inserir_legado(c, ident, ident, ident)
                destino = self.legado('nao_positivos_'+str(i), preparar)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    antes = self.foto()
                    r = sf.registrar_operacao_imediata(**parametros())
                    self.conferir_persistencia(parametros(), r, antes)
                    self.assertEqual(r.evento_ids, (1,))
                    self.assertEqual(r.liquidacao_ids, (1,))
                    # AUTOINCREMENT conserva a sequencia positiva da fixture original.
                    self.assertEqual(r.lancamento_ids, (3,))
                    with closing(banco.abrir_conexao()) as c:
                        for t in ('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'):
                            self.assertEqual(c.execute(f'SELECT * FROM {t} WHERE id<=0 ORDER BY id').fetchall(), antes[t])

    def test_autoincrement_preserva_sequencia_de_registro_legado_excluido(self):
        def preparar(c):
            c.execute("INSERT INTO lancamentos(id,data,descricao,tipo,categoria,categoria_id,valor) "
                "VALUES(500,'2026-01-01','Antigo','despesa','Legado',1,1)")
            c.execute('DELETE FROM lancamentos WHERE id=500')
        destino = self.legado('sequencia', preparar)
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            r = sf.registrar_operacao_imediata(**parametros())
            self.assertEqual(r.lancamento_ids, (501,))

    def test_esgotamento_de_ids_e_sequencia_rejeita_sem_efeitos(self):
        for caso in ('evento', 'caixa', 'liquidacao', 'sequencia'):
            with self.subTest(caso=caso):
                def preparar(c):
                    self.inserir_legado(c, sf.MAX_CENTAVOS if caso == 'evento' else 1,
                        sf.MAX_CENTAVOS if caso in ('caixa', 'sequencia') else 3,
                        sf.MAX_CENTAVOS if caso == 'liquidacao' else 1)
                    if caso == 'sequencia': c.execute('DELETE FROM lancamentos WHERE id=?', (sf.MAX_CENTAVOS,))
                destino = self.legado('esgotado_'+caso, preparar)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    antes = self.foto()
                    with self.assertRaises(sf.IdentificadoresEsgotados):
                        sf.registrar_operacao_imediata(**parametros())
                    self.assertEqual(self.foto(), antes)

    def test_ultimo_id_disponivel_nas_tres_tabelas_e_replay(self):
        def preparar(c): self.inserir_legado(c, sf.MAX_CENTAVOS-1, sf.MAX_CENTAVOS-1, sf.MAX_CENTAVOS-1)
        destino = self.legado('ultimo_id', preparar)
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            r = sf.registrar_operacao_imediata(**parametros())
            for ids in (r.evento_ids, r.lancamento_ids, r.liquidacao_ids):
                self.assertEqual(ids, (sf.MAX_CENTAVOS,))
            antes = self.foto()
            self.assertEqual(sf.registrar_operacao_imediata(**parametros()), r)
            with self.assertRaises(sf.IdentificadoresEsgotados):
                sf.registrar_operacao_imediata(**parametros(2))
            self.assertEqual(self.foto(), antes)

    def test_concorrencia_mesma_chave_com_disputa_sqlite_comprovada(self):
        pronta, ocupado, liberar, terminou = (threading.Event() for _ in range(4))
        resultados, erros = {}, {}
        abrir = banco.abrir_conexao
        def abrir_controlada():
            real = abrir(); real.execute('PRAGMA busy_timeout=1')
            if threading.current_thread().name != 'imediata-a': return real
            class CommitSuspenso:
                def __getattr__(self, nome): return getattr(real, nome)
                def commit(self):
                    pronta.set()
                    if not liberar.wait(10): raise AssertionError('nao liberou commit')
                    real.commit()
            return CommitSuspenso()
        def a():
            try: resultados['a'] = sf.registrar_operacao_imediata(**parametros())
            except BaseException as erro: erros['a'] = erro
            finally: terminou.set()
        def b():
            try:
                if not pronta.wait(10): raise AssertionError('A nao chegou no commit')
                try:
                    sf.registrar_operacao_imediata(**parametros())
                    raise AssertionError('B nao disputou lock')
                except sf.BancoOcupado as erro:
                    if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                    ocupado.set()
                if not terminou.wait(10): raise AssertionError('A nao terminou')
                resultados['b'] = sf.registrar_operacao_imediata(**parametros())
            except BaseException as erro: erros['b'] = erro
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
            ta, tb = threading.Thread(target=a, name='imediata-a'), threading.Thread(target=b, name='imediata-b')
            ta.start(); tb.start()
            try: self.assertTrue(ocupado.wait(10), 'Disputa SQLite nao comprovada')
            finally: liberar.set(); ta.join(15); tb.join(15)
            self.assertFalse(ta.is_alive() or tb.is_alive())
        self.assertFalse(erros)
        self.assertEqual(resultados['a'], resultados['b'])
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (1,))
            self.assertEqual(c.execute('SELECT count(*) FROM eventos_financeiros').fetchone(), (1,))
            self.assertEqual(c.execute('SELECT count(*) FROM liquidacoes_eventos').fetchone(), (1,))
            self.assertEqual(c.execute('SELECT count(*) FROM lancamentos WHERE operacao_hibrida_id IS NOT NULL').fetchone(), (1,))


if __name__ == '__main__':
    unittest.main()
