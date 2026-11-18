"""Extrai somente handlers por AST; não importa a inicialização de app.py."""
import ast
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch

import banco
import interface_eventos as ui
import servicos_financeiros as sf
import utils
import test_interface_operacao_imediata as imediata


class TestProtecaoLegadaInterface(unittest.TestCase):
    def setUp(self):
        self.h = imediata.TestInterfaceOperacaoImediata()
        self.addCleanup(self.h.doCleanups)
        self.h.setUp()

    def legado(self):
        with closing(banco.abrir_conexao()) as c:
            r = c.execute("INSERT INTO lancamentos(data,descricao,tipo,categoria,categoria_id,valor) "
                          "SELECT '2020-01-01','Legado','despesa',nome,id,12 FROM categorias WHERE id=1")
            c.commit()
            return r.lastrowid

    def handler(self, nome, entradas, **mudancas):
        codigo = ast.parse(Path('app.py').read_text(encoding='utf-8'))
        funcao = next(n for n in codigo.body if isinstance(n, ast.FunctionDef) and n.name == nome)
        saidas = []
        respostas = iter(entradas)
        escopo = dict(sqlite3=sqlite3, buscar_lancamento=banco.buscar_lancamento,
            permitir_alteracao_legada=ui.permitir_alteracao_legada,
            atualizar_lancamento=Mock(wraps=banco.atualizar_lancamento),
            excluir_lancamento=Mock(wraps=banco.excluir_lancamento),
            input=lambda _: next(respostas), print=lambda *args, **kwargs: saidas.append(' '.join(map(str,args))),
            mostrar_detalhes_lancamento=lambda r: None,
            formatar_data=utils.formatar_data, formatar_moeda=utils.formatar_moeda)
        escopo.update(mudancas)
        exec(compile(ast.Module(body=[funcao], type_ignores=[]), '<handler-legado>', 'exec'), escopo)
        escopo[nome]()
        return escopo, saidas

    def test_edicao_hibrida_bloqueada_antes_de_coletar_alteracao(self):
        self.h.criar()
        r = self.h.store.executar(imediata.CHAVE)
        antes = self.h.f.foto()
        escopo, saidas = self.handler('editar_lancamento', [str(r.lancamento_ids[0])])
        escopo['atualizar_lancamento'].assert_not_called()
        self.assertEqual(self.h.f.foto(), antes)
        self.assertTrue(any('edição e exclusão legadas bloqueadas' in s for s in saidas))

    def test_exclusao_hibrida_bloqueada_antes_da_confirmacao(self):
        self.h.criar()
        r = self.h.store.executar(imediata.CHAVE)
        antes = self.h.f.foto()
        escopo, saidas = self.handler('excluir_lancamento_menu', [str(r.lancamento_ids[0])])
        escopo['excluir_lancamento'].assert_not_called()
        self.assertEqual(self.h.f.foto(), antes)
        self.assertTrue(any('Eventos financeiros' in s for s in saidas))

    def test_exclusao_legada_desempacota_sete_campos_e_exclui_alvo(self):
        identificador = self.legado()
        self.assertEqual(len(banco.buscar_lancamento(identificador)), 7)
        escopo, saidas = self.handler('excluir_lancamento_menu', [str(identificador), '1'])
        escopo['excluir_lancamento'].assert_called_once_with(identificador)
        self.assertIsNone(banco.buscar_lancamento(identificador))
        self.assertTrue(any('com sucesso' in s for s in saidas))

    def test_edicao_legada_elegivel_preservada(self):
        identificador = self.legado()
        escopo, saidas = self.handler('editar_lancamento', [str(identificador), '2', 'Descrição corrigida'])
        escopo['atualizar_lancamento'].assert_called_once()
        self.assertEqual(banco.buscar_lancamento(identificador)[2], 'Descrição corrigida')
        self.assertTrue(any('com sucesso' in s for s in saidas))

    def test_cancelar_exclusao_nao_modifica_legado(self):
        identificador = self.legado()
        antes = banco.buscar_lancamento(identificador)
        escopo, _ = self.handler('excluir_lancamento_menu', [str(identificador), '2'])
        escopo['excluir_lancamento'].assert_not_called()
        self.assertEqual(banco.buscar_lancamento(identificador), antes)

    def test_protecao_compativel_com_base_anterior_a_migracao_3(self):
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(self.h.f.legado_v2)}), \
                patch.object(banco, 'aplicar_migracoes', side_effect=AssertionError('Migração')):
            identificador = self.legado()
            self.assertTrue(ui.permitir_alteracao_legada(identificador, saida=lambda _: None))
            self.handler('excluir_lancamento_menu', [str(identificador), '1'])
            self.assertIsNone(banco.buscar_lancamento(identificador))

    def test_referencias_protegem_caixa_legado_sem_colunas_hibridas(self):
        for numero, coluna in enumerate(('lancamento_legado_id', 'lancamento_id')):
            destino = self.h.f.f.clone('referencia' + str(numero))
            # Usar o snapshot v2, cuja tabela lancamentos não possui marcadores.
            with closing(sqlite3.connect(self.h.f.legado_v2)) as origem, closing(sqlite3.connect(destino)) as copia:
                origem.backup(copia)
            with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
                identificador = self.legado()
                with closing(banco.abrir_conexao()) as c:
                    campo = ',lancamento_legado_id' if coluna == 'lancamento_legado_id' else ''
                    extra = ',?' if campo else ''
                    p = (identificador,) if campo else ()
                    evento = c.execute("INSERT INTO eventos_financeiros(tipo,descricao,categoria_id,valor_centavos,"
                        f"situacao_competencia,chave_origem{campo}) VALUES('despesa','Histórico',1,100,'pendente','vinculo'{extra})", p).lastrowid
                    if not campo:
                        c.execute('INSERT INTO liquidacoes_eventos(evento_id,lancamento_id,valor_centavos) VALUES(?,?,100)',
                                  (evento, identificador))
                    c.commit()
                self.assertFalse(ui.permitir_alteracao_legada(identificador, saida=lambda _: None))
                escopo, _ = self.handler('excluir_lancamento_menu', [str(identificador)])
                escopo['excluir_lancamento'].assert_not_called()
                self.assertIsNotNone(banco.buscar_lancamento(identificador))

    def test_protecao_revalidada_depois_dos_prompts(self):
        identificador = self.legado()
        for nome, respostas in [('editar_lancamento', [str(identificador), '2', 'Nova']),
                                ('excluir_lancamento_menu', [str(identificador), '1'])]:
            protecao = Mock(side_effect=[True, False])
            escopo, _ = self.handler(nome, respostas, permitir_alteracao_legada=protecao)
            self.assertEqual(protecao.call_count, 2)
            escopo['atualizar_lancamento'].assert_not_called()
            escopo['excluir_lancamento'].assert_not_called()

    def test_rejeicao_final_do_banco_nao_e_anunciada_como_sucesso(self):
        identificador = self.legado()
        falhar = Mock(side_effect=sqlite3.IntegrityError('Proteção final'))
        for nome, campo, respostas in [('editar_lancamento', 'atualizar_lancamento', [str(identificador), '2', 'Nova']),
                                       ('excluir_lancamento_menu', 'excluir_lancamento', [str(identificador), '1'])]:
            escopo, saidas = self.handler(nome, respostas, **{campo: falhar})
            self.assertTrue(any('recusada' in s for s in saidas))
            self.assertFalse(any('com sucesso' in s for s in saidas))
            self.assertIsNotNone(banco.buscar_lancamento(identificador))

    def test_falha_de_leitura_bloqueia_sem_criar_banco(self):
        destino = self.h.pasta / 'ausente.db'
        saidas = []
        with patch.dict(os.environ, {'KAIRUA_DB_PATH': str(destino)}):
            self.assertFalse(ui.permitir_alteracao_legada(1, saida=saidas.append))
        self.assertFalse(destino.exists())
        self.assertTrue(any('Nenhuma alteração autorizada' in s for s in saidas))
