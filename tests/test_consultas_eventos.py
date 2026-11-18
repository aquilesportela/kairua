"""Consultas 3.3C.1; todo SQLite é sintético e temporário via KAIRUA_DB_PATH."""
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import date
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import banco
import consultas_eventos as ce
import interface_eventos as ui
import servicos_financeiros as sf
import test_liquidar_evento as fixture


class TestConsultasEventos(unittest.TestCase):
    def setUp(self):
        self.h = fixture.TestLiquidarEvento()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()
        self.f = self.h.f
        self.e = self.h.evento
        self.numero = 100

    def chave(self):
        self.numero += 1
        return fixture.chave(self.numero)

    def pagar(self, valor=400, evento=None):
        return sf.liquidar_evento(chave=self.chave(), evento_id=self.e if evento is None else evento,
            valor_centavos=valor, data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)

    def estornar(self, q, valor, natureza='devolucao_real'):
        return sf.estornar_liquidacao(chave=self.chave(), liquidacao_id=q, valor_centavos=valor,
            natureza=natureza, motivo='Devolução', data_estorno=date(2026, 11, 1),
            confirmar_datas_divergentes=False)

    def test_banco_inexistente_nao_cria_arquivo(self):
        destino = self.f.caminho.with_name('inexistente ?#.db')
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            for consultar in (ce.listar_eventos_liquidaveis, ce.listar_liquidacoes_estornaveis):
                with self.assertRaises(ce.ConsultaIndisponivel):
                    consultar()
        self.assertFalse(destino.exists())

    def test_uri_escapa_nome_com_espaco_acentos_e_fragmento(self):
        destino = self.f.clone('consulta ação # 100%')
        antes = destino.read_bytes()
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            self.assertEqual(ce.obter_detalhe_evento(self.e).saldo_aberto_centavos, 1000)
        self.assertEqual(destino.read_bytes(), antes)

    def test_esquema_ausente_e_versao_incompativel(self):
        destino = self.f.caminho.with_name('vazio.db')
        with closing(sqlite3.connect(destino)):
            pass
        for caminho in (destino, self.h.v2):
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(caminho)}), self.assertRaises(sf.EsquemaIncompativel):
                ce.listar_eventos_liquidaveis()

    def test_view_adulterada_e_tabela_ausente_rejeitadas(self):
        for numero, sql in enumerate(('DROP VIEW eventos_classificacao_atual', 'DROP TABLE estornos_liquidacoes')):
            destino = self.f.clone('incompativel' + str(numero))
            with closing(sqlite3.connect(destino)) as c:
                c.execute(sql)
                c.commit()
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), self.assertRaises(sf.EsquemaIncompativel):
                ce.listar_eventos_liquidaveis()

    def test_evento_sem_liquidacao_saldo_e_resultado_imutavel(self):
        e = ce.obter_detalhe_evento(self.e)
        self.assertEqual((e.valor_original_centavos, e.total_liquidado_bruto_centavos,
            e.total_estornado_centavos, e.total_liquidado_liquido_centavos, e.saldo_aberto_centavos),
            (1000, 0, 0, 0, 1000))
        self.assertEqual((e.liquidacoes, e.reversao), ((), None))
        self.assertEqual(e.data_vencimento, date(2026, 12, 15))
        self.assertEqual(ce.listar_eventos_liquidaveis(), (e,))
        self.assertEqual(ce.listar_liquidacoes_estornaveis(), ())
        with self.assertRaises(FrozenInstanceError):
            e.saldo_aberto_centavos = 0

    def test_liquidacao_parcial_e_integral(self):
        r = self.pagar(400)
        self.assertEqual(ce.obter_detalhe_evento(self.e).saldo_aberto_centavos, 600)
        q = ce.obter_detalhe_liquidacao(r.liquidacao_ids[0])
        self.assertEqual((q.evento_id, q.lancamento_id, q.valor_original_centavos,
                          q.saldo_estornavel_centavos), (self.e, r.lancamento_ids[0], 400, 400))
        self.pagar(600)
        self.assertEqual(ce.obter_detalhe_evento(self.e).saldo_aberto_centavos, 0)
        self.assertEqual(ce.listar_eventos_liquidaveis(), ())
        self.assertEqual(len(ce.listar_liquidacoes_estornaveis()), 2)

    def test_estornos_parciais_integral_e_saldo_reaberto(self):
        r = self.pagar(1000)
        qid = r.liquidacao_ids[0]
        self.estornar(qid, 250)
        self.estornar(qid, 150, 'correcao_registro')
        e = ce.obter_detalhe_evento(self.e)
        self.assertEqual((e.total_liquidado_bruto_centavos, e.total_estornado_centavos,
            e.total_liquidado_liquido_centavos, e.saldo_aberto_centavos), (1000, 400, 600, 400))
        self.assertEqual([s.valor_centavos for s in e.liquidacoes[0].estornos], [-250, -150])
        self.assertEqual(e.liquidacoes[0].saldo_estornavel_centavos, 600)
        self.estornar(qid, 600)
        self.assertEqual(ce.obter_detalhe_liquidacao(qid).saldo_estornavel_centavos, 0)
        self.assertEqual(ce.listar_liquidacoes_estornaveis(), ())
        self.assertEqual(ce.listar_eventos_liquidaveis()[0].saldo_aberto_centavos, 1000)

    def test_evento_revertido_preserva_historico_sem_compromisso_aberto(self):
        r = self.pagar(1000)
        self.estornar(r.liquidacao_ids[0], 1000)
        sf.reverter_evento(chave=self.chave(), evento_id=self.e, data_reversao=date(2027, 1, 1), motivo='Cancelado')
        e = ce.obter_detalhe_evento(self.e)
        self.assertIsNotNone(e.reversao)
        self.assertEqual((e.valor_original_centavos, e.total_liquidado_bruto_centavos,
                          e.total_estornado_centavos, e.saldo_aberto_centavos), (1000, 1000, 1000, 0))
        self.assertEqual((ce.listar_eventos_liquidaveis(), ce.listar_liquidacoes_estornaveis()), ((), ()))
        self.assertFalse(ce.obter_detalhe_liquidacao(r.liquidacao_ids[0]).elegivel_estorno)

    def test_reversao_com_liquidacao_ativa_e_erro_nao_saldo_zero(self):
        self.pagar(400)
        def corromper(c):
            op = self.f.op(c, 'reverter_evento')
            c.execute("INSERT INTO reversoes_eventos(evento_id,operacao_hibrida_id,data_competencia,"
                      "categoria_id,motivo) VALUES(?,?,'2026-11-01',1,'Fixture inconsistente')", (self.e, op))
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))
        self.h.corromper_fixture(('reversoes_eventos',), corromper)
        for consultar in (lambda: ce.obter_detalhe_evento(self.e), ce.listar_eventos_liquidaveis,
                          ce.listar_liquidacoes_estornaveis):
            with self.assertRaises(sf.OperacaoIncompleta):
                consultar()

    def test_categoria_corrente_e_classificacao_historica_distintas(self):
        r = self.pagar(400)
        antes = ce.obter_detalhe_liquidacao(r.liquidacao_ids[0]).categoria_historica
        sf.reclassificar_evento(chave=self.chave(), evento_id=self.e, categoria_nova_id=2, motivo='Classificar')
        with closing(banco.abrir_conexao()) as c:
            c.execute("UPDATE categorias SET nome='Nome atualizado' WHERE id=1")
            c.commit()
        self.estornar(r.liquidacao_ids[0], 100)
        e = ce.obter_detalhe_evento(self.e)
        self.assertEqual(e.categoria_atual.id, 2)
        self.assertEqual(e.liquidacoes[0].categoria_historica, antes)
        self.assertEqual(e.liquidacoes[0].estornos[0].categoria_historica, antes)

    def test_receita_e_categoria_legada_com_id_negativo(self):
        with closing(banco.abrir_conexao()) as c:
            c.execute("INSERT INTO categorias(id,nome,tipo) VALUES(-1,'Receita histórica','receita')")
            c.commit()
        e = self.h.criar_evento(300, valor=1, tipo='receita', categoria=-1).evento_ids[0]
        q = self.pagar(1, e).liquidacao_ids[0]
        self.estornar(q, 1)
        detalhe = ce.obter_detalhe_evento(e)
        self.assertEqual((detalhe.tipo, detalhe.categoria_atual.id, detalhe.saldo_aberto_centavos), ('receita', -1, 1))

    def test_somas_brutas_acima_int64_e_centavo_residual(self):
        e = self.h.criar_evento(300, valor=sf.MAX_CENTAVOS).evento_ids[0]
        for _ in range(2):
            r = self.pagar(sf.MAX_CENTAVOS, e)
            self.estornar(r.liquidacao_ids[0], sf.MAX_CENTAVOS)
        self.pagar(sf.MAX_CENTAVOS-1, e)
        detalhe = ce.obter_detalhe_evento(e)
        self.assertEqual(detalhe.total_liquidado_bruto_centavos, 3*sf.MAX_CENTAVOS-1)
        self.assertEqual(detalhe.total_estornado_centavos, 2*sf.MAX_CENTAVOS)
        self.assertEqual(detalhe.saldo_aberto_centavos, 1)
        self.assertIs(type(detalhe.total_liquidado_bruto_centavos), int)

    def test_multiplas_liquidacoes_estornos_sem_multiplicacao_de_joins(self):
        for valor in (200, 300, 500):
            q = self.pagar(valor).liquidacao_ids[0]
            self.estornar(q, 20)
            self.estornar(q, 30)
        e = ce.obter_detalhe_evento(self.e)
        self.assertEqual((e.total_liquidado_bruto_centavos, e.total_estornado_centavos,
                          e.total_liquidado_liquido_centavos, e.saldo_aberto_centavos), (1000, 150, 850, 150))
        self.assertEqual(len(e.liquidacoes), 3)
        self.assertEqual(sum(len(q.estornos) for q in e.liquidacoes), 6)

    def test_rateio_limite_por_liquidacao_sem_somar_caixa_inteiro(self):
        outro = self.h.criar_evento(300).evento_ids[0]
        with self.f.conectar() as c:
            op = self.f.op(c, 'liquidar_evento')
            caixa = self.f.caixa(c, op, centavos=1000)
            q1 = self.f.liquidar(c, self.e, 300, caixa)
            q2 = self.f.liquidar(c, outro, 700, caixa)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,))
        self.estornar(q1, 100)
        primeiro = ce.obter_detalhe_liquidacao(q1)
        self.assertEqual((primeiro.valor_original_centavos, primeiro.valor_caixa_centavos,
                          primeiro.saldo_estornavel_centavos), (300, 1000, 200))
        self.assertEqual(ce.obter_detalhe_liquidacao(q2).saldo_estornavel_centavos, 700)
        self.assertEqual(ce.obter_detalhe_evento(self.e).saldo_aberto_centavos, 800)
        self.assertEqual(ce.obter_detalhe_evento(outro).saldo_aberto_centavos, 300)

    def test_referencias_orfas_nao_sao_ocultadas(self):
        self.pagar(400)
        self.h.corromper_fixture(('liquidacoes_eventos',), lambda c:
            c.execute('UPDATE liquidacoes_eventos SET evento_id=999999'))
        for consultar in (ce.listar_eventos_liquidaveis, ce.listar_liquidacoes_estornaveis):
            with self.assertRaises(sf.OperacaoIncompleta):
                consultar()

    def test_estorno_orfao_nao_gera_saldo_zero(self):
        r = self.pagar(400)
        self.estornar(r.liquidacao_ids[0], 100)
        self.h.corromper_fixture(('estornos_liquidacoes',), lambda c:
            c.execute('UPDATE estornos_liquidacoes SET lancamento_estorno_id=999999'))
        with self.assertRaises(sf.OperacaoIncompleta):
            ce.obter_detalhe_evento(self.e)

    def test_sinais_valores_e_excesso_inconsistentes_rejeitados(self):
        r = self.pagar(400)
        self.estornar(r.liquidacao_ids[0], 100)
        for numero, (tabelas, sql) in enumerate([
            (('lancamentos',), 'UPDATE lancamentos SET valor_centavos=100,valor=1 WHERE valor_centavos<0'),
            (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET valor_centavos=0'),
            (('estornos_liquidacoes',), "UPDATE estornos_liquidacoes SET natureza='inexistente'"),
            (('operacoes_hibridas',), "UPDATE operacoes_hibridas SET estado='aberta'"),
            (('lancamentos',), 'UPDATE lancamentos SET categoria_id=999999'),
            (('liquidacoes_eventos',), 'UPDATE liquidacoes_eventos SET valor_centavos=2000'),
            (('lancamentos',), 'UPDATE lancamentos SET valor_centavos=-500,valor=-5 WHERE valor_centavos<0'),
        ]):
            destino = self.f.clone('corrompido' + str(numero))
            with self.subTest(sql=sql), patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                self.h.corromper_fixture(tabelas, lambda c: c.execute(sql))
                with self.assertRaises(sf.OperacaoIncompleta):
                    ce.obter_detalhe_evento(self.e)

    def test_legado_nao_e_adotado_e_permanece_inalterado(self):
        destino = self.h.v2
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            with closing(banco.abrir_conexao()) as c:
                c.execute("INSERT INTO eventos_financeiros(id,tipo,descricao,categoria_id,valor_centavos,"
                    "situacao_competencia,chave_origem) VALUES(100,'despesa','Histórico',1,100,'pendente','historico:1')")
                c.execute("INSERT INTO lancamentos(data,descricao,tipo,categoria,valor,categoria_id) "
                          "VALUES('2020-01-01','Legado','despesa','Alimentação',12.34,1)")
                c.commit()
            banco.aplicar_migracoes(destino)
            antes = self.h.foto()
            self.assertEqual(ce.listar_eventos_liquidaveis(), ())
            self.assertEqual(ce.listar_liquidacoes_estornaveis(), ())
            with self.assertRaises(sf.EventoNaoElegivel):
                ce.obter_detalhe_evento(100)
            self.assertEqual(self.h.foto(), antes)

    def test_snapshot_consistente_com_commit_em_conexao_independente(self):
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
        original = ce._Grafo._base
        confirmado = []
        def ler(g, identificador):
            resultado = original(g, identificador)
            if not confirmado:
                confirmado.append(self.pagar(400))
            return resultado
        with patch.object(ce._Grafo, '_base', ler):
            antigo = ce.obter_detalhe_evento(self.e)
        self.assertEqual(len(confirmado), 1)
        self.assertEqual((antigo.total_liquidado_bruto_centavos, antigo.saldo_aberto_centavos), (0, 1000))
        self.assertEqual(ce.obter_detalhe_evento(self.e).saldo_aberto_centavos, 600)

    def test_somente_leitura_sem_migracao_e_fechamento(self):
        self.pagar()
        antes = self.f.caminho.read_bytes()
        abrir = sqlite3.connect
        conexoes, sqls = [], []
        def rastrear(*args, **kwargs):
            self.assertTrue(args[0].endswith('?mode=ro'))
            self.assertTrue(kwargs['uri'])
            c = abrir(*args, **kwargs)
            c.set_trace_callback(sqls.append)
            conexoes.append(c)
            return c
        with patch.object(ce.sqlite3, 'connect', side_effect=rastrear), \
                patch.object(banco, 'aplicar_migracoes', side_effect=AssertionError('Migração')):
            ce.listar_eventos_liquidaveis()
            ce.obter_detalhe_evento(self.e)
            ce.listar_liquidacoes_estornaveis()
            ce.obter_detalhe_liquidacao(1)
        self.assertEqual(self.f.caminho.read_bytes(), antes)
        for c in conexoes:
            with self.assertRaises(sqlite3.ProgrammingError):
                c.execute('SELECT 1')
        self.assertEqual(sum(s == 'BEGIN' for s in sqls), 4)
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')) for s in sqls))

    def test_conexao_recusa_escrita_e_fecha_apos_excecao(self):
        c = None
        with self.assertRaises(ce.ConsultaIndisponivel):
            with ce._snapshot() as g:
                c = g.c
                c.execute("UPDATE eventos_financeiros SET descricao='Não permitido'")
        with self.assertRaises(sqlite3.ProgrammingError):
            c.execute('SELECT 1')
        self.assertEqual(ce.obter_detalhe_evento(self.e).descricao, 'Descricao original')

    def test_ids_invalidos_e_inexistentes(self):
        for valor in (True, 0, -1, sf.MAX_CENTAVOS+1, '1'):
            with self.subTest(valor=valor), self.assertRaises(sf.ParametroInvalido):
                ce.obter_detalhe_evento(valor)
        with self.assertRaises(sf.EventoInexistente):
            ce.obter_detalhe_evento(999)
        with self.assertRaises(sf.LiquidacaoInexistente):
            ce.obter_detalhe_liquidacao(999)

    def test_interface_leitura_fluxo_completo_sem_escrita_ou_diario(self):
        r = self.pagar(400)
        self.estornar(r.liquidacao_ids[0], 100)
        antes = self.h.foto()
        entradas = iter(['4', '1', '2', str(self.e), '3', '4', str(r.liquidacao_ids[0]), '0', '0'])
        saidas = []
        armazenamento = Mock()
        with patch.object(sf, 'registrar_evento_manual', side_effect=AssertionError('Escrita')), \
                patch.object(sf, 'liquidar_evento', side_effect=AssertionError('Escrita')), \
                patch.object(sf, 'estornar_liquidacao', side_effect=AssertionError('Escrita')):
            ui.menu_eventos_financeiros(entrada=lambda _: next(entradas), saida=saidas.append,
                                       armazenamento=armazenamento)
        self.assertEqual(self.h.foto(), antes)
        self.assertEqual(armazenamento.mock_calls, [])
        texto = '\n'.join(saidas)
        for esperado in ('Competência', 'Saldo aberto: R$ 7,00', 'Saldo estornável: R$ 3,00',
                         'caixa original', 'ESTORNO', 'R$ -1,00', 'devolucao_real', 'Categoria histórica'):
            self.assertIn(esperado, texto)

    def test_interface_fecha_conexao_antes_de_solicitar_proxima_entrada(self):
        abrir = sqlite3.connect
        conexoes = []
        def rastrear(*args, **kwargs):
            c = abrir(*args, **kwargs)
            conexoes.append(c)
            return c
        escolhas = iter(['1', '0'])
        def entrada(_):
            for c in conexoes:
                with self.assertRaises(sqlite3.ProgrammingError):
                    c.execute('SELECT 1')
            return next(escolhas)
        with patch.object(ce.sqlite3, 'connect', side_effect=rastrear):
            ui.menu_consultas_eventos(entrada=entrada, saida=lambda _: None)
        self.assertEqual(len(conexoes), 1)

    def test_interface_cancelamento_nao_abre_banco(self):
        for sequencia in (['0'], ['2', '0', '4', '0', '0']):
            entradas = iter(sequencia)
            with patch.object(ce.sqlite3, 'connect', side_effect=AssertionError('Abriu')):
                ui.menu_consultas_eventos(entrada=lambda _: next(entradas), saida=lambda _: None)

    def test_interface_inconsistencia_explicita_sem_presumir_saldo(self):
        entradas = iter(['1', '0'])
        saidas = []
        with patch.object(ce, 'listar_eventos_liquidaveis', side_effect=sf.OperacaoIncompleta('Referência ausente')):
            ui.menu_consultas_eventos(entrada=lambda _: next(entradas), saida=saidas.append)
        self.assertTrue(any('Inconsistência financeira detectada' in s for s in saidas))
        self.assertFalse(any('Nenhum evento elegível' in s for s in saidas))


class TestApresentacaoConsultas(unittest.TestCase):
    def test_formatacao_exata_negativos_e_totais_acima_int64(self):
        for valor, esperado in [(0, 'R$ 0,00'), (1, 'R$ 0,01'), (-123456, 'R$ -1.234,56'),
            (sf.MAX_CENTAVOS, 'R$ 92.233.720.368.547.758,07'),
            (2*sf.MAX_CENTAVOS, 'R$ 184.467.440.737.095.516,14')]:
            self.assertEqual(ui.formatar_centavos(valor), esperado)
        for valor in (True, 1.0, '100'):
            with self.assertRaises(sf.ValorInvalido):
                ui.formatar_centavos(valor)

    def test_import_consultas_nao_abre_banco(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / 'nao_criar.db'
            codigo = ('import sqlite3\nfrom unittest.mock import patch\n'
                      'with patch.object(sqlite3,"connect",side_effect=AssertionError("Abriu")):\n'
                      ' import consultas_eventos\n')
            subprocess.run([sys.executable, '-B', '-c', codigo], check=True,
                           env=os.environ | {'KAIRUA_DB_PATH': str(destino)})
            self.assertFalse(destino.exists())
