"""Reclassificacao publica: fixtures SQLite temporarias, sem app ou base real."""
from contextlib import closing
from datetime import date
import inspect
import os
import sqlite3
import threading
import unittest
from unittest.mock import patch

import banco
import servicos_financeiros as sf
import test_liquidar_evento as pagamentos


class TestReclassificarEvento(unittest.TestCase):
    def setUp(self):
        self.h = pagamentos.TestLiquidarEvento()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()
        self.f = self.h.f
        self.e = self.h.evento

    def p(self, numero=2, **mudancas):
        return dict(chave=pagamentos.chave(numero), evento_id=self.e,
            categoria_nova_id=2, motivo='Ajustar classificacao') | mudancas

    def foto(self):
        return self.h.foto()

    def corrente(self, evento=None):
        with closing(banco.abrir_conexao()) as c:
            return c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                (self.e if evento is None else evento,)).fetchone()[0]

    def pagar(self, numero=10, valor=400):
        return sf.liquidar_evento(**self.h.p(numero, valor_centavos=valor))

    def estornar(self, liquidacao, valor, numero=11):
        return sf.estornar_liquidacao(chave=pagamentos.chave(numero), liquidacao_id=liquidacao,
            valor_centavos=valor, natureza='devolucao_real', motivo='Devolvido',
            data_estorno=date(2026, 11, 2), confirmar_datas_divergentes=True)

    def conferir(self, p, r, antes, anterior=1):
        self.assertEqual((r.tipo_operacao, r.chave, r.evento_ids),
            ('reclassificar_evento', p['chave'], (p['evento_id'],)))
        self.assertEqual((r.lancamento_ids, r.liquidacao_ids, r.estorno_ids, r.reversao_ids),
            ((), (), (), ()))
        self.assertEqual(len(r.reclassificacao_ids), 1)
        self.assertGreater(r.reclassificacao_ids[0], 0)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT evento_id,operacao_hibrida_id,categoria_anterior_id,categoria_nova_id,motivo '
                'FROM reclassificacoes_eventos WHERE id=?', r.reclassificacao_ids).fetchone(),
                (p['evento_id'], r.operacao_id, anterior, p['categoria_nova_id'], sf.normalizar_texto(p['motivo'])))
            self.assertEqual(c.execute('SELECT tipo,estado FROM operacoes_hibridas WHERE id=?',
                (r.operacao_id,)).fetchone(), ('reclassificar_evento', 'concluida'))
            self.assertEqual(c.execute("SELECT seq FROM sqlite_sequence WHERE name='reclassificacoes_eventos'").fetchone(),
                r.reclassificacao_ids)
        self.assertEqual(self.corrente(p['evento_id']), p['categoria_nova_id'])
        depois = self.foto()
        for tabela, dados in antes.items():
            if tabela in ('operacoes_hibridas', 'reclassificacoes_eventos'):
                self.assertEqual(len(depois[tabela]), len(dados)+1, tabela)
                self.assertTrue(all(linha in depois[tabela] for linha in dados), tabela)
            elif tabela != 'sqlite_sequence':
                self.assertEqual(depois[tabela], dados, tabela)

    def test_assinatura_exata_e_seis_servicos(self):
        sig = inspect.signature(sf.reclassificar_evento)
        self.assertEqual(tuple(sig.parameters), ('chave', 'evento_id', 'categoria_nova_id', 'motivo',
            'categoria_anterior_esperada_id'))
        self.assertIs(sig.return_annotation, sf.ResultadoOperacao)
        for nome, parametro in sig.parameters.items():
            self.assertIs(parametro.kind, inspect.Parameter.KEYWORD_ONLY)
            if nome == 'categoria_anterior_esperada_id': self.assertIsNone(parametro.default)
            else: self.assertIs(parametro.default, inspect.Parameter.empty)
        for nome in ('registrar_evento_manual', 'registrar_operacao_imediata', 'liquidar_evento',
                     'estornar_liquidacao', 'reverter_evento', 'reclassificar_evento'):
            self.assertTrue(callable(getattr(sf, nome)))

    def test_nao_liquidado_sem_update_do_evento_original(self):
        antes = self.foto()
        self.conferir(self.p(), sf.reclassificar_evento(**self.p()), antes)

    def test_receita_e_categoria_com_id_maximo_int64(self):
        with self.f.conectar() as c:
            anterior = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
            c.execute("INSERT INTO categorias(id,nome,tipo) VALUES(?,'Receita reclassificada','receita')",
                (sf.MAX_CENTAVOS,))
        e = self.h.criar_evento(10, tipo='receita', categoria=anterior).evento_ids[0]
        p = self.p(evento_id=e, categoria_nova_id=sf.MAX_CENTAVOS, categoria_anterior_esperada_id=anterior)
        antes = self.foto()
        self.conferir(p, sf.reclassificar_evento(**p), antes, anterior=anterior)

    def test_parcial_integral_e_estornos_nao_impedem_reclassificacao(self):
        for caso in ('parcial', 'integral', 'estorno_parcial', 'estorno_integral'):
            destino = self.f.clone(caso)
            with self.subTest(caso=caso), patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                pago = self.pagar(valor=400 if caso == 'parcial' else 1000)
                if caso.startswith('estorno_'):
                    self.estornar(pago.liquidacao_ids[0], 400 if caso == 'estorno_parcial' else 1000)
                antes = self.foto()
                self.conferir(self.p(), sf.reclassificar_evento(**self.p()), antes)

    def test_evento_inexistente_ou_revertido(self):
        antes = self.foto()
        with self.assertRaises(sf.EventoInexistente): sf.reclassificar_evento(**self.p(evento_id=999))
        self.assertEqual(self.foto(), antes)
        sf.reverter_evento(chave=pagamentos.chave(10), evento_id=self.e,
            data_reversao=date(2026, 11, 1), motivo='Cancelado')
        antes = self.foto()
        with self.assertRaises(sf.EventoRevertido): sf.reclassificar_evento(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_historico_legado_sem_origem_manual_nao_e_adotado(self):
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
            with self.assertRaises(sf.EventoNaoElegivel): sf.reclassificar_evento(**self.p(evento_id=77))
            self.assertEqual(self.foto(), antes)

    def test_evento_inelegivel_ou_vinculos_inconsistentes(self):
        casos = [('situacao_competencia', 'estimada', sf.EventoNaoElegivel),
                 ('tipo', 'outro', sf.EventoNaoElegivel), ('valor_centavos', 0, sf.EventoNaoElegivel),
                 ('operacao_hibrida_id', 999, sf.OperacaoIncompleta),
                 ('compra_cartao_id', 999, sf.OperacaoIncompleta)]
        for campo, valor, erro in casos:
            destino = self.f.clone(campo)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('eventos_financeiros',), lambda c:
                    c.execute(f'UPDATE eventos_financeiros SET {campo}=? WHERE id=?', (valor, self.e)))
                antes = self.foto()
                with self.assertRaises(erro): sf.reclassificar_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_categoria_nova_inexistente_ou_incompativel(self):
        with closing(banco.abrir_conexao()) as c:
            receita = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
        for categoria, erro in ((999, sf.CategoriaInexistente), (receita, sf.CategoriaIncompativel)):
            antes = self.foto()
            with self.assertRaises(erro): sf.reclassificar_evento(**self.p(categoria_nova_id=categoria))
            self.assertEqual(self.foto(), antes)

    def test_categoria_anterior_inexistente_ou_incompativel(self):
        for caso, erro in (('ausente', sf.CategoriaInexistente), ('tipo', sf.CategoriaIncompativel)):
            destino = self.f.clone(caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('categorias',), lambda c: c.execute(
                    'DELETE FROM categorias WHERE id=1' if caso == 'ausente' else
                    "UPDATE categorias SET tipo='receita' WHERE id=1"))
                antes = self.foto()
                # Categoria anterior e validada antes da nova inexistente.
                with self.assertRaises(erro): sf.reclassificar_evento(**self.p(categoria_nova_id=999))
                self.assertEqual(self.foto(), antes)

    def test_categorias_legadas_nao_positivas_validas(self):
        for numero, categoria in ((20, -2**63), (21, 0)):
            with self.f.conectar() as c:
                c.execute("INSERT INTO categorias(id,nome,tipo) VALUES(?,?,'despesa')",
                    (categoria, 'Categoria legada '+str(categoria)))
            p = self.p(numero, categoria_nova_id=categoria, categoria_anterior_esperada_id=1)
            antes = self.foto()
            self.conferir(p, sf.reclassificar_evento(**p), antes)
            p_volta = self.p(numero+10, categoria_nova_id=1, categoria_anterior_esperada_id=categoria)
            antes = self.foto()
            self.conferir(p_volta, sf.reclassificar_evento(**p_volta), antes, anterior=categoria)

    def test_sem_alteracao_nao_cria_operacao_ou_historico(self):
        antes = self.foto()
        with self.assertRaises(sf.ReclassificacaoSemAlteracao):
            sf.reclassificar_evento(**self.p(categoria_nova_id=1))
        self.assertEqual(self.foto(), antes)
        # A chave nao foi consumida pela rejeicao e pode representar a intencao corrigida.
        self.conferir(self.p(), sf.reclassificar_evento(**self.p()), antes)

    def test_expectativa_correta_divergente_e_precedencia(self):
        antes = self.foto()
        for mudanca, erro in (
            (dict(categoria_anterior_esperada_id=999), sf.ConflitoEstado),
            (dict(categoria_nova_id=1, categoria_anterior_esperada_id=999), sf.ConflitoEstado),
            (dict(categoria_nova_id=999, categoria_anterior_esperada_id=999), sf.CategoriaInexistente),
            (dict(categoria_nova_id=1, categoria_anterior_esperada_id=1), sf.ReclassificacaoSemAlteracao)):
            with self.assertRaises(erro): sf.reclassificar_evento(**self.p(**mudanca))
            self.assertEqual(self.foto(), antes)
        p = self.p(categoria_anterior_esperada_id=1)
        self.conferir(p, sf.reclassificar_evento(**p), antes)

    def test_sequencia_a_b_a_e_view_corrente_sem_mudar_evento(self):
        a = self.p(categoria_anterior_esperada_id=1)
        antes = self.foto()
        r_a = sf.reclassificar_evento(**a)
        self.conferir(a, r_a, antes)
        b = self.p(3, categoria_nova_id=1, categoria_anterior_esperada_id=2)
        antes = self.foto()
        r_b = sf.reclassificar_evento(**b)
        self.conferir(b, r_b, antes, anterior=2)
        self.assertGreater(r_b.reclassificacao_ids[0], r_a.reclassificacao_ids[0])
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_id FROM eventos_financeiros WHERE id=?',
                (self.e,)).fetchone(), (1,))

    def test_caixas_anteriores_preservados_liquidacao_futura_nova_categoria(self):
        original = self.pagar(valor=300)
        self.estornar(original.liquidacao_ids[0], 100)
        antes = self.foto()
        self.conferir(self.p(), sf.reclassificar_evento(**self.p()), antes)
        # O teste de reclassificacao compara todas as tabelas, inclusive caixa e estorno.
        p = self.h.p(12, valor_centavos=400)
        antes = self.foto()
        novo = sf.liquidar_evento(**p)
        self.h.conferir(p, novo, antes, categoria=2)
        self.assertNotEqual(novo.lancamento_ids, original.lancamento_ids)

    def test_estorno_futuro_copia_classificacao_original_apos_reclassificar(self):
        original = self.pagar(valor=500)
        sf.reclassificar_evento(**self.p())
        with self.f.conectar() as c:
            c.execute("UPDATE categorias SET nome='Nome posterior' WHERE id=1")
        antes = self.foto()
        estorno = self.estornar(original.liquidacao_ids[0], 200)
        with closing(banco.abrir_conexao()) as c:
            anterior = c.execute('SELECT tipo,categoria_id,categoria FROM lancamentos WHERE id=?',
                original.lancamento_ids).fetchone()
            self.assertEqual(c.execute('SELECT tipo,categoria_id,categoria FROM lancamentos WHERE id=?',
                estorno.lancamento_ids).fetchone(), anterior)
            self.assertEqual(anterior[1], 1)
        depois = self.foto()
        self.assertEqual(depois['eventos_financeiros'], antes['eventos_financeiros'])
        self.assertEqual(depois['reclassificacoes_eventos'], antes['reclassificacoes_eventos'])
        self.assertEqual(self.corrente(), 2)

    def test_validadores_estaticos_nao_abrem_conexao(self):
        casos = [dict(evento_id=v) for v in (0, -1, True, 1.0, '1', 2**63)]
        for campo in ('categoria_nova_id', 'categoria_anterior_esperada_id'):
            casos += [{campo: v} for v in (True, 1.0, '1', 2**63, -2**63-1)]
        casos += [dict(motivo=v) for v in ('', '  ', None, 'x\x00y', '\ud800')]
        casos += [dict(chave='invalida')]
        antes = self.foto()
        for caso in casos:
            with self.subTest(caso=caso), patch.object(banco, 'abrir_conexao', side_effect=AssertionError('abriu')):
                with self.assertRaises(sf.ParametroInvalido): sf.reclassificar_evento(**self.p(**caso))
        self.assertEqual(self.foto(), antes)

    def test_replay_normalizado_opcional_null_e_conflito_payload(self):
        p = self.p(motivo='  Cafe\u0301  grupo  ')
        antes = self.foto()
        r = sf.reclassificar_evento(**p)
        self.conferir(p, r, antes)
        antes = self.foto()
        self.assertEqual(sf.reclassificar_evento(**(p | {'motivo': 'Café  grupo',
            'categoria_anterior_esperada_id': None})), r)
        self.assertEqual(self.foto(), antes)
        for mudanca in (dict(motivo='Outro'), dict(evento_id=999), dict(categoria_nova_id=1),
                        dict(categoria_anterior_esperada_id=1)):
            with self.assertRaises(sf.ConflitoIdempotencia): sf.reclassificar_evento(**(p | mudanca))
            self.assertEqual(self.foto(), antes)

    def test_replay_apos_reclassificacao_posterior_e_reversao(self):
        p = self.p(categoria_anterior_esperada_id=1)
        r = sf.reclassificar_evento(**p)
        sf.reclassificar_evento(**self.p(3, categoria_nova_id=1, categoria_anterior_esperada_id=2))
        sf.reverter_evento(chave=pagamentos.chave(4), evento_id=self.e,
            data_reversao=date(2026, 11, 1), motivo='Cancelado')
        antes = self.foto()
        self.assertEqual(sf.reclassificar_evento(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_tipo_conflitante_e_operacao_aberta(self):
        antes = self.foto()
        # Chave 1 pertence ao cadastro manual; conflito precede categoria dinamica.
        with self.assertRaises(sf.ConflitoIdempotencia): sf.reclassificar_evento(**self.p(1, categoria_nova_id=999))
        self.assertEqual(self.foto(), antes)
        req = sf.canonicalizar_requisicao('reclassificar_evento', **self.p())
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.reclassificar_evento(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_valor_int64_do_evento_nao_e_convertido(self):
        for numero, valor in ((10, 1), (11, sf.MAX_CENTAVOS)):
            e = self.h.criar_evento(numero, valor=valor).evento_ids[0]
            p = self.p(numero+10, evento_id=e)
            antes = self.foto()
            self.conferir(p, sf.reclassificar_evento(**p), antes)

    def historico_excluido_fixture(self, id_historico):
        outro = self.h.criar_evento(10).evento_ids[0]
        with self.f.conectar() as c:
            id_real = self.f.reclassificar(c, outro, 2, id=id_historico)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id="
                '(SELECT operacao_hibrida_id FROM reclassificacoes_eventos WHERE id=?)', (id_real,))
        # Exclusao e proibida normalmente. Simular historico removido sob fixture
        # permite demonstrar que o servico respeita o high-water mark persistente.
        self.h.corromper_fixture(('reclassificacoes_eventos',), lambda c:
            c.execute('DELETE FROM reclassificacoes_eventos WHERE id=?', (id_historico,)))

    def test_autoincrement_preserva_sequencia_acima_do_max_id(self):
        self.historico_excluido_fixture(500)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT MAX(id) FROM reclassificacoes_eventos').fetchone(), (None,))
            self.assertEqual(c.execute("SELECT seq FROM sqlite_sequence WHERE name='reclassificacoes_eventos'").fetchone(), (500,))
        antes = self.foto()
        r = sf.reclassificar_evento(**self.p())
        self.assertEqual(r.reclassificacao_ids, (501,))
        self.conferir(self.p(), r, antes)

    def test_ultimo_id_da_sequencia_e_esgotamento_mesmo_sem_linha_maxima(self):
        self.historico_excluido_fixture(sf.MAX_CENTAVOS-1)
        antes = self.foto()
        r = sf.reclassificar_evento(**self.p())
        self.assertEqual(r.reclassificacao_ids, (sf.MAX_CENTAVOS,))
        self.conferir(self.p(), r, antes)
        self.assertEqual(sf.reclassificar_evento(**self.p()), r)
        # Mantem sequencia M e remove a linha apenas nesta fixture adversarial.
        self.h.corromper_fixture(('reclassificacoes_eventos',), lambda c:
            c.execute('DELETE FROM reclassificacoes_eventos WHERE id=?', r.reclassificacao_ids))
        antes = self.foto()
        with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('gravou')):
            with self.assertRaises(sf.IdentificadoresEsgotados): sf.reclassificar_evento(**self.p(3))
        self.assertEqual(self.foto(), antes)

    def test_ids_nao_positivos_nao_forcam_id_explicito_na_tabela_autoincrement(self):
        for id_antigo in (-10, 0):
            destino = self.f.clone('id_'+str(id_antigo))
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(('reclassificacoes_eventos',), lambda c:
                    c.execute('INSERT INTO reclassificacoes_eventos(id,evento_id,operacao_hibrida_id,'
                        'categoria_anterior_id,categoria_nova_id,motivo) VALUES(?,999,999,1,2,?)',
                        (id_antigo, 'Historico sintetico')))
                antes = self.foto()
                r = sf.reclassificar_evento(**self.p())
                self.assertEqual(r.reclassificacao_ids, (1,))
                self.conferir(self.p(), r, antes)

    def test_rollback_apos_inserts_conclusao_e_falha_commit_fecha_conexao(self):
        abrir = banco.abrir_conexao
        antes = self.foto()
        for ponto in ('operacoes_hibridas', 'reclassificacoes_eventos', 'conclusao', 'commit'):
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
                with self.assertRaises(sf.FalhaPersistencia) as erro: sf.reclassificar_evento(**self.p())
            self.assertEqual(str(erro.exception.__cause__), 'injetada:'+ponto)
            self.assertTrue(proxy.fechada)
            self.assertEqual(self.foto(), antes)

    def test_resposta_perdida_apos_commit_e_recuperavel(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self): real.commit(); raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.reclassificar_evento(**self.p())
        antes = self.foto()
        r = sf.reclassificar_evento(**self.p())
        self.assertEqual(sf.reclassificar_evento(**self.p()), r)
        self.assertEqual(self.foto(), antes)

    def test_completude_rejeita_ausente_duplicada_e_dados_divergentes(self):
        abrir = banco.abrir_conexao
        outro = self.h.criar_evento(10).evento_ids[0]
        for caso in ('ausente', 'duplicada', 'motivo', 'alvo', 'extra'):
            real = abrir()
            antes = self.foto()
            self_outer = self
            class Incompleta:
                def __getattr__(self, nome): return getattr(real, nome)
                def execute(self, sql, *args):
                    if sql.startswith('INSERT INTO reclassificacoes_eventos'):
                        valores = list(args[0])
                        if caso == 'motivo': valores[4] = 'Outro motivo'
                        if caso == 'alvo': valores[0] = outro
                        if caso == 'ausente': real.execute('SAVEPOINT fixture')
                        cur = real.execute(sql, valores)
                        if caso == 'ausente':
                            real.execute('ROLLBACK TO fixture'); real.execute('RELEASE fixture')
                        elif caso == 'duplicada':
                            real.execute('INSERT INTO reclassificacoes_eventos(evento_id,operacao_hibrida_id,'
                                "categoria_anterior_id,categoria_nova_id,motivo) VALUES(?,?,1,2,'Extra')", (outro, valores[1]))
                        elif caso == 'extra': self_outer.f.evento(real)
                        return cur
                    return real.execute(sql, *args)
            with self.subTest(caso=caso), patch.object(banco, 'abrir_conexao', return_value=Incompleta()):
                with self.assertRaises(sf.OperacaoIncompleta): sf.reclassificar_evento(**self.p())
            self.assertEqual(self.foto(), antes)

    def test_replay_recusa_historico_ausente_adulterado_ou_efeito_extra(self):
        p = self.p()
        r = sf.reclassificar_evento(**p)
        for caso in ('ausente', 'anterior', 'nova', 'motivo', 'evento', 'extra'):
            destino = self.f.clone('replay_'+caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                if caso == 'extra':
                    self.h.corromper_fixture(('lancamentos',), lambda c:
                        self.f.caixa(c, r.operacao_id, centavos=-1))
                else:
                    sql = {'ausente': 'DELETE FROM reclassificacoes_eventos WHERE id=?',
                           'anterior': 'UPDATE reclassificacoes_eventos SET categoria_anterior_id=2 WHERE id=?',
                           'nova': 'UPDATE reclassificacoes_eventos SET categoria_nova_id=1 WHERE id=?',
                           'motivo': "UPDATE reclassificacoes_eventos SET motivo='Adulterado' WHERE id=?",
                           'evento': 'UPDATE reclassificacoes_eventos SET evento_id=999 WHERE id=?'}[caso]
                    self.h.corromper_fixture(('reclassificacoes_eventos',), lambda c:
                        c.execute(sql, r.reclassificacao_ids))
                antes = self.foto()
                with self.assertRaises(sf.OperacaoIncompleta): sf.reclassificar_evento(**p)
                self.assertEqual(self.foto(), antes)

    def test_ordem_sql_autoincrement_nativo_commit_e_fechamento(self):
        real = banco.abrir_conexao()
        sqls, confirmado = [], []
        real.set_trace_callback(sqls.append)
        class Observada:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self): real.commit(); confirmado.append(True)
        with patch.object(banco, 'abrir_conexao', return_value=Observada()):
            r = sf.reclassificar_evento(**self.p())
        self.assertEqual(confirmado, [True])
        inicio = sqls.index('BEGIN IMMEDIATE')
        dinamicas = [i for i, sql in enumerate(sqls) if sql.startswith('SELECT categoria_atual_id')
            or sql.startswith('SELECT tipo FROM categorias') or sql.startswith('INSERT INTO reclassificacoes_eventos')]
        self.assertTrue(dinamicas)
        self.assertTrue(all(i > inicio for i in dinamicas))
        inserts = [sql for sql in sqls if sql.startswith('INSERT INTO reclassificacoes_eventos')]
        self.assertTrue(all('(evento_id,operacao_hibrida_id,' in sql for sql in inserts))
        self.assertFalse(any(sql.startswith('UPDATE eventos_financeiros') for sql in sqls))
        self.assertGreater(r.reclassificacao_ids[0], 0)
        with self.assertRaises(sqlite3.ProgrammingError): real.execute('SELECT 1')

    def disputar(self, p_a, p_b, segundo_pagamento=False):
        pronta, liberar, terminou, ocupado = (threading.Event() for _ in range(4))
        resultados, erros = {}, {}
        abrir = banco.abrir_conexao
        def abrir_controlada():
            real = abrir(); real.execute('PRAGMA busy_timeout=1')
            if threading.current_thread().name != 'classe-a': return real
            class Suspensa:
                def __getattr__(self, nome): return getattr(real, nome)
                def commit(self):
                    pronta.set()
                    if not liberar.wait(10): raise AssertionError('nao liberou')
                    real.commit()
            return Suspensa()
        def a():
            try: resultados['a'] = sf.reclassificar_evento(**p_a)
            except BaseException as erro: erros['a'] = erro
            finally: terminou.set()
        def b():
            servico = sf.liquidar_evento if segundo_pagamento else sf.reclassificar_evento
            try:
                if not pronta.wait(10): raise AssertionError('A nao chegou ao commit')
                try:
                    servico(**p_b)
                    raise AssertionError('Nao disputou lock')
                except sf.BancoOcupado as erro:
                    if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                    ocupado.set()
                if not terminou.wait(10): raise AssertionError('A nao terminou')
                resultados['b'] = servico(**p_b)
            except BaseException as erro: erros['b'] = erro
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
            ta, tb = threading.Thread(target=a, name='classe-a'), threading.Thread(target=b, name='classe-b')
            ta.start(); tb.start()
            try: self.assertTrue(ocupado.wait(10), 'Sem disputa SQLite comprovada')
            finally: liberar.set(); ta.join(15); tb.join(15)
            self.assertFalse(ta.is_alive() or tb.is_alive())
        self.assertNotIn('a', erros)
        return resultados, erros

    def test_concorrencia_real_mesma_chave_e_expectativa_divergente(self):
        for mesmo in (True, False):
            destino = self.f.clone('concorrente_'+str(mesmo))
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                p_a = self.p(categoria_anterior_esperada_id=1)
                p_b = self.p(2 if mesmo else 3, categoria_anterior_esperada_id=1)
                resultados, erros = self.disputar(p_a, p_b)
                if mesmo:
                    self.assertFalse(erros)
                    self.assertEqual(resultados['a'], resultados['b'])
                else: self.assertIsInstance(erros.get('b'), sf.ConflitoEstado)
                with closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT categoria_anterior_id,categoria_nova_id FROM reclassificacoes_eventos').fetchall(), [(1, 2)])
                    self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (2,))

    def test_concorrencia_real_reclassificacao_e_liquidacao(self):
        antes = self.foto()
        resultados, erros = self.disputar(self.p(), self.h.p(10), segundo_pagamento=True)
        self.assertFalse(erros)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_id FROM lancamentos WHERE id=?',
                resultados['b'].lancamento_ids).fetchone(), (2,))
            self.assertEqual(c.execute('SELECT categoria_id FROM eventos_financeiros WHERE id=?', (self.e,)).fetchone(), (1,))
        depois = self.foto()
        self.assertEqual(depois['eventos_financeiros'], antes['eventos_financeiros'])
        self.assertEqual(len(depois['reclassificacoes_eventos']), 1)
        self.assertEqual(len(depois['liquidacoes_eventos']), 1)
        self.assertEqual(len(depois['lancamentos']), len(antes['lancamentos'])+1)


if __name__ == '__main__':
    unittest.main()
