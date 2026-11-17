"""3.3B: UI isolada; nunca importa app e nunca utiliza o SQLite real."""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import banco
import interface_eventos as ui
import intencoes_financeiras as diario
import servicos_financeiros as sf
import test_registrar_evento_manual as fixture


def parametros():
    return {k: v for k, v in fixture.parametros().items() if k != 'chave'}


CHAVE = fixture.parametros()['chave']


class TestParserBrasileiro(unittest.TestCase):
    def test_formatos_exatos_e_extremos(self):
        for texto, esperado in [('0,01', 1), ('1.234,56', 123456), ('1234,56', 123456),
                ('R$ 1.234,56', 123456), ('1234', 123400), ('1.234.567,89', 123456789),
                ('1,2', 120), ('92.233.720.368.547.758,07', sf.MAX_CENTAVOS),
                ('92233720368547758,07', sf.MAX_CENTAVOS)]:
            with self.subTest(texto=texto):
                self.assertEqual(ui.interpretar_valor_brasileiro(texto), esperado)

    def test_formatos_invalidos_sem_arredondamento(self):
        for texto in ['1.234,567', '1,234', '12.34,56', '1e3', 'NaN', 'Infinity',
                'inf', '1.23', '1,', ',01', '-1', '+1', '0', '0,00', '1 234,56',
                'R$1,00', '1.234.56', '01.234,56', 'R$  1,00', '', True, 1.0,
                '92233720368547758,08', '9' * 4097]:
            with self.subTest(texto=str(texto)[:40]), self.assertRaises(sf.ValorInvalido):
                ui.interpretar_valor_brasileiro(texto)

    def test_datas_calendario_e_formato(self):
        self.assertEqual(ui.interpretar_data_brasileira('29/02/2024'), date(2024, 2, 29))
        self.assertEqual(ui.interpretar_data_brasileira('31/12/9999'), date.max)
        for valor in ['29/02/2025', '31/04/2026', '2026-11-01', '1/1/2026', '01/01/0000']:
            with self.subTest(valor=valor), self.assertRaises(sf.DataInvalida):
                ui.interpretar_data_brasileira(valor)

    def test_import_sem_conexao_ou_migracao_em_outro_processo(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta) / 'nao_criar.db'
            codigo = ('from unittest.mock import patch\nimport banco,sqlite3\n'
                'with patch.object(sqlite3,"connect",side_effect=AssertionError("conexao")), '
                'patch.object(banco,"aplicar_migracoes",side_effect=AssertionError("migracao")):\n'
                ' import interface_eventos,intencoes_financeiras\n')
            subprocess.run([sys.executable, '-B', '-c', codigo], check=True,
                           env=os.environ | {'KAIRUA_DB_PATH': str(destino)})
            self.assertFalse(destino.exists())

    def test_integracao_minima_menu_sem_importar_app(self):
        fonte = Path('app.py').read_text(encoding='utf-8')
        atual = ast.parse(fonte)
        funcoes = {n.name: n for n in atual.body if isinstance(n, ast.FunctionDef)}
        # Executa apenas a AST do menu, com stubs, sem inicialização de app.py.
        chamadas = []
        escolhas = iter(['1', '2', '3', '4', '5', '6', '0'])
        class Prompt:
            @staticmethod
            def ask(*args):
                return next(escolhas)
        escopo = dict(Prompt=Prompt, exibir_menu=lambda *a: None,
                      menu_eventos_financeiros=lambda: chamadas.append('eventos'),
                      console=type('Console', (), {'print': lambda *a: None})())
        for nome in ('lancamentos', 'resumos', 'relatorios', 'categorias', 'cartoes'):
            escopo['menu_' + nome] = lambda nome=nome: chamadas.append(nome)
        exec(compile(ast.Module(body=[funcoes['menu_principal']], type_ignores=[]), '<menu>', 'exec'), escopo)
        escopo['menu_principal']()
        self.assertEqual(chamadas, ['lancamentos', 'resumos', 'relatorios', 'categorias', 'cartoes', 'eventos'])


class TestIntencoesEInterface(unittest.TestCase):
    def setUp(self):
        self.f = fixture.TestRegistrarEventoManual()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        self.store = diario.ArmazenamentoIntencoes(self.pasta)

    def criar(self, chave=CHAVE, **mudancas):
        return self.store.criar(chave=chave, **(parametros() | mudancas))

    def entrada(self, *fim):
        valores = iter(['despesa', 'Cafe\u0301 mensal', '1', '1.234,56',
                        '01/11/2026', '15/12/2026', *(fim or ['SIM'])])
        return lambda _: next(valores)

    def contar(self):
        with closing(banco.abrir_conexao()) as c:
            return tuple(c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in
                ('operacoes_hibridas', 'eventos_financeiros', 'lancamentos', 'liquidacoes_eventos'))

    def test_cadastro_ui_confirmado_um_evento_sem_caixa(self):
        antes = self.contar()
        saida = []
        ui.registrar_manual(entrada=self.entrada(), saida=saida.append, armazenamento=self.store)
        self.assertEqual(self.contar(), (antes[0]+1, antes[1]+1, antes[2], antes[3]))
        arquivos = list(self.pasta.glob('*.json'))
        self.assertEqual(len(arquivos), 1)
        r = self.store.obter('kairua:v1:' + arquivos[0].stem)
        self.assertEqual(r['estado'], 'confirmada')
        self.assertTrue(any('Operação confirmada' in s for s in saida))
        self.assertEqual(json.loads(r['payload'])['parametros']['valor_centavos'], 123456)

    def test_receita_ui_com_datas_extremas(self):
        entradas = iter(['receita', 'Salário', '9', '0,01', '01/01/0001', '31/12/9999', 'SIM'])
        ui.registrar_manual(entrada=lambda _: next(entradas), saida=lambda _: None,
                           armazenamento=self.store)
        with closing(banco.abrir_conexao()) as c:
            self.assertEqual(c.execute('SELECT tipo,valor_centavos,data_competencia,data_vencimento '
                                      'FROM eventos_financeiros').fetchall(),
                             [('receita', 1, '0001-01-01', '9999-12-31')])

    def test_descricao_vazia_e_interrupcao_antes_da_confirmacao(self):
        for sequencia in (['despesa', '   '], ['despesa']):
            entradas = iter(sequencia)
            def entrada(_):
                try:
                    return next(entradas)
                except StopIteration:
                    raise EOFError
            with patch.object(sf, 'registrar_evento_manual') as servico:
                ui.registrar_manual(entrada=entrada, saida=lambda _: None, armazenamento=self.store)
                servico.assert_not_called()
                self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_localizacao_padrao_separa_bancos_sem_criar_arquivos(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.pasta)}):
            primeiro = diario.diretorio_padrao()
            self.assertEqual(primeiro.parent, self.pasta / 'Kairua' / 'intencoes')
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(self.pasta / 'outro.db')}):
                self.assertNotEqual(diario.diretorio_padrao(), primeiro)
            self.assertFalse((self.pasta / 'Kairua').exists())

    def test_cancelamento_nao_persiste_nem_chama_servico(self):
        for resposta in ('não', 'sim', ''):
            with self.subTest(resposta=resposta), patch.object(sf, 'registrar_evento_manual') as servico:
                ui.registrar_manual(entrada=self.entrada(resposta), saida=lambda _: None,
                                   armazenamento=self.store)
                servico.assert_not_called()
                self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_entrada_invalida_antes_de_persistir(self):
        for valor in ('0', '1e3', '1,234'):
            entradas = iter(['despesa', 'Conta', '1', valor])
            with self.subTest(valor=valor), patch.object(sf, 'registrar_evento_manual') as servico:
                ui.registrar_manual(entrada=lambda _: next(entradas), saida=lambda _: None,
                                   armazenamento=self.store, categorias=lambda _: [(1, 'Teste')])
                servico.assert_not_called()
                self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_categoria_fora_da_lista_nao_persiste(self):
        entradas = iter(['receita', 'Salário', '1'])
        with patch.object(sf, 'registrar_evento_manual') as servico:
            ui.registrar_manual(entrada=lambda _: next(entradas), saida=lambda _: None,
                armazenamento=self.store, categorias=lambda _: [(9, 'Salário')])
            servico.assert_not_called()
        self.assertEqual(list(self.pasta.glob('*.json')), [])

    def test_categoria_incompativel_rejeitada_pelo_motor(self):
        self.criar(tipo='receita', categoria_id=1)
        antes = self.contar()
        with self.assertRaises(sf.CategoriaIncompativel):
            self.store.executar(CHAVE)
        self.assertEqual(self.contar(), antes)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'rejeitada')

    def test_intencao_persistida_antes_da_chamada(self):
        self.criar()
        def servico(**p):
            outro = diario.ArmazenamentoIntencoes(self.pasta).obter(CHAVE)
            self.assertEqual(outro['estado'], 'incerta')
            self.assertEqual(diario.parametros_da_intencao(outro), parametros() | {'descricao': 'Café  mensal'})
            return sf.registrar_evento_manual(**p)
        self.store.executar(CHAVE, servico=servico)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'confirmada')

    def test_replay_mesma_chave_sem_duplicidade(self):
        self.criar()
        r = self.store.executar(CHAVE)
        antes = self.contar()
        self.assertEqual(self.store.executar(CHAVE), r)
        self.assertEqual(self.contar(), antes)

    def test_resposta_perdida_apos_commit_reinicio_e_recuperacao(self):
        self.criar()
        resultados = []
        def perder(**p):
            resultados.append(sf.registrar_evento_manual(**p))
            raise TimeoutError('Resposta perdida após commit')
        with self.assertRaises(TimeoutError):
            self.store.executar(CHAVE, servico=perder)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')
        antes = self.contar()
        novo = diario.ArmazenamentoIntencoes(self.pasta)
        self.assertEqual(novo.executar(CHAVE), resultados[0])
        self.assertEqual(self.contar(), antes)
        self.assertEqual(novo.listar_pendentes(), [])

    def test_interrupcao_de_processo_preserva_intencao(self):
        self.criar()
        codigo = ('import os,sys\nfrom intencoes_financeiras import ArmazenamentoIntencoes\n'
                  'def parar(**p): os._exit(23)\n'
                  'ArmazenamentoIntencoes(sys.argv[1]).executar(sys.argv[2],servico=parar)\n')
        p = subprocess.run([sys.executable, '-B', '-c', codigo, str(self.pasta), CHAVE])
        self.assertEqual(p.returncode, 23)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')
        self.store.executar(CHAVE)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'confirmada')

    def test_ui_nao_afirma_sucesso_apos_resposta_perdida(self):
        saida = []
        def perder(**p):
            sf.registrar_evento_manual(**p)
            raise TimeoutError('Após commit')
        ui.registrar_manual(entrada=self.entrada(), saida=saida.append, armazenamento=self.store, servico=perder)
        self.assertFalse(any('Operação confirmada:' in s for s in saida))
        self.assertEqual(len(self.store.listar_pendentes()), 1)
        self.assertEqual(self.store.listar_pendentes()[0]['estado'], 'incerta')

    def test_rejeicao_na_recuperacao_nao_descarta_incerteza(self):
        self.criar()
        with self.assertRaises(TimeoutError):
            self.store.executar(CHAVE, servico=lambda **p: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(sf.EsquemaIncompativel):
            self.store.executar(CHAVE, servico=lambda **p: (_ for _ in ()).throw(sf.EsquemaIncompativel()))
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')

    def test_mesma_chave_payload_divergente_nao_sobrescreve(self):
        original = self.criar()
        with self.assertRaises(sf.ConflitoIdempotencia):
            self.criar(valor_centavos=1)
        self.assertEqual(self.store.obter(CHAVE), original)

    def test_json_corrompido_nao_e_descartado(self):
        self.criar()
        caminho = self.pasta / (CHAVE[10:] + '.json')
        caminho.write_bytes(b'{incompleto')
        with self.assertRaises(diario.ErroIntencao):
            self.store.listar_pendentes()
        self.assertEqual(caminho.read_bytes(), b'{incompleto')

    def test_payload_adulterado_e_destino_diferente_rejeitados(self):
        self.criar()
        caminho = self.pasta / (CHAVE[10:] + '.json')
        original = caminho.read_bytes()
        r = json.loads(original)
        r['payload'] = r['payload'].replace('registrar_evento_manual', 'registrar_operacao_imediata')
        caminho.write_text(json.dumps(r), encoding='utf-8')
        with self.assertRaises(diario.ErroIntencao):
            self.store.obter(CHAVE)
        caminho.write_bytes(original)
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(self.pasta / 'outro.db')}):
            with self.assertRaises(diario.ErroIntencao):
                diario.ArmazenamentoIntencoes(self.pasta).obter(CHAVE)
            with self.assertRaises(diario.ErroIntencao):
                self.store.executar(CHAVE)
        self.assertFalse((self.pasta / 'outro.db').exists())

    def test_falha_escrita_inicial_impede_servico(self):
        with patch('intencoes_financeiras.os.fsync', side_effect=OSError('disco')), \
                patch.object(sf, 'registrar_evento_manual') as servico:
            ui.registrar_manual(entrada=self.entrada(), saida=lambda _: None, armazenamento=self.store)
            servico.assert_not_called()
        self.assertEqual(list(self.pasta.glob('*.json')), [])
        self.assertEqual(list(self.pasta.glob('*.tmp')), [])

    def test_falha_replace_preserva_arquivo_anterior(self):
        self.criar()
        caminho = self.pasta / (CHAVE[10:] + '.json')
        antes = caminho.read_bytes()
        with patch('intencoes_financeiras.os.replace', side_effect=OSError('replace')):
            with self.assertRaises(OSError):
                self.store.executar(CHAVE)
        self.assertEqual(caminho.read_bytes(), antes)
        self.assertEqual(list(self.pasta.glob('*.tmp')), [])

    def test_falha_gravacao_recibo_apos_commit_recuperavel(self):
        self.criar()
        gravar = self.store._gravar
        def falhar(r):
            if r['estado'] == 'confirmada':
                raise OSError('Falha após commit')
            gravar(r)
        with patch.object(self.store, '_gravar', side_effect=falhar), self.assertRaises(OSError):
            self.store.executar(CHAVE)
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')
        antes = self.contar()
        self.store.executar(CHAVE)
        self.assertEqual(self.contar(), antes)

    def test_duas_sessoes_mesma_chave_convergem(self):
        self.criar()
        inicio = threading.Barrier(2)
        def executar():
            inicio.wait(timeout=10)
            return diario.ArmazenamentoIntencoes(self.pasta).executar(CHAVE)
        antes = self.contar()
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(executar), pool.submit(executar)
            self.assertEqual(a.result(timeout=20), b.result(timeout=20))
        self.assertEqual(self.contar(), (antes[0]+1, antes[1]+1, antes[2], antes[3]))

    def test_concorrencia_criacao_chaves_distintas_e_colisao(self):
        def criar(i):
            chave = 'kairua:v1:' + str(fixture.UUID(int=i))
            return diario.ArmazenamentoIntencoes(self.pasta).criar(chave=chave, **parametros())
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(criar, range(1, 9)))
        self.assertEqual(len(self.store.listar_pendentes()), 8)
        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(criar, [1, 1]))
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(len(list(self.pasta.glob('*.json'))), 8)

    def test_colisao_concorrente_payload_diferente_preserva_vencedor(self):
        inicio = threading.Barrier(2)
        def criar(valor):
            inicio.wait(timeout=10)
            try:
                diario.ArmazenamentoIntencoes(self.pasta).criar(chave=CHAVE,
                    **(parametros() | {'valor_centavos': valor}))
                return valor
            except sf.ConflitoIdempotencia:
                return None
        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(criar, [1, 2]))
        self.assertEqual(resultados.count(None), 1)
        vencedor = next(v for v in resultados if v is not None)
        self.assertEqual(diario.parametros_da_intencao(self.store.obter(CHAVE))['valor_centavos'], vencedor)

    def test_lock_real_entre_processos_independentes(self):
        # O segundo processo tenta um lock NÃO bloqueante e comprova a
        # contenção; só então o pai libera o primeiro. Sem sleeps como prova.
        codigo_a = ('import sys\nfrom intencoes_financeiras import ArmazenamentoIntencoes\n'
            's=ArmazenamentoIntencoes(sys.argv[1])\n'
            'with s._bloqueio(".diario.lock"):\n'
            ' print("LOCK",flush=True)\n'
            ' sys.stdin.readline()\n')
        codigo_b = ('import sys,os\nfrom intencoes_financeiras import ArmazenamentoIntencoes\n'
            's=ArmazenamentoIntencoes(sys.argv[1])\n'
            'with (s.diretorio/".diario.lock").open("a+b") as f:\n'
            ' try:\n'
            '  if os.name=="nt":\n'
            '   import msvcrt\n'
            '   msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)\n'
            '  else:\n'
            '   import fcntl\n'
            '   fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
            ' except OSError: print("BLOQUEADO",flush=True)\n'
            ' else: raise AssertionError("lock nao disputado")\n'
            's.listar_pendentes()\n'
            'print("LIBERADO",flush=True)\n')
        with subprocess.Popen([sys.executable, '-B', '-c', codigo_a, str(self.pasta)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as a:
            try:
                self.assertEqual(a.stdout.readline().strip(), 'LOCK')
                with subprocess.Popen([sys.executable, '-B', '-c', codigo_b, str(self.pasta)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as b:
                    try:
                        self.assertEqual(b.stdout.readline().strip(), 'BLOQUEADO')
                        a.stdin.write('liberar\n')
                        a.stdin.flush()
                        saida, erros = b.communicate(timeout=15)
                        self.assertEqual(b.returncode, 0, erros)
                        self.assertEqual(saida.strip(), 'LIBERADO')
                    finally:
                        if b.poll() is None:
                            b.kill()
            finally:
                if a.poll() is None:
                    a.stdin.close()
                a.wait(timeout=15)

    def test_recibo_faltante_ou_com_caixa_nao_confirma(self):
        self.criar()
        for r in [None, sf.ResultadoOperacao(1, CHAVE, 'registrar_evento', evento_ids=(1,), lancamento_ids=(1,))]:
            with self.subTest(recibo=r), self.assertRaises(diario.ErroIntencao):
                self.store.executar(CHAVE, servico=lambda **p: r)
            self.assertEqual(self.store.obter(CHAVE)['estado'], 'incerta')

    def test_menu_consulta_e_recupera_persistido(self):
        self.criar()
        entradas = iter(['2', '3', CHAVE, 'SIM', '0'])
        saida = []
        ui.menu_eventos_financeiros(entrada=lambda _: next(entradas), saida=saida.append,
                                   armazenamento=self.store)
        self.assertTrue(any(CHAVE + ' — pendente' in s for s in saida))
        self.assertTrue(any('Operação confirmada:' in s for s in saida))
        self.assertEqual(self.store.obter(CHAVE)['estado'], 'confirmada')

    def test_esquema_indisponivel_sem_migracao(self):
        destino = self.pasta / 'vazio.db'
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}), \
                patch.object(banco, 'aplicar_migracoes', side_effect=AssertionError('migração')):
            store = diario.ArmazenamentoIntencoes(self.pasta / 'vazio')
            saida = []
            ui.registrar_manual(entrada=self.entrada(), saida=saida.append, armazenamento=store,
                               categorias=lambda _: [(1, 'Teste')])
            self.assertTrue(any('Esquema híbrido indisponível' in s for s in saida))
            self.assertFalse(any('Operação confirmada:' in s for s in saida))
            with closing(banco.abrir_conexao()) as c:
                self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
