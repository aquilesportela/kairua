"""Liquidacao publica: SQLite temporario e fixtures SQL, sem app/servico de estorno."""
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


def chave(numero):
    return 'kairua:v1:'+str(UUID(int=numero))


class TestLiquidarEvento(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.v2 = self.f.clone('legado_v2')
        self.f.migrar()
        self.evento = self.criar_evento().evento_ids[0]

    def criar_evento(self, numero=1, valor=1000, tipo='despesa', categoria=1):
        return sf.registrar_evento_manual(chave=chave(numero), tipo=tipo,
            descricao='Descricao original', categoria_id=categoria, valor_centavos=valor,
            data_competencia=date(2026, 11, 1), data_vencimento=date(2026, 12, 15),
            confirmar_ocorrencia=True)

    def p(self, numero=2, **mudancas):
        return dict(chave=chave(numero), evento_id=self.evento, valor_centavos=400,
            data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False) | mudancas

    def foto(self):
        with closing(banco.abrir_conexao()) as c:
            return {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def conferir(self, p, r, antes, categoria=1, descricao='Descricao original'):
        self.assertEqual(r.tipo_operacao, 'liquidar_evento')
        self.assertEqual(r.evento_ids, (p['evento_id'],))
        self.assertEqual(len(r.lancamento_ids), 1)
        self.assertEqual(len(r.liquidacao_ids), 1)
        self.assertGreater(r.lancamento_ids[0], 0)
        self.assertGreater(r.liquidacao_ids[0], 0)
        self.assertEqual((r.estorno_ids, r.reversao_ids, r.reclassificacao_ids), ((), (), ()))
        with closing(banco.abrir_conexao()) as c:
            tipo = c.execute('SELECT tipo FROM eventos_financeiros WHERE id=?', (p['evento_id'],)).fetchone()[0]
            nome = c.execute('SELECT nome FROM categorias WHERE id=?', (categoria,)).fetchone()[0]
            self.assertEqual(c.execute('SELECT descricao,tipo,categoria_id,categoria,valor_centavos,'
                'typeof(valor_centavos),valor=CAST(valor_centavos AS REAL)/100.0,data,operacao_hibrida_id '
                'FROM lancamentos WHERE id=?', r.lancamento_ids).fetchone(),
                (descricao, tipo, categoria, nome, p['valor_centavos'], 'integer', 1,
                 p['data_liquidacao'].isoformat(), r.operacao_id))
            self.assertEqual(c.execute('SELECT evento_id,lancamento_id,valor_centavos FROM liquidacoes_eventos '
                'WHERE id=?', r.liquidacao_ids).fetchone(), (p['evento_id'], r.lancamento_ids[0], p['valor_centavos']))
            self.assertEqual(c.execute('SELECT estado FROM operacoes_hibridas WHERE id=?',
                (r.operacao_id,)).fetchone(), ('concluida',))
        depois = self.foto()
        for t, dados in antes.items():
            if t in ('operacoes_hibridas', 'lancamentos', 'liquidacoes_eventos'):
                self.assertEqual(len(depois[t]), len(dados)+1, t)
                self.assertTrue(all(linha in depois[t] for linha in dados), t)
            elif t != 'sqlite_sequence':
                self.assertEqual(depois[t], dados, t)

    def estornar_fixture(self, liquidacao, valor, natureza='devolucao_real'):
        with self.f.conectar() as c:
            s = self.f.estornar(c, liquidacao, valor, natureza=natureza,
                                data='2026-11-02' if natureza == 'devolucao_real' else '2026-11-01')
            op = c.execute('SELECT l.operacao_hibrida_id FROM estornos_liquidacoes s '
                'JOIN lancamentos l ON l.id=s.lancamento_estorno_id WHERE s.id=?', (s,)).fetchone()[0]
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))
        return s

    def reclassificar_fixture(self, categoria):
        with self.f.conectar() as c:
            r = self.f.reclassificar(c, self.evento, categoria)
            op = c.execute('SELECT operacao_hibrida_id FROM reclassificacoes_eventos WHERE id=?', (r,)).fetchone()[0]
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))

    def corromper_fixture(self, tabelas, mutacao):
        """Dano controlado em temp; restaura DDL/PRAGMAs antes de testar o servico.

        Permite provar recusa de dados, nao apenas do manifesto de esquema.
        As fixtures de estorno validas acima mantem todos os gatilhos ativos.
        """
        with closing(banco.abrir_conexao()) as c:
            gatilhos = c.execute('SELECT name,sql FROM sqlite_master WHERE type=\'trigger\'').fetchall()
            selecionados = [(nome, sql) for nome, sql in gatilhos
                            if c.execute('SELECT tbl_name FROM sqlite_master WHERE name=?', (nome,)).fetchone()[0] in tabelas]
            for nome, _ in selecionados: c.execute(f'DROP TRIGGER "{nome}"')
            c.execute('PRAGMA ignore_check_constraints=ON')
            mutacao(c)
            c.execute('PRAGMA ignore_check_constraints=OFF')
            for _, sql in selecionados: c.execute(sql)
            c.commit()

    def test_assinatura_e_seis_servicos_autorizados(self):
        sig = inspect.signature(sf.liquidar_evento)
        self.assertEqual(set(sig.parameters), set(self.p()) | {'descricao_caixa'})
        self.assertIsNone(sig.parameters['descricao_caixa'].default)
        for nome, p in sig.parameters.items():
            self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY)
            if nome != 'descricao_caixa': self.assertIs(p.default, inspect.Parameter.empty)
        self.assertTrue(callable(sf.estornar_liquidacao))
        self.assertTrue(callable(sf.reverter_evento))
        self.assertTrue(callable(sf.reclassificar_evento))

    def test_parcial_integral_e_duas_chamadas_sem_nova_competencia(self):
        antes = self.foto()
        p = self.p(valor_centavos=300)
        r = sf.liquidar_evento(**p)
        self.conferir(p, r, antes)
        p2 = self.p(3, valor_centavos=700)
        antes2 = self.foto()
        r2 = sf.liquidar_evento(**p2)
        self.conferir(p2, r2, antes2)
        self.assertNotEqual(r.lancamento_ids, r2.lancamento_ids)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT SUM(valor_liquido) FROM _hibrido_liquidacoes WHERE evento_id=?',
                (self.evento,)).fetchone(), (1000,))
        antes3 = self.foto()
        with self.assertRaises(sf.SaldoInsuficiente): sf.liquidar_evento(**self.p(4, valor_centavos=1))
        self.assertEqual(self.foto(), antes3)

    def test_receita_integral_preserva_tipo_e_sem_evento_novo(self):
        with closing(banco.abrir_conexao()) as c:
            cat = c.execute("SELECT id FROM categorias WHERE tipo='receita' LIMIT 1").fetchone()[0]
        e = self.criar_evento(10, tipo='receita', categoria=cat).evento_ids[0]
        p = self.p(evento_id=e, valor_centavos=1000)
        antes = self.foto()
        self.conferir(p, sf.liquidar_evento(**p), antes, categoria=cat)

    def test_excesso_de_saldo_nao_cria_operacao_ou_caixa(self):
        sf.liquidar_evento(**self.p(valor_centavos=900))
        antes = self.foto()
        with self.assertRaises(sf.SaldoInsuficiente): sf.liquidar_evento(**self.p(3, valor_centavos=101))
        self.assertEqual(self.foto(), antes)

    def test_tipo_valor_id_data_descricao_e_confirmacao_invalidos_antes_da_conexao(self):
        casos = [dict(evento_id=v) for v in (True, False, 0, -1, 2**63, '1', 1.0)]
        casos += [dict(valor_centavos=v) for v in (0, -1, True, False, 2**63, 1.5, '10', Decimal(1))]
        casos += [dict(data_liquidacao='2026-11-01'), dict(data_liquidacao=datetime(2026, 1, 1)),
            dict(confirmar_datas_divergentes=1), dict(confirmar_datas_divergentes=None),
            dict(descricao_caixa='  '), dict(chave='invalida')]
        antes = self.foto()
        for mudanca in casos:
            with self.subTest(mudanca=mudanca), patch.object(banco, 'abrir_conexao',
                    side_effect=AssertionError('abriu com entrada invalida')):
                with self.assertRaises(sf.ParametroInvalido): sf.liquidar_evento(**self.p(**mudanca))
        self.assertEqual(self.foto(), antes)

    def test_data_divergente_confirmada_e_datas_futuras_retroativas(self):
        antes = self.foto()
        with self.assertRaises(sf.ConfirmacaoNecessaria):
            sf.liquidar_evento(**self.p(data_liquidacao=date(2030, 1, 1)))
        self.assertEqual(self.foto(), antes)
        for i, data_caixa in enumerate((date.min, date.max), start=2):
            p = self.p(i, data_liquidacao=data_caixa, confirmar_datas_divergentes=True)
            antes = self.foto()
            self.conferir(p, sf.liquidar_evento(**p), antes)

    def test_descricao_opcional_copia_original_e_informada_e_normalizada(self):
        p = self.p(descricao_caixa='  Cafe\u0301  liquidado  ')
        antes = self.foto()
        self.conferir(p, sf.liquidar_evento(**p), antes, descricao='Café  liquidado')
        antes = self.foto()
        p2 = self.p(3, descricao_caixa=None)
        self.conferir(p2, sf.liquidar_evento(**p2), antes)

    def test_categoria_corrente_e_nome_capturados_sem_alterar_historico(self):
        r1 = sf.liquidar_evento(**self.p(valor_centavos=100))
        self.reclassificar_fixture(2)
        p = self.p(3)
        antes = self.foto()
        self.conferir(p, sf.liquidar_evento(**p), antes, categoria=2)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT categoria_id FROM eventos_financeiros WHERE id=?', (self.evento,)).fetchone(), (1,))
            self.assertEqual(c.execute('SELECT categoria_id FROM lancamentos WHERE id=?', r1.lancamento_ids).fetchone(), (1,))

    def test_evento_inexistente_inelegivel_e_revertido(self):
        antes = self.foto()
        with self.assertRaises(sf.EventoInexistente): sf.liquidar_evento(**self.p(evento_id=999))
        self.assertEqual(self.foto(), antes)
        with self.f.conectar() as c:
            self.f.reverter(c, self.evento)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        with self.assertRaises(sf.EventoRevertido): sf.liquidar_evento(**self.p())
        self.assertEqual(self.foto(), antes)

    def test_eventos_legados_nao_sao_adotados_automaticamente(self):
        for estado, data_competencia in (('pendente', None), ('estimada', '2026-11-01'), ('confirmada', '2026-11-01')):
            destino = self.f.caminho.with_name('historico_'+estado+'.db')
            with closing(sqlite3.connect(self.v2)) as fonte, closing(sqlite3.connect(destino)) as c:
                fonte.backup(c)
                c.execute('INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,'
                    'situacao_competencia,data_competencia,chave_origem) VALUES(77,?,?,?,?,?,?,?)',
                    ('despesa', 'Antigo', 1, 1000, estado, data_competencia, 'historico'))
                c.commit()
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                banco.aplicar_migracoes(destino)
                antes = self.foto()
                with self.assertRaises(sf.EventoNaoElegivel): sf.liquidar_evento(**self.p(evento_id=77))
                self.assertEqual(self.foto(), antes)

    def test_categoria_corrente_ausente_ou_incompativel_falha_sem_escrever(self):
        for caso in ('ausente', 'incompativel'):
            destino = self.f.clone(caso)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                if caso == 'ausente':
                    self.corromper_fixture(('categorias',), lambda c: c.execute('DELETE FROM categorias WHERE id=1'))
                    erro = sf.CategoriaInexistente
                else:
                    self.corromper_fixture(('categorias',), lambda c: c.execute("UPDATE categorias SET tipo='receita' WHERE id=1"))
                    erro = sf.CategoriaIncompativel
                antes = self.foto()
                with self.assertRaises(erro): sf.liquidar_evento(**self.p())
                self.assertEqual(self.foto(), antes)

    def test_replay_payload_conflitante_e_nova_chave_mesma_quantia(self):
        p = self.p()
        r = sf.liquidar_evento(**p)
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('replay validou saldo')):
            self.assertEqual(sf.liquidar_evento(**(p | {'descricao_caixa': None})), r)
        self.assertEqual(self.foto(), antes)
        for mudanca in (dict(valor_centavos=401), dict(descricao_caixa='Outra'), dict(evento_id=999)):
            with self.subTest(mudanca=mudanca), self.assertRaises(sf.ConflitoIdempotencia):
                sf.liquidar_evento(**(p | mudanca))
        r2 = sf.liquidar_evento(**self.p(3))
        self.assertNotEqual(r.operacao_id, r2.operacao_id)
        self.assertNotEqual(r.lancamento_ids, r2.lancamento_ids)

    def test_replay_apos_mudancas_de_saldo_categoria_e_reversao(self):
        p = self.p(valor_centavos=1000)
        r = sf.liquidar_evento(**p)
        self.reclassificar_fixture(2)
        antes = self.foto()
        self.assertEqual(sf.liquidar_evento(**p), r)
        self.assertEqual(self.foto(), antes)
        self.estornar_fixture(r.liquidacao_ids[0], 1000)
        with self.f.conectar() as c:
            self.f.reverter(c, self.evento)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        antes = self.foto()
        with patch.object(sf, '_saldo_aberto_validado', side_effect=AssertionError('replay validou saldo')):
            self.assertEqual(sf.liquidar_evento(**p), r)
        self.assertEqual(self.foto(), antes)

    def test_operacao_aberta_persistida_nao_e_retomada(self):
        p = self.p()
        req = sf.canonicalizar_requisicao('liquidar_evento', **p)
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                      (req.chave, req.tipo_operacao, req.requisicao_canonica)); c.commit()
        antes = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta): sf.liquidar_evento(**p)
        self.assertEqual(self.foto(), antes)

    def test_estorno_parcial_e_integral_recompoem_saldo_sem_reutilizar_caixa(self):
        r = sf.liquidar_evento(**self.p(valor_centavos=1000))
        self.estornar_fixture(r.liquidacao_ids[0], 250)
        antes = self.foto()
        with self.assertRaises(sf.SaldoInsuficiente): sf.liquidar_evento(**self.p(3, valor_centavos=251))
        self.assertEqual(self.foto(), antes)
        p = self.p(3, valor_centavos=250)
        r2 = sf.liquidar_evento(**p)
        self.conferir(p, r2, antes)
        self.assertNotEqual(r.lancamento_ids, r2.lancamento_ids)
        self.estornar_fixture(r.liquidacao_ids[0], 750, natureza='correcao_registro')
        p3 = self.p(4, valor_centavos=750)
        antes = self.foto()
        self.conferir(p3, sf.liquidar_evento(**p3), antes)

    def test_int64_somas_brutas_podem_exceder_int64_mas_saldo_liquido_e_exato(self):
        e = self.criar_evento(10, valor=sf.MAX_CENTAVOS).evento_ids[0]
        for numero in (11, 12):
            p = self.p(numero, evento_id=e, valor_centavos=sf.MAX_CENTAVOS)
            r = sf.liquidar_evento(**p)
            self.estornar_fixture(r.liquidacao_ids[0], sf.MAX_CENTAVOS)
        antes = self.foto()
        p = self.p(13, evento_id=e, valor_centavos=sf.MAX_CENTAVOS)
        self.conferir(p, sf.liquidar_evento(**p), antes)

    def test_rateio_preexistente_valido_nao_restringe_relacao_muitos_para_muitos(self):
        outro = self.criar_evento(10).evento_ids[0]
        with self.f.conectar() as c:
            op = self.f.op(c, 'liquidar_evento')
            caixa = self.f.caixa(c, op, centavos=1000)
            self.f.liquidar(c, self.evento, 400, caixa)
            self.f.liquidar(c, outro, 600, caixa)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))
        antes = self.foto()
        p = self.p(valor_centavos=600)
        r = sf.liquidar_evento(**p)
        self.conferir(p, r, antes)
        self.assertNotEqual(r.lancamento_ids, (caixa,))

    def test_dados_de_liquidacao_orfa_valor_invalido_e_caixa_inconsistente(self):
        r = sf.liquidar_evento(**self.p())
        casos = {
            'orfa': (('liquidacoes_eventos',), lambda c: c.execute('UPDATE liquidacoes_eventos SET lancamento_id=999 WHERE id=?', r.liquidacao_ids)),
            'valor_zero': (('liquidacoes_eventos',), lambda c: c.execute('UPDATE liquidacoes_eventos SET valor_centavos=0 WHERE id=?', r.liquidacao_ids)),
            'excesso': (('liquidacoes_eventos',), lambda c: c.execute('UPDATE liquidacoes_eventos SET valor_centavos=1001 WHERE id=?', r.liquidacao_ids)),
            'superalocado': (('liquidacoes_eventos',), lambda c: c.execute('UPDATE liquidacoes_eventos SET valor_centavos=500 WHERE id=?', r.liquidacao_ids)),
            'real': (('lancamentos',), lambda c: c.execute('UPDATE lancamentos SET valor=0 WHERE id=?', r.lancamento_ids)),
            'aberta': (('operacoes_hibridas',), lambda c: c.execute("UPDATE operacoes_hibridas SET estado='aberta' WHERE id=?", (r.operacao_id,))),
        }
        for nome, (tabelas, mutacao) in casos.items():
            with self.subTest(nome=nome):
                destino = self.f.clone('corrupto_'+nome)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    self.corromper_fixture(tabelas, mutacao)
                    antes = self.foto()
                    with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('escreveu')):
                        with self.assertRaises(sf.OperacaoIncompleta): sf.liquidar_evento(**self.p(3, valor_centavos=1))
                    self.assertEqual(self.foto(), antes)

    def test_evento_manual_corrompido_e_soma_liquida_excessiva_sao_recusados(self):
        for coluna, valor in (('tipo', 'outro'), ('valor_centavos', 0), ('situacao_competencia', 'estimada')):
            destino = self.f.clone('evento_'+coluna)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.corromper_fixture(('eventos_financeiros',), lambda c:
                    c.execute(f'UPDATE eventos_financeiros SET {coluna}=? WHERE id=?', (valor, self.evento)))
                antes = self.foto()
                with self.assertRaises(sf.EventoNaoElegivel): sf.liquidar_evento(**self.p())
                self.assertEqual(self.foto(), antes)
        sf.liquidar_evento(**self.p())
        def excesso(c):
            op = self.f.op(c, 'liquidar_evento')
            caixa = self.f.caixa(c, op, centavos=700)
            self.f.liquidar(c, self.evento, 700, caixa)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))
        self.corromper_fixture(('liquidacoes_eventos',), excesso)
        antes = self.foto()
        with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('escreveu')):
            with self.assertRaises(sf.OperacaoIncompleta): sf.liquidar_evento(**self.p(3, valor_centavos=1))
        self.assertEqual(self.foto(), antes)

    def test_estorno_orfao_positivo_ou_excessivo_e_recusado(self):
        r = sf.liquidar_evento(**self.p())
        s = self.estornar_fixture(r.liquidacao_ids[0], 100)
        for caso in ('orfao', 'positivo', 'excesso'):
            with self.subTest(caso=caso):
                destino = self.f.clone('estorno_'+caso)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    if caso == 'orfao':
                        self.corromper_fixture(('estornos_liquidacoes',), lambda c:
                            c.execute('UPDATE estornos_liquidacoes SET lancamento_estorno_id=999 WHERE id=?', (s,)))
                    else:
                        def mutacao(c):
                            valor = 100 if caso == 'positivo' else -401
                            c.execute('UPDATE lancamentos SET valor_centavos=?,valor=CAST(? AS REAL)/100.0 '
                                'WHERE id=(SELECT lancamento_estorno_id FROM estornos_liquidacoes WHERE id=?)', (valor, valor, s))
                        self.corromper_fixture(('lancamentos',), mutacao)
                    antes = self.foto()
                    with patch.object(sf._UnidadeTrabalho, '_iniciar_operacao', side_effect=AssertionError('escreveu')):
                        with self.assertRaises(sf.OperacaoIncompleta): sf.liquidar_evento(**self.p(3, valor_centavos=1))
                    self.assertEqual(self.foto(), antes)

    def test_falhas_apos_cada_insert_fechamento_e_commit_revertem_tudo(self):
        antes = self.foto()
        abrir = banco.abrir_conexao
        for ponto in ('operacoes_hibridas', 'lancamentos', 'liquidacoes_eventos', 'conclusao', 'commit'):
            with self.subTest(ponto=ponto):
                real = abrir()
                class FalhaControlada:
                    fechada = False
                    def __getattr__(self, nome): return getattr(real, nome)
                    def execute(self, sql, *args):
                        cursor = real.execute(sql, *args)
                        if sql.startswith('INSERT INTO '+ponto) or (ponto == 'conclusao' and sql.startswith('UPDATE operacoes_hibridas')):
                            raise sqlite3.OperationalError('injetada:'+ponto)
                        return cursor
                    def commit(self):
                        if ponto == 'commit': raise sqlite3.OperationalError('injetada:commit')
                        real.commit()
                    def close(self): self.fechada = True; real.close()
                proxy = FalhaControlada()
                with patch.object(banco, 'abrir_conexao', return_value=proxy):
                    with self.assertRaises(sf.FalhaPersistencia) as erro: sf.liquidar_evento(**self.p())
                self.assertEqual(str(erro.exception.__cause__), 'injetada:'+ponto)
                self.assertTrue(proxy.fechada)
                self.assertEqual(self.foto(), antes)

    def test_guarda_real_recusa_caixa_orfao_e_liquidacao_extra(self):
        abrir = banco.abrir_conexao
        outro_evento = self.criar_evento(10).evento_ids[0]
        for caso in ('orfao', 'extra'):
            real = abrir()
            antes = self.foto()
            class EfeitosIncompletos:
                def __getattr__(self, nome): return getattr(real, nome)
                def execute(self, sql, *args):
                    if sql.startswith('INSERT INTO liquidacoes_eventos'):
                        if caso == 'orfao':
                            # Savepoint exclusivo da fixture: cursor ainda informa
                            # rowcount=1, mas o vinculo nao existe ao conferir efeitos.
                            real.execute('SAVEPOINT fixture_vinculo')
                            cursor = real.execute(sql, *args)
                            real.execute('ROLLBACK TO fixture_vinculo')
                            real.execute('RELEASE fixture_vinculo')
                            return cursor
                        # Dois pares validos somam o caixa, mas nao correspondem
                        # ao contrato de uma chamada/um evento/uma liquidacao.
                        valores = list(args[0]); valores[-1] = 200
                        cursor = real.execute(sql, valores)
                        real.execute('INSERT INTO liquidacoes_eventos(evento_id,lancamento_id,valor_centavos) '
                                     'VALUES(?,?,200)', (outro_evento, valores[2]))
                        return cursor
                    return real.execute(sql, *args)
            with patch.object(banco, 'abrir_conexao', return_value=EfeitosIncompletos()):
                with self.assertRaises(sf.OperacaoIncompleta): sf.liquidar_evento(**self.p())
            self.assertEqual(self.foto(), antes)

    def test_perda_de_resposta_apos_commit_recupera_mesmo_recibo(self):
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self): real.commit(); raise sqlite3.OperationalError('resposta perdida')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): sf.liquidar_evento(**self.p())
        antes = self.foto()
        r = sf.liquidar_evento(**self.p())
        self.assertEqual(sf.liquidar_evento(**self.p()), r)
        self.assertEqual(self.foto(), antes)

    def test_concorrencia_com_disputa_real_nao_excede_saldo_e_mesma_chave_replay(self):
        for mesmo in (False, True):
            with self.subTest(mesma_chave=mesmo):
                destino = self.f.clone('concorrencia_'+str(mesmo))
                pronta, ocupado, liberar, terminou = (threading.Event() for _ in range(4))
                resultados, erros = {}, {}
                abrir = banco.abrir_conexao
                p_a, p_b = self.p(2, valor_centavos=700), self.p(2 if mesmo else 3, valor_centavos=700)
                def abrir_controlada():
                    real = abrir(); real.execute('PRAGMA busy_timeout=1')
                    if threading.current_thread().name != 'liquidacao-a': return real
                    class CommitSuspenso:
                        def __getattr__(self, nome): return getattr(real, nome)
                        def commit(self):
                            pronta.set()
                            if not liberar.wait(10): raise AssertionError('nao liberou commit')
                            real.commit()
                    return CommitSuspenso()
                def a():
                    try: resultados['a'] = sf.liquidar_evento(**p_a)
                    except BaseException as erro: erros['a'] = erro
                    finally: terminou.set()
                def b():
                    try:
                        if not pronta.wait(10): raise AssertionError('A nao chegou no commit')
                        try:
                            sf.liquidar_evento(**p_b)
                            raise AssertionError('B nao disputou lock')
                        except sf.BancoOcupado as erro:
                            if erro.__cause__.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY: raise
                            ocupado.set()
                        if not terminou.wait(10): raise AssertionError('A nao terminou')
                        resultados['b'] = sf.liquidar_evento(**p_b)
                    except BaseException as erro: erros['b'] = erro
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), \
                        patch.object(banco, 'abrir_conexao', side_effect=abrir_controlada):
                    ta, tb = threading.Thread(target=a, name='liquidacao-a'), threading.Thread(target=b, name='liquidacao-b')
                    ta.start(); tb.start()
                    try: self.assertTrue(ocupado.wait(10), 'Disputa SQLite nao comprovada')
                    finally: liberar.set(); ta.join(15); tb.join(15)
                    self.assertFalse(ta.is_alive() or tb.is_alive())
                self.assertNotIn('a', erros)
                if mesmo:
                    self.assertFalse(erros)
                    self.assertEqual(resultados['a'], resultados['b'])
                else:
                    self.assertIsInstance(erros.get('b'), sf.SaldoInsuficiente)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), closing(banco.abrir_conexao()) as c:
                    self.assertEqual(c.execute('SELECT SUM(valor_centavos) FROM liquidacoes_eventos WHERE evento_id=?',
                        (self.evento,)).fetchone(), (700,))
                    self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (2,))


if __name__ == '__main__':
    unittest.main()
