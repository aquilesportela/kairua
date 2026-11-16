"""Fixtures financeiras apenas de teste; nenhum servico antecipado em producao."""
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal, localcontext
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import UUID

import banco
import servicos_financeiros as sf
import test_migracao_3 as base


def chave(numero=1):
    return 'kairua:v1:' + str(UUID(int=numero))


def parametros_evento():
    return dict(tipo='despesa', descricao='Manual', categoria_id=1,
                valor_centavos=1000, data_competencia=date(2026, 11, 1),
                data_vencimento=date(2026, 12, 1), confirmar_ocorrencia=True)


class TestValidadoresServicos(unittest.TestCase):
    def test_magnitudes_int64_estritas(self):
        for valor in (1, 100, sf.MAX_CENTAVOS):
            self.assertEqual(sf.validar_centavos(valor), valor)
        for valor in (True, False, 0, -1, -2**63, 2**63, 1.0, '100', Decimal(1), None):
            with self.subTest(valor=valor), self.assertRaises(sf.ValorInvalido):
                sf.validar_centavos(valor)

    def test_decimal_exato_inclusive_limites(self):
        for entrada, esperado in [('0.01', 1), ('1.000', 100), (Decimal('1E-2'), 1),
                                   ('92233720368547758.07', sf.MAX_CENTAVOS),
                                   (Decimal('0.0100000000000000000000000000'), 1)]:
            self.assertEqual(sf.converter_decimal_centavos(entrada), esperado)

    def test_decimal_fracao_nao_arredonda_com_contexto_pequeno(self):
        with localcontext() as contexto:
            contexto.prec = 2
            self.assertEqual(sf.converter_decimal_centavos('92233720368547758.07'), sf.MAX_CENTAVOS)
            for valor in ('1.001', Decimal('1.00000000000000000000000000001'),
                          Decimal('1E-1000000000'), Decimal('1E+1000000000')):
                with self.subTest(valor=valor), self.assertRaises(sf.ValorInvalido):
                    sf.converter_decimal_centavos(valor)

    def test_decimal_rejeita_formatos_tipos_e_excessos(self):
        for valor in ('0', '-1', '1,00', '1.000,00', '1e2', ' 1.00 ', 'NaN', 'Infinity',
                      '92233720368547758.08', '1' * 4097, '', None, 1, True, 1.5,
                      Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity'), Decimal('-0')):
            with self.subTest(valor=str(valor)[:30]), self.assertRaises(sf.ValorInvalido):
                sf.converter_decimal_centavos(valor)

    def test_datas_puras_futuras_retroativas_e_calendario(self):
        for texto in ('0001-01-01', '2024-02-29', '9999-12-31'):
            self.assertEqual(sf.validar_data(sf.interpretar_data_iso(texto)).isoformat(), texto)
        for texto in ('2023-02-29', '2026-04-31', '2026-2-01', '0000-01-01', '20261101', None):
            with self.subTest(texto=texto), self.assertRaises(sf.DataInvalida):
                sf.interpretar_data_iso(texto)
        for valor in ('2026-11-01', datetime(2026, 11, 1), None):
            with self.assertRaises(sf.DataInvalida):
                sf.validar_data(valor)

    def test_confirmacao_datas_tipo_estrito(self):
        sf.confirmar_datas(date(2026, 1, 1), date(2026, 1, 1), False)
        sf.confirmar_datas(date(2030, 1, 1), date(2020, 1, 1), True)
        with self.assertRaises(sf.ConfirmacaoNecessaria):
            sf.confirmar_datas(date(2030, 1, 1), date(2020, 1, 1), False)
        with self.assertRaises(sf.ParametroInvalido):
            sf.confirmar_datas(date.today(), date.today(), 1)

    def test_textos_nfc_trim_sem_apagar_diferencas(self):
        self.assertEqual(sf.normalizar_texto('  Cafe\u0301  a  '), 'Café  a')
        self.assertNotEqual(sf.normalizar_texto('A  b'), sf.normalizar_texto('a b'))
        for valor in (' ', None, 'a\x00b', '\ud800'):
            with self.assertRaises(sf.ParametroInvalido):
                sf.normalizar_texto(valor)

    def test_chaves_validas_e_invalidas_sem_reparo(self):
        self.assertEqual(sf.validar_chave(chave()), chave())
        for valor in (None, chave().upper(), chave().replace('-', ''), ' '+chave(),
                      chave()+' ', 'kairua:v2:'+str(UUID(int=1)), 'kairua:v1:invalido'):
            with self.subTest(valor=valor), self.assertRaises(sf.ParametroInvalido):
                sf.validar_chave(valor)

    def test_json_dourado_equivalente_e_divergente(self):
        req = sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **parametros_evento())
        esperado = ('{"parametros":{"categoria_id":1,"confirmar_ocorrencia":true,'
            '"data_competencia":"2026-11-01","data_vencimento":"2026-12-01",'
            '"descricao":"Manual","tipo":"despesa","valor_centavos":1000},'
            '"servico":"registrar_evento_manual","tipo_operacao":"registrar_evento","versao_contrato":1}')
        self.assertEqual(req.requisicao_canonica, esperado)
        p = dict(reversed(list(parametros_evento().items())))
        p['descricao'] = ' Manual '
        self.assertEqual(req, sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **p))
        p['valor_centavos'] += 1
        self.assertNotEqual(req, sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **p))
        p['descricao'] = 'Cafe\u0301'
        a = sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **p)
        p['descricao'] = 'Café'
        self.assertEqual(a, sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **p))
        with self.assertRaises(FrozenInstanceError):
            req.chave = chave(2)

    def test_campos_fechados_confirmacao_e_opcionais(self):
        p = parametros_evento()
        for mudancas in ({'extra': 1}, {'tipo': 'outro'}, {'valor_centavos': 1.0},
                         {'confirmar_ocorrencia': False}, {'categoria_id': True}):
            with self.assertRaises(sf.ParametroInvalido):
                sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave(), **(p | mudancas))
        with self.assertRaises(sf.ParametroInvalido):
            sf.canonicalizar_requisicao('registrar_evento_manual', chave=chave())
        req = sf.canonicalizar_requisicao('liquidar_evento', chave=chave(), evento_id=1,
            valor_centavos=10, data_liquidacao=date(2026, 1, 1), confirmar_datas_divergentes=False)
        self.assertIsNone(json.loads(req.requisicao_canonica)['parametros']['descricao_caixa'])

    def test_import_nao_abre_nem_migra_banco(self):
        # Mocks no proprio processo importador, nao apenas no pai.
        with tempfile.TemporaryDirectory() as pasta:
            env = os.environ.copy()
            destino = Path(pasta) / 'nao_criar.db'
            env['KAIRUA_DB_PATH'] = str(destino)
            codigo = ('from unittest.mock import patch\nimport banco,sqlite3\n'
                'with patch.object(banco,"abrir_conexao",side_effect=AssertionError("abriu")), '
                'patch.object(banco,"aplicar_migracoes",side_effect=AssertionError("migrou")), '
                'patch.object(sqlite3,"connect",side_effect=AssertionError("conectou")):\n'
                ' import servicos_financeiros\n')
            subprocess.run([sys.executable, '-B', '-c', codigo], env=env, check=True)
            self.assertFalse(destino.exists())


class TestInfraestruturaServicos(unittest.TestCase):
    def setUp(self):
        self.f = base.TestMigracao3()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.f.migrar()

    def req(self, numero=1, servico='registrar_evento_manual', **p):
        if not p:
            p = parametros_evento()
        return sf.canonicalizar_requisicao(servico, chave=chave(numero), **p)

    def fixture_evento(self, c, req, op):
        p = json.loads(req.requisicao_canonica)['parametros']
        campos = {k: p[k] for k in ('tipo', 'descricao', 'categoria_id', 'valor_centavos',
                                    'data_competencia', 'data_vencimento')}
        return self.f.evento(c, op, **campos, chave_origem='manual:'+req.chave+':evento:0')

    def gravar_fixture(self, req, escritor=None):
        with sf._UnidadeTrabalho(req) as u:
            if u.anterior is None:
                op = u._iniciar_operacao()
                (escritor or self.fixture_evento)(u._conexao, req, op)
                u._concluir()
            with self.assertRaises(sf.OperacaoIncompleta):
                _ = u.resultado
        return u.resultado

    def foto(self):
        with closing(banco.abrir_conexao()) as c:
            return {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_transacao_real_pragmas_recibo_e_replay_sem_escrita(self):
        req = self.req()
        recibo = self.gravar_fixture(req)
        foto = self.foto()
        with sf._UnidadeTrabalho(req) as u:
            c = u._conexao
            self.assertTrue(c.in_transaction)
            self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone(), (1,))
            self.assertEqual(c.execute('PRAGMA recursive_triggers').fetchone(), (1,))
            self.assertEqual(u.anterior, recibo)
            self.assertEqual(c.total_changes, 0)
        self.assertEqual(u.resultado, recibo)
        self.assertEqual(self.foto(), foto)
        with self.assertRaises(sqlite3.ProgrammingError):
            c.execute('SELECT 1')
        with self.assertRaises(FrozenInstanceError):
            recibo.evento_ids = ()

    def test_conflito_payload_ou_tipo_na_mesma_chave(self):
        req = self.req()
        self.gravar_fixture(req)
        foto = self.foto()
        for outro in (self.req(**(parametros_evento() | {'valor_centavos': 99})),
                      self.req(servico='reverter_evento', evento_id=1,
                               data_reversao=date(2026, 1, 1), motivo='Motivo')):
            with self.assertRaises(sf.ConflitoIdempotencia):
                with sf._UnidadeTrabalho(outro):
                    self.fail('Nao deve entrar no corpo')
            self.assertEqual(self.foto(), foto)

    def test_operacao_aberta_preexistente_nao_e_retomada(self):
        req = self.req()
        with closing(banco.abrir_conexao()) as c:
            c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                      (req.chave, req.tipo_operacao, req.requisicao_canonica))
            c.commit()
        foto = self.foto()
        with self.assertRaises(sf.OperacaoIncompleta):
            with sf._UnidadeTrabalho(req): pass
        self.assertEqual(self.foto(), foto)

    def test_guardas_reais_rejeitam_vazio_aberto_efeitos_extras_e_caixa_orfao(self):
        foto = self.foto()
        for ponto in ('sem_operacao', 'aberta', 'vazia', 'extra', 'sem_vinculo'):
            with self.subTest(ponto=ponto), self.assertRaises(sf.OperacaoIncompleta):
                req = self.req()
                if ponto == 'sem_vinculo':
                    req = self.req(servico='registrar_operacao_imediata', **parametros_evento(),
                                   data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)
                with sf._UnidadeTrabalho(req) as u:
                    if ponto == 'sem_operacao': continue
                    op = u._iniciar_operacao()
                    if ponto in ('extra', 'sem_vinculo'):
                        self.fixture_evento(u._conexao, req, op)
                        if ponto == 'extra':
                            self.f.evento(u._conexao, op)
                        else:
                            self.f.caixa(u._conexao, op)
                    if ponto != 'aberta': u._concluir()
            self.assertEqual(self.foto(), foto)

    def test_rollback_em_fronteiras_distintas(self):
        foto = self.foto()
        for ponto in ('entrada', 'operacao', 'efeito', 'conclusao'):
            with self.subTest(ponto=ponto), self.assertRaisesRegex(RuntimeError, 'injetada'):
                req = self.req()
                with sf._UnidadeTrabalho(req) as u:
                    if ponto != 'entrada':
                        op = u._iniciar_operacao()
                        if ponto != 'operacao':
                            self.fixture_evento(u._conexao, req, op)
                            if ponto == 'conclusao': u._concluir()
                    raise RuntimeError('falha injetada')
            self.assertEqual(self.foto(), foto)
            with self.assertRaises(sqlite3.ProgrammingError):
                u._conexao.execute('SELECT 1')

    def test_erro_sqlite_tem_causa_e_faz_rollback(self):
        foto = self.foto()
        with self.assertRaises(sf.FalhaPersistencia) as capturado:
            with sf._UnidadeTrabalho(self.req()) as u:
                u._iniciar_operacao()
                u._conexao.execute('SQL INVALIDO')
        self.assertIsInstance(capturado.exception.__cause__, sqlite3.Error)
        self.assertEqual(self.foto(), foto)

    def test_esquema_ausente_sem_inicializar(self):
        vazio = self.f.caminho.with_name('vazio.db')
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(vazio)}):
            with self.assertRaises(sf.EsquemaIncompativel):
                with sf._UnidadeTrabalho(self.req()): pass
            with closing(sqlite3.connect(vazio)) as c:
                self.assertEqual(c.execute('SELECT name FROM sqlite_master').fetchall(), [])

    def test_esquemas_incompativeis_rejeitados_sem_escrita(self):
        alteracoes = [
            'DROP TRIGGER tr_eventos_bi',
            'DROP VIEW eventos_classificacao_atual',
            'CREATE UNIQUE INDEX novo ON lancamentos(descricao)',
            'CREATE UNIQUE INDEX novo ON categorias(lower(nome)) WHERE id>0',
            'CREATE TRIGGER externo AFTER INSERT ON COMPRAS_CARTAO BEGIN SELECT 1; END',
            "UPDATE esquema_migracoes SET nome='outro' WHERE versao=3",
            "INSERT INTO esquema_migracoes(versao,nome) VALUES(4,'futura')",
            'DROP INDEX idx_eventos_competencia',
        ]
        for i, sql in enumerate(alteracoes):
            with self.subTest(sql=sql):
                destino = self.f.clone(f'incompativel_{i}')
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        c.execute(sql); c.commit()
                    foto = self.foto()
                    with self.assertRaises(sf.EsquemaIncompativel):
                        with sf._UnidadeTrabalho(self.req()): pass
                    self.assertEqual(self.foto(), foto)

    def test_indice_nao_unico_adicional_permitido(self):
        with closing(banco.abrir_conexao()) as c:
            c.execute('CREATE INDEX extra ON lancamentos(lower(descricao)) WHERE id>0')
            c.commit()
        self.gravar_fixture(self.req())

    def test_alteracao_de_check_e_indice_com_dono_errado_rejeitada(self):
        for caso in ('check', 'indice'):
            with self.subTest(caso=caso):
                destino = self.f.clone(caso)
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    with closing(banco.abrir_conexao()) as c:
                        if caso == 'check':
                            sql = c.execute("SELECT sql FROM sqlite_master WHERE name='operacoes_hibridas'").fetchone()[0]
                            c.execute('DROP TABLE operacoes_hibridas')
                            c.execute(sql.replace('CHECK (id > 0)', 'CHECK (id >= 0)'))
                        else:
                            c.execute('DROP INDEX idx_eventos_competencia')
                            c.execute('CREATE INDEX idx_eventos_competencia ON reversoes_eventos(data_competencia)')
                        c.commit()
                    with self.assertRaises(sf.EsquemaIncompativel):
                        with sf._UnidadeTrabalho(self.req()): pass

    def test_manifesto_nao_e_cache_do_banco_apos_primeira_chamada(self):
        self.gravar_fixture(self.req())
        with closing(banco.abrir_conexao()) as c:
            c.execute('DROP TRIGGER tr_liquidacoes_bi'); c.commit()
        with self.assertRaises(sf.EsquemaIncompativel):
            with sf._UnidadeTrabalho(self.req()): pass

    def test_operacao_concluida_incompleta_rejeitada_no_replay(self):
        req = self.req()
        with closing(banco.abrir_conexao()) as c:
            op = c.execute('INSERT INTO operacoes_hibridas(chave,tipo,requisicao_canonica) VALUES(?,?,?)',
                           (req.chave, req.tipo_operacao, req.requisicao_canonica)).lastrowid
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=?", (op,)); c.commit()
        with self.assertRaises(sf.OperacaoIncompleta):
            with sf._UnidadeTrabalho(req): pass

    def test_requisicao_fabricada_rejeitada_antes_da_conexao(self):
        req = sf.RequisicaoNormalizada('registrar_evento_manual', 'registrar_evento', chave(), '{}')
        with patch.object(banco, 'abrir_conexao', side_effect=AssertionError('abriu')):
            with self.assertRaises(sf.ParametroInvalido): sf._UnidadeTrabalho(req)

    def test_versao_bool_nao_e_aceita_como_inteiro(self):
        req = self.req()
        invalida = sf.RequisicaoNormalizada(req.servico, req.tipo_operacao, req.chave,
                                           req.requisicao_canonica, True)
        with self.assertRaises(sf.ParametroInvalido): sf._UnidadeTrabalho(invalida)

    def preparar_alvo(self):
        with self.f.conectar() as c:
            evento = self.f.evento(c)
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=(SELECT operacao_hibrida_id FROM eventos_financeiros WHERE id=?)", (evento,))
        return evento

    def test_recuperacao_dos_seis_perfis_com_fixtures_controladas(self):
        evento = self.preparar_alvo()
        # Competencia sem caixa ja e exercitada acima; demais perfis abaixo.
        imediata = self.req(10, 'registrar_operacao_imediata', **parametros_evento(),
                           data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)
        def produzir_imediata(c, req, op):
            e = self.fixture_evento(c, req, op)
            l = self.f.caixa(c, op, descricao='Manual')
            self.f.liquidar(c, e, 1000, l)
        ri = self.gravar_fixture(imediata, produzir_imediata)
        pagamento = self.req(11, 'liquidar_evento', evento_id=evento, valor_centavos=500,
            data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)
        def produzir_pagamento(c, req, op):
            l = self.f.caixa(c, op, centavos=500, descricao='Manual')
            self.f.liquidar(c, evento, 500, l)
        rp = self.gravar_fixture(pagamento, produzir_pagamento)
        estorno = self.req(12, 'estornar_liquidacao', liquidacao_id=rp.liquidacao_ids[0],
            valor_centavos=500, natureza='devolucao_real', motivo='Devolvido',
            data_estorno=date(2026, 11, 2), confirmar_datas_divergentes=True)
        def produzir_estorno(c, req, op):
            l = self.f.caixa(c, op, centavos=-500, data='2026-11-02',
                descricao=f'Estorno L#{rp.liquidacao_ids[0]} [devolucao_real]: Devolvido')
            self.f.inserir(c, 'estornos_liquidacoes', dict(liquidacao_id=rp.liquidacao_ids[0],
                lancamento_estorno_id=l, natureza='devolucao_real', motivo='Devolvido'))
        rs = self.gravar_fixture(estorno, produzir_estorno)
        reclassificacao = self.req(13, 'reclassificar_evento', evento_id=evento,
                                  categoria_nova_id=2, motivo='Corrigir grupo')
        def produzir_reclass(c, req, op):
            self.f.inserir(c, 'reclassificacoes_eventos', dict(evento_id=evento,
                operacao_hibrida_id=op, categoria_anterior_id=1, categoria_nova_id=2, motivo='Corrigir grupo'))
        rr = self.gravar_fixture(reclassificacao, produzir_reclass)
        reversao = self.req(14, 'reverter_evento', evento_id=evento,
                           data_reversao=date(2027, 1, 1), motivo='Cancelado')
        def produzir_reversao(c, req, op):
            self.f.inserir(c, 'reversoes_eventos', dict(evento_id=evento, operacao_hibrida_id=op,
                data_competencia='2027-01-01', categoria_id=2, motivo='Cancelado'))
        rv = self.gravar_fixture(reversao, produzir_reversao)
        for req, esperado in ((imediata, ri), (pagamento, rp), (estorno, rs),
                              (reclassificacao, rr), (reversao, rv)):
            self.assertEqual(self.gravar_fixture(req), esperado)
        self.assertEqual(rs.liquidacao_ids, rp.liquidacao_ids)
        self.assertEqual(rv.evento_ids, (evento,))

    def test_replay_criacao_apos_reclassificacao_e_reversao(self):
        req = self.req()
        recibo = self.gravar_fixture(req)
        with self.f.conectar() as c:
            e = recibo.evento_ids[0]
            self.f.reclassificar(c, e, 2)
            self.f.reverter(c, e)
            # Fechar as operacoes produzidas pelo fixture, nao pelo controlador.
            c.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE estado='aberta'")
        self.assertEqual(self.gravar_fixture(req), recibo)

    def test_vinculo_errado_detectado_apesar_de_valido_para_os_gatilhos(self):
        alvo, outro = self.preparar_alvo(), self.preparar_alvo()
        req = self.req(servico='liquidar_evento', evento_id=alvo, valor_centavos=100,
            data_liquidacao=date(2026, 11, 1), confirmar_datas_divergentes=False)
        foto = self.foto()
        def produzir_errado(c, req, op):
            l = self.f.caixa(c, op, centavos=100, descricao='Manual')
            self.f.liquidar(c, outro, 100, l)
        with self.assertRaises(sf.OperacaoIncompleta): self.gravar_fixture(req, produzir_errado)
        self.assertEqual(self.foto(), foto)

    def test_historico_elegivel_nao_e_convertido(self):
        foto = self.foto()
        self.gravar_fixture(self.req())
        depois = self.foto()
        for tabela in ('lancamentos', 'compras_cartao', 'parcelamentos', 'categorias'):
            self.assertEqual(foto[tabela], depois[tabela])

    def test_limpeza_quando_begin_ou_commit_falha(self):
        foto = self.foto()
        for ponto in ('begin', 'commit', 'configurar'):
            with self.subTest(ponto=ponto):
                real = banco.abrir_conexao()
                class ConexaoFalha:
                    fechada = False
                    def __getattr__(self, nome): return getattr(real, nome)
                    def execute(self, sql, *args):
                        if (ponto == 'begin' and sql == 'BEGIN IMMEDIATE') or (ponto == 'configurar' and sql.startswith('PRAGMA')):
                            raise sqlite3.OperationalError('falha injetada')
                        return real.execute(sql, *args)
                    def commit(self): raise sqlite3.OperationalError('falha commit')
                    def close(self):
                        self.fechada = True
                        real.close()
                proxy = ConexaoFalha()
                with patch.object(banco, 'abrir_conexao', return_value=proxy):
                    with self.assertRaises(sf.FalhaPersistencia): self.gravar_fixture(self.req())
                self.assertTrue(proxy.fechada)
                self.assertEqual(self.foto(), foto)

    def test_commit_efetivado_com_resposta_perdida_e_recuperavel(self):
        req = self.req()
        real = banco.abrir_conexao()
        class RespostaPerdida:
            def __getattr__(self, nome): return getattr(real, nome)
            def commit(self):
                real.commit()
                raise sqlite3.OperationalError('resposta perdida apos commit')
        with patch.object(banco, 'abrir_conexao', return_value=RespostaPerdida()):
            with self.assertRaises(sf.FalhaPersistencia): self.gravar_fixture(req)
        recibo = self.gravar_fixture(req)
        self.assertEqual(len(recibo.evento_ids), 1)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(), (1,))

    def test_erro_original_preservado_se_rollback_falha(self):
        real = banco.abrir_conexao()
        class RollbackFalha:
            def __getattr__(self, nome): return getattr(real, nome)
            def rollback(self): raise sqlite3.OperationalError('rollback injetado')
        foto = self.foto()
        with patch.object(banco, 'abrir_conexao', return_value=RollbackFalha()):
            with self.assertRaisesRegex(RuntimeError, 'original') as capturado:
                with sf._UnidadeTrabalho(self.req()) as u:
                    u._iniciar_operacao()
                    raise RuntimeError('original')
        self.assertIn('rollback', capturado.exception.__notes__[0])
        self.assertEqual(self.foto(), foto)

    def test_concorrencia_mesma_chave_igual_diferente_e_chaves_distintas(self):
        for caso in ('igual', 'conflito', 'distinta'):
            with self.subTest(caso=caso):
                destino = self.f.clone('concorrencia_'+caso)
                pronta, tentou, liberar = threading.Event(), threading.Event(), threading.Event()
                resultados, erros = {}, {}
                a = self.req(100)
                b = a if caso == 'igual' else self.req(101 if caso == 'distinta' else 100,
                    **(parametros_evento() | {'valor_centavos': 2000}))
                def executar(nome, req):
                    try:
                        if nome == 'b':
                            if not pronta.wait(10): raise AssertionError('primeira conexao nao pronta')
                            tentou.set()
                        with sf._UnidadeTrabalho(req) as u:
                            if u.anterior is None:
                                op = u._iniciar_operacao()
                                self.fixture_evento(u._conexao, req, op)
                                u._concluir()
                            if nome == 'a':
                                pronta.set()
                                if not liberar.wait(10): raise AssertionError('barreira nao liberada')
                        resultados[nome] = u.resultado
                    except BaseException as erro:
                        erros[nome] = erro
                with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                    ta = threading.Thread(target=executar, args=('a', a))
                    tb = threading.Thread(target=executar, args=('b', b))
                    ta.start(); tb.start()
                    try:
                        self.assertTrue(tentou.wait(10))
                    finally:
                        liberar.set(); ta.join(15); tb.join(15)
                    self.assertFalse(ta.is_alive() or tb.is_alive())
                    self.assertNotIn('a', erros)
                    if caso == 'conflito':
                        self.assertIsInstance(erros.get('b'), sf.ConflitoIdempotencia)
                    else:
                        self.assertFalse(erros)
                        if caso == 'igual': self.assertEqual(resultados['a'], resultados['b'])
                        else: self.assertNotEqual(resultados['a'].operacao_id, resultados['b'].operacao_id)
                    with closing(banco.abrir_conexao()) as c:
                        self.assertEqual(c.execute('SELECT count(*) FROM operacoes_hibridas').fetchone(),
                                         (2 if caso == 'distinta' else 1,))

    def test_timeout_real_classificado_como_banco_ocupado(self):
        bloqueio = banco.abrir_conexao()
        self.addCleanup(bloqueio.close)
        bloqueio.execute('BEGIN IMMEDIATE')
        real_abrir = banco.abrir_conexao
        def abrir_curta():
            c = real_abrir(); c.execute('PRAGMA busy_timeout=1'); return c
        with patch.object(banco, 'abrir_conexao', side_effect=abrir_curta):
            with self.assertRaises(sf.BancoOcupado) as capturado:
                with sf._UnidadeTrabalho(self.req()): pass
        self.assertEqual(capturado.exception.__cause__.sqlite_errorcode & 255, sqlite3.SQLITE_BUSY)
        bloqueio.rollback()


if __name__ == '__main__':
    unittest.main()
