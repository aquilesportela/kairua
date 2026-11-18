"""3.3C.2: UI e diário em SQLite temporário, sem importação de app.py."""
from contextlib import closing
from dataclasses import asdict, replace
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

import banco
import interface_eventos as ui
import intencoes_financeiras as diario
import servicos_financeiros as sf
import test_registrar_evento_manual as fixture


CHAVE = 'kairua:v1:' + str(UUID(int=500))


def parametros():
    return dict(tipo='despesa', descricao='Café mensal', categoria_id=1, valor_centavos=1250,
        data_competencia=date(2026, 11, 1), data_vencimento=date(2026, 12, 15),
        data_liquidacao=date(2026, 11, 1), confirmar_ocorrencia=True, confirmar_datas_divergentes=False)


class TestInterfaceOperacaoImediata(unittest.TestCase):
    def setUp(self):
        self.f = fixture.TestRegistrarEventoManual()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        self.store = diario.ArmazenamentoIntencoes(self.pasta)

    def criar(self, chave=CHAVE, **mudancas):
        return self.store.criar(chave=chave, servico='registrar_operacao_imediata', **(parametros() | mudancas))

    def entrada(self, **mudancas):
        campos = dict(tipo='despesa', descricao=' Cafe\u0301 mensal ', categoria='1', valor='12,50',
            competencia='01/11/2026', vencimento='15/12/2026', caixa='01/11/2026', ocorrencia='SIM') | mudancas
        respostas = list(campos[k] for k in ('tipo', 'descricao', 'categoria', 'valor',
                                            'competencia', 'vencimento', 'caixa', 'ocorrencia'))
        if campos['competencia'] != campos['caixa']:
            respostas.append(campos.get('divergencia', 'SIM'))
        valores = iter(respostas)
        return lambda _: next(valores)

    def executar_ui(self, **kwargs):
        saidas = []
        with patch.object(ui, 'uuid4', return_value=UUID(int=500)):
            ui.registrar_imediata(saida=saidas.append, armazenamento=self.store, **kwargs)
        return saidas

    def contar(self):
        with closing(banco.abrir_conexao()) as c:
            return tuple(c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                         for t in ('operacoes_hibridas', 'eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'))

    def test_despesa_ui_cria_tres_efeitos_e_recibo_correto(self):
        antes = self.contar()
        saidas = self.executar_ui(entrada=self.entrada())
        self.assertEqual(self.contar(), tuple(n+1 for n in antes))
        r = self.store.obter(CHAVE)
        self.assertEqual((r['estado'], json.loads(r['payload'])['servico']), ('confirmada', 'registrar_operacao_imediata'))
        recibo = self.store.executar(CHAVE)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT e.valor_centavos,l.valor_centavos,q.valor_centavos,'
                'e.operacao_hibrida_id,l.operacao_hibrida_id FROM liquidacoes_eventos q '
                'JOIN eventos_financeiros e ON e.id=q.evento_id JOIN lancamentos l ON l.id=q.lancamento_id').fetchone(),
                (1250, 1250, 1250, recibo.operacao_id, recibo.operacao_id))
        texto = '\n'.join(saidas)
        for esperado in ('Evento criado:', 'Caixa criado:', 'Liquidação integral criada:',
                         'R$ 12,50', 'Competência: 01/11/2026', 'Vencimento: 15/12/2026'):
            self.assertIn(esperado, texto)
        self.assertNotIn('Nenhuma movimentação de caixa', texto)

    def test_receita_ui_um_centavo(self):
        antes = self.f.foto()['lancamentos']
        self.executar_ui(entrada=self.entrada(tipo='receita', categoria='9', valor='0,01'))
        caixa = self.store.obter(CHAVE)['recibo']['lancamento_ids'][0]
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT tipo,categoria_id,valor_centavos FROM lancamentos WHERE id=?', (caixa,)).fetchall(),
                             [('receita', 9, 1)])
        depois = self.f.foto()['lancamentos']
        self.assertEqual(len(depois), len(antes)+1)
        self.assertTrue(all(linha in depois for linha in antes))

    def test_limite_int64_na_ui_sem_float(self):
        antes = self.f.foto()['lancamentos']
        self.executar_ui(entrada=self.entrada(valor='92.233.720.368.547.758,07'))
        caixa = self.store.obter(CHAVE)['recibo']['lancamento_ids'][0]
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT valor_centavos,typeof(valor_centavos) FROM lancamentos WHERE id=?', (caixa,)).fetchall(),
                             [(sf.MAX_CENTAVOS, 'integer')])
        depois = self.f.foto()['lancamentos']
        self.assertEqual(len(depois), len(antes)+1)
        self.assertTrue(all(linha in depois for linha in antes))

    def test_resumo_antes_da_confirmacao_e_sem_transacao_aberta(self):
        saidas = []
        respostas = self.entrada()
        def entrada(pergunta):
            if 'ocorrência econômica' in pergunta:
                texto = '\n'.join(saidas)
                for esperado in ('R$ 12,50', 'Tipo: despesa', 'Categoria selecionada:',
                                 'Competência: 01/11/2026', 'Vencimento: 15/12/2026',
                                 'Liquidação / caixa: 01/11/2026', 'um lançamento de caixa'):
                    self.assertIn(esperado, texto)
                self.assertEqual(list(self.pasta.glob('*.json')), [])
                # Uma conexão independente consegue adquirir a escrita durante
                # o prompt: a coleta não mantém transação financeira aberta.
                with closing(banco.abrir_conexao()) as c:
                    c.execute('BEGIN IMMEDIATE')
                    c.rollback()
            return respostas(pergunta)
        ui.registrar_imediata(entrada=entrada, saida=saidas.append, armazenamento=self.store)
        self.assertTrue(any('Operação confirmada:' in s for s in saidas))

    def test_datas_independentes_com_confirmacao_persistida(self):
        self.executar_ui(entrada=self.entrada(caixa='02/11/2026', divergencia='SIM'))
        p = diario.parametros_da_intencao(self.store.obter(CHAVE))
        self.assertEqual((p['data_competencia'], p['data_vencimento'], p['data_liquidacao'],
                          p['confirmar_datas_divergentes']),
                         (date(2026, 11, 1), date(2026, 12, 15), date(2026, 11, 2), True))

    def test_cancelamento_e_confirmacao_divergente_ausente_nao_persistem(self):
        for alteracoes in ({'ocorrencia': 'NÃO'}, {'caixa': '02/11/2026', 'divergencia': 'não'}):
            with self.subTest(alteracoes=alteracoes), patch.object(sf, 'registrar_operacao_imediata') as servico:
                antes = self.f.foto()
                self.executar_ui(entrada=self.entrada(**alteracoes))
                servico.assert_not_called()
                self.assertEqual(list(self.pasta.glob('*.json')), [])
                self.assertEqual(self.f.foto(), antes)

    def test_entradas_invalidas_antes_de_intencao(self):
        for alteracoes in ({'valor': '0'}, {'valor': '1,234'}, {'valor': '92233720368547758,08'},
                           {'tipo': 'outro'}, {'descricao': '   '}, {'competencia': '29/02/2025'},
                           {'categoria': '9'}):
            with self.subTest(alteracoes=alteracoes), patch.object(sf, 'registrar_operacao_imediata') as servico:
                self.executar_ui(entrada=self.entrada(**alteracoes))
                servico.assert_not_called()
                self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_categoria_revalidada_pelo_motor(self):
        self.criar(tipo='receita', categoria_id=1)
        antes = self.f.foto()
        with self.assertRaises(sf.CategoriaIncompativel):
            self.store.executar(CHAVE)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'rejeitada')
        self.assertEqual(self.f.foto(), antes)

    def test_persistencia_canonica_antes_do_servico(self):
        def servico(**p):
            r = diario.ArmazenamentoIntencoes(self.pasta).obter(CHAVE)
            self.assertEqual(r['estado'], 'incerta')
            self.assertEqual(diario.parametros_da_intencao(r), parametros())
            return sf.registrar_operacao_imediata(**p)
        self.executar_ui(entrada=self.entrada(), servico=servico)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'confirmada')

    def test_falha_diario_impede_chamada_financeira(self):
        antes = self.f.foto()
        with patch('intencoes_financeiras.os.replace', side_effect=OSError('Disco')), \
                patch.object(sf, 'registrar_operacao_imediata') as servico:
            saidas = self.executar_ui(entrada=self.entrada())
            servico.assert_not_called()
        self.assertFalse(any('Operação confirmada:' in s for s in saidas))
        self.assertEqual(self.f.foto(), antes)

    def test_falha_ao_marcar_incerta_nao_executa(self):
        self.criar()
        antes = self.store.obter(CHAVE)
        with patch.object(self.store, '_gravar', side_effect=OSError('Disco')), \
                patch.object(sf, 'registrar_operacao_imediata') as servico:
            with self.assertRaises(OSError):
                self.store.executar(CHAVE)
            servico.assert_not_called()
        self.assertEqual(self.store.obter(CHAVE), antes)

    def test_rollback_real_apos_cada_insert_na_integracao(self):
        original = sqlite3.connect
        for numero, tabela in enumerate(('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos')):
            antes = self.f.foto()
            class Falhar(sqlite3.Connection):
                def execute(self, sql, *args, **kwargs):
                    resultado = super().execute(sql, *args, **kwargs)
                    if sql.lstrip().startswith('INSERT INTO ' + tabela):
                        raise sqlite3.OperationalError('Falha após INSERT')
                    return resultado
            def abrir():
                return original(banco.obter_caminho_banco(), factory=Falhar)
            chave = 'kairua:v1:' + str(UUID(int=600+numero))
            self.criar(chave=chave)
            with self.subTest(tabela=tabela), patch.object(banco, 'abrir_conexao', abrir), \
                    self.assertRaises(sf.FalhaPersistencia):
                self.store.executar(chave)
            self.assertEqual(self.f.foto(), antes)
            self.assertEqual(self.store.obter(chave)['estado'], 'incerta')

    def test_perda_de_resposta_recuperada_pelo_menu_generico(self):
        def perder(**p):
            sf.registrar_operacao_imediata(**p)
            raise TimeoutError('Após commit')
        saidas = self.executar_ui(entrada=self.entrada(), servico=perder)
        self.assertFalse(any('Operação confirmada:' in s for s in saidas))
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')
        antes = self.f.foto()
        entradas = iter(['3', CHAVE, 'SIM', '0'])
        saidas = []
        ui.menu_eventos_financeiros(entrada=lambda _: next(entradas), saida=saidas.append, armazenamento=self.store)
        self.assertEqual(self.f.foto(), antes)
        self.assertTrue(any('Caixa criado:' in s for s in saidas))
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'confirmada')

    def test_reinicio_real_apos_commit_recupera_sem_duplicar(self):
        self.criar()
        codigo = ('import os,sys\nimport servicos_financeiros as sf\n'
            'from intencoes_financeiras import ArmazenamentoIntencoes\n'
            'def perder(**p):\n sf.registrar_operacao_imediata(**p)\n os._exit(23)\n'
            'ArmazenamentoIntencoes(sys.argv[1]).executar(sys.argv[2],servico=perder)\n')
        r = subprocess.run([sys.executable, '-B', '-c', codigo, str(self.pasta), CHAVE], timeout=20)
        self.assertEqual(r.returncode, 23)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')
        antes = self.f.foto()
        recibo = diario.ArmazenamentoIntencoes(self.pasta).executar(CHAVE)
        self.assertEqual(recibo.tipo_operacao, 'registrar_imediata')
        self.assertEqual(self.f.foto(), antes)

    def test_replay_confirmado_sem_gravar_diario_ou_banco(self):
        self.criar()
        original = self.store.executar(CHAVE)
        antes = self.f.foto()
        with patch.object(self.store, '_gravar', side_effect=AssertionError('Replay escreveu')):
            self.assertEqual(self.store.executar(CHAVE), original)
        self.assertEqual(self.f.foto(), antes)

    def test_conflito_payload_ou_tipo_nao_sobrescreve_intencao(self):
        original = self.criar()
        with self.assertRaises(sf.ConflitoIdempotencia):
            self.criar(valor_centavos=1251)
        manual = {k:v for k,v in parametros().items() if k not in ('data_liquidacao', 'confirmar_datas_divergentes')}
        with self.assertRaises(sf.ConflitoIdempotencia):
            self.store.criar(chave=CHAVE, **manual)
        self.assertEqual(self.store.obter(CHAVE), original)

    def test_conflito_com_operacao_preexistente_no_banco(self):
        manual = {k:v for k,v in parametros().items() if k not in ('data_liquidacao', 'confirmar_datas_divergentes')}
        sf.registrar_evento_manual(chave=CHAVE, **manual)
        self.criar()
        antes = self.f.foto()
        with self.assertRaises(sf.ConflitoIdempotencia):
            self.store.executar(CHAVE)
        self.assertEqual(self.f.foto(), antes)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')

    def test_catalogo_fechado_recusa_servicos_futuros_e_nomes_arbitrarios(self):
        for nome in ('liquidar_evento', 'estornar_liquidacao', 'reverter_evento', 'reclassificar_evento', '__import__'):
            with self.subTest(nome=nome), self.assertRaises(diario.ErroIntencao):
                self.store.criar(chave=CHAVE, servico=nome, **parametros())
        self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_nome_adulterado_no_json_nao_executa(self):
        self.criar()
        caminho = self.pasta / (CHAVE[10:] + '.json')
        r = json.loads(caminho.read_text(encoding='utf-8'))
        p = json.loads(r['payload'])
        p['servico'] = 'liquidar_evento'
        r['payload'] = json.dumps(p)
        caminho.write_text(json.dumps(r), encoding='utf-8')
        antes = caminho.read_bytes()
        with patch.object(sf, 'registrar_operacao_imediata') as servico, self.assertRaises(diario.ErroIntencao):
            self.store.executar(CHAVE)
        servico.assert_not_called()
        self.assertEqual(caminho.read_bytes(), antes)

    def test_cardinalidade_tipo_e_ids_do_recibo_conferidos(self):
        valido = sf.ResultadoOperacao(1, CHAVE, 'registrar_imediata', evento_ids=(1,),
                                     lancamento_ids=(1,), liquidacao_ids=(1,))
        casos = [replace(valido, liquidacao_ids=()), replace(valido, evento_ids=(1,2)),
            replace(valido, lancamento_ids=(True,)), replace(valido, estorno_ids=(1,)),
            replace(valido, tipo_operacao='registrar_evento'), replace(valido, operacao_id=0)]
        self.criar()
        for r in casos:
            with self.subTest(recibo=r), self.assertRaises(diario.ErroIntencao):
                self.store.executar(CHAVE, servico=lambda **p: r)
            self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')

    def test_intencao_confirmada_nao_e_rebaixada_em_falha_posterior(self):
        self.criar()
        recibo = self.store.executar(CHAVE)
        antes = self.store.obter(CHAVE)
        with self.assertRaises(TimeoutError):
            self.store.executar(CHAVE, servico=lambda **p: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(self.store.obter(CHAVE), antes)
        self.assertEqual(self.store.executar(CHAVE), recibo)

    def test_recuperacao_preserva_datas_e_categoria_original_sem_join_corrente(self):
        self.criar()
        r = self.store.executar(CHAVE)
        sf.reclassificar_evento(chave='kairua:v1:'+str(UUID(int=501)), evento_id=r.evento_ids[0],
                               categoria_nova_id=2, motivo='Posterior')
        with closing(banco.abrir_conexao()) as c:
            c.execute("UPDATE categorias SET nome='Nome posterior' WHERE id=1")
            c.commit()
        entradas = iter(['3', CHAVE, 'SIM', '0'])
        saidas = []
        ui.menu_eventos_financeiros(entrada=lambda _: next(entradas), saida=saidas.append, armazenamento=self.store)
        texto = '\n'.join(saidas)
        self.assertIn('Categoria original (ID): 1', texto)
        self.assertNotIn('Nome posterior', texto)
        self.assertIn('Liquidação / caixa: 01/11/2026', texto)

    def test_intencao_antiga_v1_sem_migracao_e_sem_reescrita(self):
        manual = {k:v for k,v in parametros().items() if k not in ('data_liquidacao', 'confirmar_datas_divergentes')}
        r = sf.registrar_evento_manual(chave=CHAVE, **manual)
        payload = ('{"parametros":{"categoria_id":1,"confirmar_ocorrencia":true,"data_competencia":"2026-11-01",'
            '"data_vencimento":"2026-12-15","descricao":"Café mensal","tipo":"despesa","valor_centavos":1250},'
            '"servico":"registrar_evento_manual","tipo_operacao":"registrar_evento","versao_contrato":1}')
        antigo = dict(versao=1, chave=CHAVE, destino=diario.destino_configurado(), payload=payload,
                      estado='confirmada', recibo=asdict(r), erro=None)
        caminho = self.pasta / (CHAVE[10:] + '.json')
        caminho.write_text(json.dumps(antigo, ensure_ascii=False, indent=4), encoding='utf-8')
        antes = caminho.read_bytes()
        with patch.object(banco, 'aplicar_migracoes', side_effect=AssertionError('Migrou')), \
                patch.object(sf, 'registrar_operacao_imediata', side_effect=AssertionError('Serviço errado')):
            self.assertEqual(self.store.executar(CHAVE), r)
        self.assertEqual(caminho.read_bytes(), antes)

    def test_menu_5_encaminha_exclusivamente_para_imediata(self):
        entradas = iter(['5', '0'])
        with patch.object(ui, 'registrar_imediata') as imediata, patch.object(ui, 'registrar_manual') as manual:
            ui.menu_eventos_financeiros(entrada=lambda _: next(entradas), saida=lambda _: None, armazenamento=self.store)
        imediata.assert_called_once()
        manual.assert_not_called()

    def test_esquema_indisponivel_nao_migra(self):
        destino = self.pasta / 'sem_esquema.db'
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), \
                patch.object(banco, 'aplicar_migracoes', side_effect=AssertionError('Migração')):
            store = diario.ArmazenamentoIntencoes(self.pasta / 'outro')
            saidas = []
            ui.registrar_imediata(entrada=self.entrada(), saida=saidas.append, armazenamento=store,
                                  categorias=lambda _: [(1, 'Categoria')])
        self.assertTrue(any('Esquema híbrido indisponível' in s for s in saidas))
        self.assertFalse(any('Operação confirmada:' in s for s in saidas))

    def test_processos_disputam_lock_da_intencao_e_recuperam_mesmos_ids(self):
        self.criar()
        codigo_a = ('import sys,json\nfrom dataclasses import asdict\nimport servicos_financeiros as sf\n'
            'from intencoes_financeiras import ArmazenamentoIntencoes\n'
            'def esperar(**p):\n print("DENTRO",flush=True)\n sys.stdin.readline()\n return sf.registrar_operacao_imediata(**p)\n'
            'r=ArmazenamentoIntencoes(sys.argv[1]).executar(sys.argv[2],servico=esperar)\n'
            'print(json.dumps(asdict(r)),flush=True)\n')
        codigo_b = ('import os,sys,json\nfrom dataclasses import asdict\nfrom pathlib import Path\n'
            'from intencoes_financeiras import ArmazenamentoIntencoes\n'
            'with (Path(sys.argv[1])/(".exec-"+sys.argv[2][10:]+".lock")).open("a+b") as f:\n'
            ' try:\n'
            '  if os.name=="nt":\n'
            '   import msvcrt\n'
            '   msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)\n'
            '  else:\n'
            '   import fcntl\n'
            '   fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
            ' except OSError: print("BLOQUEADO",flush=True)\n'
            ' else: raise AssertionError("Lock nao disputado")\n'
            'r=ArmazenamentoIntencoes(sys.argv[1]).executar(sys.argv[2])\n'
            'print(json.dumps(asdict(r)),flush=True)\n')
        antes = self.contar()
        with subprocess.Popen([sys.executable, '-B', '-c', codigo_a, str(self.pasta), CHAVE],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as a:
            try:
                self.assertEqual(a.stdout.readline().strip(), 'DENTRO')
                with subprocess.Popen([sys.executable, '-B', '-c', codigo_b, str(self.pasta), CHAVE],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as b:
                    try:
                        self.assertEqual(b.stdout.readline().strip(), 'BLOQUEADO')
                        a.stdin.write('executar\n')
                        a.stdin.flush()
                        ra, ea = a.communicate(timeout=20)
                        rb, eb = b.communicate(timeout=20)
                        self.assertEqual(a.returncode, 0, ea)
                        self.assertEqual(b.returncode, 0, eb)
                        self.assertEqual(json.loads(ra), json.loads(rb))
                    finally:
                        if b.poll() is None:
                            b.kill()
            finally:
                if a.poll() is None:
                    a.kill()
        self.assertEqual(self.contar(), tuple(n+1 for n in antes))
