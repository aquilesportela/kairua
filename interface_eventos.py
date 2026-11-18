"""Submenu híbrido 3.3B. Importação sem conexão, inicialização ou migração.

Diário padrão: LOCALAPPDATA/Kairua/intencoes/<hash do caminho do banco>.
Entradas/saídas injetáveis; somente registrar_evento_manual produz efeitos.
"""
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

import banco
import servicos_financeiros as sf
import consultas_eventos as consultas
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


def formatar_centavos(valor):
    """Aceita também totais brutos acima de int64, sem conversão para REAL."""
    if type(valor) is not int:
        raise sf.ValorInvalido('Use centavos inteiros na apresentação.')
    magnitude = abs(valor)
    reais = format(magnitude // 100, ',').replace(',', '.')
    return f'R$ {"-" if valor < 0 else ""}{reais},{magnitude % 100:02d}'


def _mostrar_liquidacao(q, saida):
    saida(f'Liquidação #{q.id} — evento #{q.evento_id}, caixa original #{q.lancamento_id}, operação #{q.operacao_id}')
    saida(f'Tipo econômico: {q.tipo}. Data do caixa: {q.data_caixa:%d/%m/%Y}')
    saida(f'Categoria histórica do caixa: {q.categoria_historica.id} — {q.categoria_historica.nome}')
    saida(f'Valor originalmente alocado: {formatar_centavos(q.valor_original_centavos)}')
    saida(f'Valor integral do caixa (não somar por vínculo): {formatar_centavos(q.valor_caixa_centavos)}')
    saida(f'Total estornado: {formatar_centavos(q.total_estornado_centavos)}')
    saida(f'Saldo estornável: {formatar_centavos(q.saldo_estornavel_centavos)}')
    if not q.estornos:
        saida('Nenhum estorno vinculado.')
    for s in q.estornos:
        saida(f'ESTORNO #{s.id} — liquidação #{s.liquidacao_id}, caixa negativo #{s.lancamento_id}, '
              f'operação #{s.operacao_id}: {formatar_centavos(s.valor_centavos)}')
        saida(f'Data: {s.data:%d/%m/%Y}. Natureza: {s.natureza}. Motivo: {s.motivo}')
        saida(f'Categoria histórica: {s.categoria_historica.id} — {s.categoria_historica.nome}')
    saida('Elegibilidade informativa para estorno: ' + ('sim' if q.elegivel_estorno else 'não'))


def _mostrar_evento(e, saida):
    saida(f'Evento #{e.id} — {e.tipo}: {e.descricao}')
    saida(f'Competência: {e.data_competencia:%d/%m/%Y}. Vencimento: {e.data_vencimento:%d/%m/%Y}')
    saida(f'Categoria corrente: {e.categoria_atual.id} — {e.categoria_atual.nome}')
    for rotulo, valor in (
        ('Valor original de competência', e.valor_original_centavos),
        ('Total liquidado bruto', e.total_liquidado_bruto_centavos),
        ('Total estornado', e.total_estornado_centavos),
        ('Total liquidado líquido', e.total_liquidado_liquido_centavos),
        ('Saldo aberto', e.saldo_aberto_centavos),
    ):
        saida(f'{rotulo}: {formatar_centavos(valor)}')
    if e.reversao:
        saida(f'EVENTO REVERTIDO — reversão #{e.reversao.id} em {e.reversao.data:%d/%m/%Y}. '
              'Compromisso cancelado; competência original preservada.')
    if not e.liquidacoes:
        saida('Nenhuma liquidação ou movimentação de caixa vinculada.')
    for q in e.liquidacoes:
        _mostrar_liquidacao(q, saida)


def menu_consultas_eventos(*, entrada=input, saida=print):
    while True:
        saida('Consulta de eventos e liquidações — somente leitura\n'
              '1 - Listar eventos com saldo aberto\n2 - Detalhar evento por ID\n'
              '3 - Listar liquidações com saldo estornável\n4 - Detalhar liquidação por ID\n0 - Voltar')
        try:
            opcao = entrada('Opção: ').strip()
            if opcao == '0':
                return
            if opcao == '1':
                eventos = consultas.listar_eventos_liquidaveis()
                if not eventos:
                    saida('Nenhum evento elegível com saldo aberto.')
                for e in eventos:
                    saida(f'#{e.id} | {e.tipo} | {e.descricao} | competência {e.data_competencia:%d/%m/%Y} | '
                          f'vencimento {e.data_vencimento:%d/%m/%Y} | {e.categoria_atual.nome} | '
                          f'saldo aberto {formatar_centavos(e.saldo_aberto_centavos)}')
            elif opcao == '3':
                liquidacoes = consultas.listar_liquidacoes_estornaveis()
                if not liquidacoes:
                    saida('Nenhuma liquidação elegível com saldo estornável.')
                for q in liquidacoes:
                    _mostrar_liquidacao(q, saida)
            elif opcao in ('2', '4'):
                identificador = int(entrada('ID (0 para cancelar): '))
                if identificador == 0:
                    continue
                if opcao == '2':
                    detalhe = consultas.obter_detalhe_evento(identificador)
                    _mostrar_evento(detalhe, saida)
                else:
                    detalhe = consultas.obter_detalhe_liquidacao(identificador)
                    _mostrar_liquidacao(detalhe, saida)
            else:
                saida('Opção inválida.')
        except (EOFError, KeyboardInterrupt):
            saida('Consulta encerrada. Nenhum dado foi modificado.')
            return
        except sf.EsquemaIncompativel:
            saida('Esquema híbrido indisponível ou incompatível; nenhuma migração foi executada.')
        except sf.OperacaoIncompleta as erro:
            saida(f'Inconsistência financeira detectada: {erro} Nenhum saldo foi presumido ou reparado.')
        except (sf.ErroFinanceiro, ValueError, OSError) as erro:
            saida(f'Consulta não realizada: {erro}')


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


def _recibo(resultado, saida, registro=None):
    if resultado.tipo_operacao not in ('registrar_evento', 'registrar_imediata'):
        raise ErroIntencao('Tipo de recibo não disponível nesta interface.')
    saida(f'Operação confirmada: {resultado.operacao_id}. Evento: {resultado.evento_ids[0]}.')
    saida(f'Chave de recuperação: {resultado.chave}')
    if resultado.tipo_operacao == 'registrar_evento':
        saida('Competência registrada. Nenhuma movimentação de caixa ou liquidação foi criada.')
    else:
        saida(f'Evento criado: {resultado.evento_ids[0]}. Caixa criado: {resultado.lancamento_ids[0]}. '
              f'Liquidação integral criada: {resultado.liquidacao_ids[0]}.')
    if registro is not None:
        # Dados originais da intenção, nunca joins com categorias correntes.
        p = json.loads(registro['payload'])['parametros']
        saida(f"Tipo econômico: {p['tipo']}. Valor original: {formatar_centavos(p['valor_centavos'])}.")
        saida(f"Categoria original (ID): {p['categoria_id']}.")
        for campo, rotulo in (('data_competencia', 'Competência'), ('data_vencimento', 'Vencimento'),
                              ('data_liquidacao', 'Liquidação / caixa')):
            if campo in p:
                ano, mes, dia = p[campo].split('-')
                saida(f'{rotulo}: {dia}/{mes}/{ano}')


def permitir_alteracao_legada(lancamento_id, *, saida=print):
    """Pré-checagem de UI, compatível com bases anteriores ao esquema híbrido.

    Não inicializa/migra; os gatilhos permanecem a defesa contra corridas.
    Falha de leitura ou estrutura parcialmente presente bloqueia a alteração.
    """
    try:
        if type(lancamento_id) is not int or not -2**63 <= lancamento_id <= sf.MAX_CENTAVOS:
            raise ValueError('ID inválido')
        uri = Path(banco.obter_caminho_banco()).absolute().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as c:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            tabelas = {r[0].lower() for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            linha = c.execute('SELECT * FROM lancamentos WHERE id=?', (lancamento_id,)).fetchone()
            if linha is None:
                saida('Lançamento não encontrado; nenhuma alteração autorizada.')
                return False
            valores = {nome.lower(): linha[nome] for nome in linha.keys()}
            protegido = any(valores.get(campo) is not None
                            for campo in ('operacao_hibrida_id', 'valor_centavos'))
            for tabela, campo in (('liquidacoes_eventos', 'lancamento_id'),
                                  ('estornos_liquidacoes', 'lancamento_estorno_id'),
                                  ('eventos_financeiros', 'lancamento_legado_id')):
                if tabela in tabelas:
                    vinculo = c.execute(f'SELECT 1 FROM {tabela} WHERE {campo}=? LIMIT 1', (lancamento_id,)).fetchone()
                    protegido = protegido or vinculo is not None
        if protegido:
            saida('Lançamento vinculado ao fluxo financeiro híbrido: edição e exclusão legadas bloqueadas. '
                  'Utilize o fluxo de Eventos financeiros para consultar e tratar seus vínculos.')
            return False
        return True
    except (sqlite3.Error, ValueError, OSError):
        saida('Não foi possível verificar a proteção do lançamento. Nenhuma alteração autorizada.')
        return False


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
        registro = diario.criar(chave=chave, **p)
        # A chave é exibida antes da chamada, inclusive se a resposta se perder.
        saida(f'Intenção persistida. Chave: {chave}')
        _recibo(diario.executar(chave, servico=servico), saida, registro)
    except (EOFError, KeyboardInterrupt):
        saida('Entrada interrompida; consulte intenções pendentes antes de repetir o cadastro.')
    except (sf.ErroFinanceiro, ErroIntencao, OSError, ValueError, sqlite3.Error) as erro:
        _falha(erro, saida, chave, diario)
    except Exception as erro:
        _falha(erro, saida, chave, diario)


def registrar_imediata(*, entrada=input, saida=print, armazenamento=None, categorias=None, servico=None):
    chave = None
    diario = armazenamento
    try:
        saida('Registrar competência e caixa com liquidação integral na mesma operação.')
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
        nomes = dict(opcoes)
        if categoria_id not in nomes:
            raise sf.CategoriaIncompativel('Selecione uma categoria da lista do tipo informado.')
        valor = interpretar_valor_brasileiro(entrada('Valor (R$): '))
        competencia = interpretar_data_brasileira(entrada('Competência (DD/MM/AAAA): '))
        vencimento = interpretar_data_brasileira(entrada('Vencimento (DD/MM/AAAA): '))
        liquidacao = interpretar_data_brasileira(entrada('Liquidação / caixa (DD/MM/AAAA): '))
        saida(f'Tipo: {tipo}. Descrição: {descricao}. Valor: {formatar_centavos(valor)}.')
        saida(f'Categoria selecionada: {categoria_id} — {nomes[categoria_id]}.')
        for rotulo, data in (('Competência', competencia), ('Vencimento', vencimento), ('Liquidação / caixa', liquidacao)):
            saida(f'{rotulo}: {data.day:02d}/{data.month:02d}/{data.year:04d}')
        saida('Serão criados um evento de competência, um lançamento de caixa e uma liquidação integral.')
        if entrada('Confirme a ocorrência econômica e o registro digitando SIM: ').strip() != 'SIM':
            saida('Cadastro cancelado. Nenhuma intenção foi persistida.')
            return
        divergentes = competencia != liquidacao
        if divergentes and entrada('Competência e caixa divergem. Digite SIM para confirmar essas datas: ').strip() != 'SIM':
            saida('Cadastro cancelado. Datas divergentes não confirmadas.')
            return
        p = dict(tipo=tipo, descricao=descricao, categoria_id=categoria_id, valor_centavos=valor,
                 data_competencia=competencia, data_vencimento=vencimento, data_liquidacao=liquidacao,
                 confirmar_ocorrencia=True, confirmar_datas_divergentes=divergentes)
        chave = 'kairua:v1:' + str(uuid4())
        diario = armazenamento if armazenamento is not None else ArmazenamentoIntencoes()
        registro = diario.criar(chave=chave, servico='registrar_operacao_imediata', **p)
        saida(f'Intenção persistida. Chave: {chave}')
        _recibo(diario.executar(chave, servico=servico), saida, registro)
    except (EOFError, KeyboardInterrupt):
        saida('Entrada interrompida; consulte intenções pendentes antes de repetir o cadastro.')
    except Exception as erro:
        _falha(erro, saida, chave, diario)


def menu_eventos_financeiros(*, entrada=input, saida=print, armazenamento=None):
    diario = armazenamento if armazenamento is not None else ArmazenamentoIntencoes()
    while True:
        chave = None
        saida('Eventos financeiros\n1 - Registrar evento manual\n'
              '2 - Consultar operações pendentes ou incertas\n3 - Recuperar resultado de operação\n'
              '4 - Consultar eventos e liquidações\n5 - Registrar operação imediata\n0 - Voltar')
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
                    saida(f"{r['chave']} — {r['estado']} — {json.loads(r['payload'])['servico']}")
            elif opcao == '3':
                chave = entrada('Chave original: ').strip()
                r = diario.obter(chave)
                saida('A recuperação repetirá exatamente o payload persistido, com a mesma chave.')
                saida(r['payload'])
                if entrada('Digite SIM para recuperar: ').strip() == 'SIM':
                    _recibo(diario.executar(chave), saida, r)
            elif opcao == '4':
                menu_consultas_eventos(entrada=entrada, saida=saida)
            elif opcao == '5':
                registrar_imediata(entrada=entrada, saida=saida, armazenamento=diario)
            else:
                saida('Opção inválida.')
        except (EOFError, KeyboardInterrupt):
            saida('Retornando. Intenções persistidas foram preservadas.')
            return
        except (sf.ErroFinanceiro, ErroIntencao, OSError, ValueError) as erro:
            _falha(erro, saida, chave, diario)
        except Exception as erro:
            _falha(erro, saida, chave, diario)
