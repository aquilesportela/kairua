"""Submenu híbrido 3.3B. Importação sem conexão, inicialização ou migração.

Diário padrão: LOCALAPPDATA/Kairua/intencoes/<hash do caminho do banco>.
Entradas/saídas injetáveis; somente registrar_evento_manual produz efeitos.
"""
from contextlib import closing
from datetime import date
import re
import sqlite3
from uuid import uuid4

import banco
import servicos_financeiros as sf
from intencoes_financeiras import ArmazenamentoIntencoes, ErroIntencao


def interpretar_valor_brasileiro(texto):
    if type(texto) is not str:
        raise sf.ValorInvalido('Informe um valor textual brasileiro.')
    texto = texto.strip()
    if len(texto) > 4096:
        raise sf.ValorInvalido('Valor textual excessivamente longo.')
    if texto.startswith('R$ '):
        texto = texto[3:]
    if not re.fullmatch(r'(?:[0-9]+|[1-9][0-9]{0,2}(?:\.[0-9]{3})+)(?:,[0-9]{1,2})?', texto):
        raise sf.ValorInvalido('Use 1234,56 ou 1.234,56, sem fração de centavo.')
    return sf.converter_decimal_centavos(texto.replace('.', '').replace(',', '.'))


def interpretar_data_brasileira(texto):
    if type(texto) is not str or not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}', texto):
        raise sf.DataInvalida('Use DD/MM/AAAA.')
    dia, mes, ano = map(int, texto.split('/'))
    try:
        return date(ano, mes, dia)
    except ValueError as erro:
        raise sf.DataInvalida('Data inexistente.') from erro


def listar_categorias(tipo):
    # Leitura somente; nunca chama inicializadores legados. Não mantém conexão
    # aberta durante os prompts. A validação definitiva pertence ao serviço.
    try:
        with closing(banco.abrir_conexao()) as c:
            return c.execute('SELECT id,nome FROM categorias WHERE tipo=? ORDER BY nome', (tipo,)).fetchall()
    except sqlite3.OperationalError as erro:
        if 'no such table' in str(erro).lower() or 'no such column' in str(erro).lower():
            raise sf.EsquemaIncompativel('Cadastro de categorias indisponível.') from erro
        raise


def _recibo(resultado, saida):
    saida(f'Operação confirmada: {resultado.operacao_id}. Evento: {resultado.evento_ids[0]}.')
    saida(f'Chave de recuperação: {resultado.chave}')
    saida('Competência registrada. Nenhuma movimentação de caixa ou liquidação foi criada.')


def _falha(erro, saida, chave=None, armazenamento=None):
    if chave is not None and armazenamento is not None:
        try:
            incerta = armazenamento.obter(chave)['estado'] == 'incerta'
        except Exception:
            incerta = False
        if incerta:
            saida('Resultado incerto. Intenção preservada; recupere com a mesma chave, sem novo cadastro.')
            saida(f'Chave: {chave}')
            if isinstance(erro, sf.EsquemaIncompativel):
                saida('Esquema híbrido indisponível; nenhuma migração foi executada.')
            return
    if isinstance(erro, sf.EsquemaIncompativel):
        saida('Esquema híbrido indisponível ou incompatível. Nenhuma migração foi executada.')
    elif isinstance(erro, ErroIntencao):
        saida(f'Recuperação local bloqueada: {erro}')
    elif isinstance(erro, (sf.ParametroInvalido, sf.CategoriaInexistente,
                           sf.CategoriaIncompativel, sf.IdentificadoresEsgotados)):
        saida(f'Operação recusada: {erro}')
    else:
        saida('Resultado não confirmado. A intenção foi preservada quando persistida; consulte a recuperação.')
    if chave is not None:
        saida(f'Chave: {chave}. Não crie outra intenção para repetir esta operação.')


def registrar_manual(*, entrada=input, saida=print, armazenamento=None, categorias=None, servico=None):
    chave = None
    diario = armazenamento
    try:
        saida('Registrar evento manual de competência, sem pagamento/recebimento e sem alteração do caixa.')
        tipo = entrada('Tipo (receita/despesa): ').strip().lower()
        if tipo not in ('receita', 'despesa'):
            raise sf.ParametroInvalido('Tipo deve ser receita ou despesa.')
        descricao = sf.normalizar_texto(entrada('Descrição: '))
        opcoes = (categorias or listar_categorias)(tipo)
        if not opcoes:
            saida('Não há categorias compatíveis cadastradas.')
            return
        for identificador, nome in opcoes:
            saida(f'{identificador}: {nome}')
        try:
            categoria_id = int(entrada('ID da categoria: '))
        except ValueError as erro:
            raise sf.ParametroInvalido('ID de categoria inválido.') from erro
        if categoria_id not in {c[0] for c in opcoes}:
            raise sf.CategoriaIncompativel('Selecione uma categoria da lista do tipo informado.')
        valor = interpretar_valor_brasileiro(entrada('Valor (R$): '))
        competencia = interpretar_data_brasileira(entrada('Competência (DD/MM/AAAA): '))
        vencimento = interpretar_data_brasileira(entrada('Vencimento (DD/MM/AAAA): '))
        saida('Confirme a ocorrência econômica. Este registro NÃO cria caixa.')
        if entrada('Digite SIM para confirmar e registrar; outra resposta cancela: ').strip() != 'SIM':
            saida('Cadastro cancelado. Nenhuma intenção foi persistida.')
            return
        p = dict(tipo=tipo, descricao=descricao, categoria_id=categoria_id, valor_centavos=valor,
                 data_competencia=competencia, data_vencimento=vencimento, confirmar_ocorrencia=True)
        chave = 'kairua:v1:' + str(uuid4())
        diario = armazenamento if armazenamento is not None else ArmazenamentoIntencoes()
        diario.criar(chave=chave, **p)
        # A chave é exibida antes da chamada, inclusive se a resposta se perder.
        saida(f'Intenção persistida. Chave: {chave}')
        _recibo(diario.executar(chave, servico=servico), saida)
    except (EOFError, KeyboardInterrupt):
        saida('Entrada interrompida; consulte intenções pendentes antes de repetir o cadastro.')
    except (sf.ErroFinanceiro, ErroIntencao, OSError, ValueError, sqlite3.Error) as erro:
        _falha(erro, saida, chave, diario)
    except Exception as erro:
        _falha(erro, saida, chave, diario)


def menu_eventos_financeiros(*, entrada=input, saida=print, armazenamento=None):
    diario = armazenamento if armazenamento is not None else ArmazenamentoIntencoes()
    while True:
        chave = None
        saida('Eventos financeiros\n1 - Registrar evento manual\n'
              '2 - Consultar operações pendentes ou incertas\n3 - Recuperar resultado de operação\n0 - Voltar')
        try:
            opcao = entrada('Opção: ').strip()
            if opcao == '0':
                return
            if opcao == '1':
                registrar_manual(entrada=entrada, saida=saida, armazenamento=diario)
            elif opcao == '2':
                registros = diario.listar_pendentes()
                if not registros:
                    saida('Nenhuma intenção pendente ou incerta.')
                for r in registros:
                    saida(f"{r['chave']} — {r['estado']}")
            elif opcao == '3':
                chave = entrada('Chave original: ').strip()
                r = diario.obter(chave)
                saida('A recuperação repetirá exatamente o payload persistido, com a mesma chave.')
                saida(r['payload'])
                if entrada('Digite SIM para recuperar: ').strip() == 'SIM':
                    _recibo(diario.executar(chave), saida)
            else:
                saida('Opção inválida.')
        except (EOFError, KeyboardInterrupt):
            saida('Retornando. Intenções persistidas foram preservadas.')
            return
        except (sf.ErroFinanceiro, ErroIntencao, OSError, ValueError) as erro:
            _falha(erro, saida, chave, diario)
        except Exception as erro:
            _falha(erro, saida, chave, diario)
