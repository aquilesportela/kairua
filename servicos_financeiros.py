"""Servicos hibridos de competencia, caixa e historicos financeiros (3.2B.6).

Nao abre banco no import nem executa migracoes automaticamente.

O controlador _UnidadeTrabalho e privado: futuros servicos devem validar o
estado dinamico e produzir efeitos na mesma conexao. Nao e sandbox para codigo
Python que acesse deliberadamente a conexao privada e execute commit/DDL.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
import sqlite3
import unicodedata
from uuid import UUID
from typing import Literal

import banco
import migracao_3


MAX_CENTAVOS = 9223372036854775807
VERSAO_CONTRATO = 1
TipoEconomico = Literal['receita', 'despesa']
NaturezaEstorno = Literal['devolucao_real', 'correcao_registro']
TipoOperacao = Literal['registrar_evento', 'registrar_imediata', 'liquidar_evento',
                       'estornar_liquidacao', 'reverter_evento', 'reclassificar_evento']


class ErroFinanceiro(Exception):
    """Base de erros de dominio; a causa SQLite e preservada quando aplicavel."""


class ParametroInvalido(ErroFinanceiro): pass
class ValorInvalido(ParametroInvalido): pass
class DataInvalida(ParametroInvalido): pass
class ConfirmacaoNecessaria(ParametroInvalido): pass
class CategoriaInexistente(ErroFinanceiro): pass
class CategoriaIncompativel(ErroFinanceiro): pass
class EventoInexistente(ErroFinanceiro): pass
class EventoNaoElegivel(ErroFinanceiro): pass
class EventoRevertido(ErroFinanceiro): pass
class LiquidacaoInexistente(ErroFinanceiro): pass
class SaldoInsuficiente(ErroFinanceiro): pass
class EstornoExcessivo(ErroFinanceiro): pass
class EventoJaRevertido(ErroFinanceiro): pass
class EventoAindaLiquidado(ErroFinanceiro): pass
class ReclassificacaoSemAlteracao(ErroFinanceiro): pass
class ConflitoIdempotencia(ErroFinanceiro): pass
class ConflitoEstado(ErroFinanceiro): pass
class OperacaoIncompleta(ErroFinanceiro): pass
class EsquemaIncompativel(ErroFinanceiro): pass
class IdentificadoresEsgotados(ErroFinanceiro): pass
class BancoOcupado(ErroFinanceiro): pass
class FalhaPersistencia(ErroFinanceiro): pass


@dataclass(frozen=True)
class RequisicaoNormalizada:
    servico: str
    tipo_operacao: TipoOperacao
    chave: str
    requisicao_canonica: str
    versao_contrato: int = VERSAO_CONTRATO


@dataclass(frozen=True)
class OperacaoPersistida:
    id: int
    chave: str
    tipo: TipoOperacao
    requisicao_canonica: str
    estado: str


@dataclass(frozen=True)
class LinhaEfeito:
    campos: tuple

    def __getitem__(self, nome):
        return dict(self.campos)[nome]


@dataclass(frozen=True)
class EfeitosOperacao:
    eventos: tuple[LinhaEfeito, ...]
    lancamentos: tuple[LinhaEfeito, ...]
    liquidacoes: tuple[LinhaEfeito, ...]
    estornos: tuple[LinhaEfeito, ...]
    reversoes: tuple[LinhaEfeito, ...]
    reclassificacoes: tuple[LinhaEfeito, ...]


@dataclass(frozen=True)
class ResultadoOperacao:
    operacao_id: int
    chave: str
    tipo_operacao: TipoOperacao
    evento_ids: tuple[int, ...] = ()
    lancamento_ids: tuple[int, ...] = ()
    liquidacao_ids: tuple[int, ...] = ()
    estorno_ids: tuple[int, ...] = ()
    reversao_ids: tuple[int, ...] = ()
    reclassificacao_ids: tuple[int, ...] = ()
    versao_contrato: int = VERSAO_CONTRATO


def validar_centavos(valor):
    if type(valor) is not int or not 1 <= valor <= MAX_CENTAVOS:
        raise ValorInvalido('Magnitude deve ser inteiro positivo int64 em centavos')
    return valor


def converter_decimal_centavos(valor):
    """Inspeciona coeficiente/expoente; independente do contexto Decimal global.

    Strings usam ponto, sem locale/agrupamento; limite de 4096 caracteres e
    somente protecao de parsing, nao teto financeiro. Decimal ja construido
    nao tem limite de escala; zeros finais nao representam fracao de centavo.
    """
    if type(valor) is str:
        if len(valor) > 4096 or not re.fullmatch(r'[+]?[0-9]+(?:\.[0-9]+)?', valor):
            raise ValorInvalido('Formato decimal invalido')
        try:
            valor = Decimal(valor)
        except InvalidOperation as erro:
            raise ValorInvalido('Decimal invalido') from erro
    if type(valor) is not Decimal or not valor.is_finite():
        raise ValorInvalido('Use Decimal finito ou texto decimal exato')
    sinal, digitos, expoente = valor.as_tuple()
    if sinal or not any(digitos):
        raise ValorInvalido('Valor deve ser positivo')
    deslocamento = expoente + 2
    if deslocamento < 0:
        corte = -deslocamento
        if corte >= len(digitos) or any(digitos[-corte:]):
            raise ValorInvalido('Fracao de centavo nao permitida')
        digitos = digitos[:-corte]
        deslocamento = 0
    # Nunca construir uma potencia ou inteiro de tamanho arbitrario.
    if len(digitos) + deslocamento > 19:
        raise ValorInvalido('Valor excede int64')
    inteiro = 0
    for digito in digitos:
        inteiro = inteiro * 10 + digito
    return validar_centavos(inteiro * 10 ** deslocamento)


def validar_data(valor):
    if type(valor) is not date:
        raise DataInvalida('Use datetime.date sem hora')
    return valor


def interpretar_data_iso(valor):
    if type(valor) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', valor):
        raise DataInvalida('Data deve usar AAAA-MM-DD')
    try:
        return date.fromisoformat(valor)
    except ValueError as erro:
        raise DataInvalida('Data inexistente') from erro


def normalizar_texto(valor):
    if type(valor) is not str:
        raise ParametroInvalido('Texto deve ser str')
    texto = unicodedata.normalize('NFC', valor).strip()
    if not texto or '\x00' in texto:
        raise ParametroInvalido('Texto vazio ou com NUL')
    try:
        texto.encode('utf-8')
    except UnicodeError as erro:
        raise ParametroInvalido('Texto Unicode invalido') from erro
    return texto


def _booleano(valor):
    if type(valor) is not bool:
        raise ParametroInvalido('Confirmacao deve ser bool')
    return valor


def confirmar_datas(competencia, caixa, confirmado):
    validar_data(competencia)
    validar_data(caixa)
    _booleano(confirmado)
    if competencia != caixa and not confirmado:
        raise ConfirmacaoNecessaria('Confirme datas de caixa e competencia diferentes')


def validar_chave(chave):
    if type(chave) is not str or not chave.startswith('kairua:v1:'):
        raise ParametroInvalido('Chave idempotente invalida')
    try:
        uuid = UUID(chave[10:])
    except (ValueError, AttributeError) as erro:
        raise ParametroInvalido('UUID invalido') from erro
    if chave != 'kairua:v1:' + str(uuid):
        raise ParametroInvalido('Chave deve usar UUID canonico minusculo')
    return chave


def _identificador(valor):
    if type(valor) is not int or not -2**63 <= valor <= MAX_CENTAVOS:
        raise ParametroInvalido('Referencia deve ser inteiro int64')
    return valor


_CADASTRO = ('tipo', 'descricao', 'categoria_id', 'valor_centavos',
             'data_competencia', 'data_vencimento', 'confirmar_ocorrencia')
_CONTRATOS = {
    'registrar_evento_manual': ('registrar_evento', _CADASTRO, ()),
    'registrar_operacao_imediata': ('registrar_imediata', _CADASTRO +
        ('data_liquidacao', 'confirmar_datas_divergentes'), ()),
    'liquidar_evento': ('liquidar_evento', ('evento_id', 'valor_centavos',
        'data_liquidacao', 'confirmar_datas_divergentes'), ('descricao_caixa',)),
    'estornar_liquidacao': ('estornar_liquidacao', ('liquidacao_id', 'valor_centavos',
        'natureza', 'motivo', 'data_estorno', 'confirmar_datas_divergentes'), ()),
    'reverter_evento': ('reverter_evento', ('evento_id', 'data_reversao', 'motivo'), ()),
    'reclassificar_evento': ('reclassificar_evento', ('evento_id', 'categoria_nova_id',
        'motivo'), ('categoria_anterior_esperada_id',)),
}


def canonicalizar_requisicao(servico, *, chave, **parametros):
    validar_chave(chave)
    if type(servico) is not str or servico not in _CONTRATOS:
        raise ParametroInvalido('Servico desconhecido')
    tipo, obrigatorios, opcionais = _CONTRATOS[servico]
    if set(parametros) - set(obrigatorios + opcionais) or set(obrigatorios) - set(parametros):
        raise ParametroInvalido('Campos ausentes ou desconhecidos')
    normalizados = {}
    for campo in obrigatorios + opcionais:
        valor = parametros.get(campo)
        if campo in opcionais and valor is None:
            normalizados[campo] = None
            continue
        if campo == 'valor_centavos':
            valor = validar_centavos(valor)
        elif campo.endswith('_id'):
            valor = _identificador(valor)
        elif campo.startswith('data_'):
            valor = validar_data(valor).isoformat()
        elif campo.startswith('confirmar_'):
            valor = _booleano(valor)
            if campo == 'confirmar_ocorrencia' and not valor:
                raise ConfirmacaoNecessaria('Ocorrencia economica deve ser confirmada')
        else:
            valor = normalizar_texto(valor)
            if campo == 'tipo' and valor not in ('receita', 'despesa'):
                raise ParametroInvalido('Tipo economico invalido')
            if campo == 'natureza' and valor not in ('devolucao_real', 'correcao_registro'):
                raise ParametroInvalido('Natureza de estorno invalida')
        normalizados[campo] = valor
    if servico == 'registrar_operacao_imediata':
        confirmar_datas(parametros['data_competencia'], parametros['data_liquidacao'],
                        parametros['confirmar_datas_divergentes'])
    payload = json.dumps(dict(versao_contrato=1, servico=servico, tipo_operacao=tipo,
                             parametros=normalizados), ensure_ascii=False,
                         sort_keys=True, separators=(',', ':'), allow_nan=False)
    return RequisicaoNormalizada(servico, tipo, chave, payload)


def _conferir_requisicao(req):
    # Dataclass frozen nao e autorizacao para aceitar construcao manual invalida.
    if type(req) is not RequisicaoNormalizada or type(req.versao_contrato) is not int or req.versao_contrato != 1:
        raise ParametroInvalido('Versao ou tipo de requisicao invalido')
    try:
        dados = json.loads(req.requisicao_canonica)
        parametros = dict(dados['parametros'])
        for campo in parametros:
            if campo.startswith('data_'):
                parametros[campo] = interpretar_data_iso(parametros[campo])
        reconstruida = canonicalizar_requisicao(req.servico, chave=req.chave, **parametros)
        if reconstruida != req:
            raise ParametroInvalido('Requisicao nao canonica')
    except (TypeError, ValueError, KeyError, AttributeError) as erro:
        raise ParametroInvalido('Requisicao invalida') from erro


# Manifesto conservador das tabelas aprovadas em fe7bb69, gerado uma unica vez
# de fixture legada sintetica + catalogo publicado, nunca da base inspecionada.
# SHA256 do DDL sqlite_master.strip(), sem normalizar literais/comentarios.
# Pode rejeitar DDL equivalente; nao normaliza/converte o legado.
_TABELAS_DDL = {
    'cartoes': '86d11dfb9fb6fc9c070b988319936e8c77ac6cc1c3f6b8745cc056a01fcd3222',
    'categorias': 'b5e9c171bf106e5f9f1e65aa57a607b0f86e93258130458bc53dbcd854da1df8',
    'compras_cartao': 'ba8e82062257e967b3e266fec43c84684a038d2587aef959916306012ec24429',
    'esquema_migracoes': '938bd74de0c7a16358b009756c2d3c3f1d828466afdef5504bfdbe95987fb9ba',
    'estornos_liquidacoes': 'a529fcff9530bb64eb8e47a211c7854148d7c66b4b8202269c225a344b575569',
    'eventos_financeiros': '8578f0e9351f404e5432620d467b3ea30fe33f611bca3c7f4f3bfdc875194e0f',
    'faturas': '6bbcb07376307ed8ca68081401e856f7037eacc8edd2ec98ad4de016a758f402',
    'lancamentos': '61dd5f0afbe606ad1f9f1d6ad7f7d0e3db69da6d4a0f4305bea5cb3ac44b2612',
    'liquidacoes_eventos': '00b4a45a790fa440548b993b39410fede2356817fa2397c9d13a4cc3ce1a80fe',
    'operacoes_hibridas': '49efe262e81de40421a1951b91676437dc5308b459f08a34369664f919fe4b04',
    'parcelamento_parcelas': 'f2a8e87e841d61dcfd7ec78e3638cdce47a62b63f1486335829630d704b9af56',
    'parcelamentos': '5d0f1f29edf0ea412d31280f31c05865b5134b065f6497f500450b7fcd238f28',
    'parcelas_cartao': '164cf63811c2d379b60f4da3ba506202e4ae675bfd73b9647d969300a1822091',
    'reclassificacoes_eventos': '3f8a3f45ff712c6381e8191fc7428b72f5ac32f558cf4c4001d49960a48c5cce',
    'recorrencia_ocorrencias': '493684ec08e632fb25d10c4b7c16eab219287f2456771bcffca5b1a03433a92e',
    'recorrencias': '92c28ae1184e621fffb142edc2d8f2b2e24c8addf77a26b8f5668721072885d5',
    'reversoes_eventos': '9b91d55e08e06a23f3abe2bbd9164b86b0de1512f6771c2c5a3161fe87dfa918',
}


def _objetos_catalogo():
    # Somente formato fechado do catalogo confiavel, nao interpreta SQL externo.
    objetos = {}
    for sql in (*banco.MIGRACOES[1][2], *migracao_3.SQL_MIGRACAO_3):
        partes = sql.strip().split(None, 3)
        if partes[0] == 'CREATE' and partes[1] in ('INDEX', 'VIEW', 'TRIGGER'):
            objetos[partes[2]] = (partes[1].lower(), sql.strip())
    return objetos


_OBJETOS_ESPERADOS = _objetos_catalogo()
_HISTORICO = ((1, 'controle_de_versoes'), (2, 'esquema_financeiro_hibrido'),
              (3, 'contrato_operacoes_hibridas'))


def _verificar_esquema(c):
    """Somente leitura, exigida sob o lock transacional; sem cache da base."""
    if not c.in_transaction:
        raise EsquemaIncompativel('Verificacao exige transacao ativa')
    try:
        objetos = {r[0].lower(): r for r in c.execute(
            'SELECT name,type,tbl_name,sql FROM main.sqlite_master')}
        for nome, digest in _TABELAS_DDL.items():
            objeto = objetos.get(nome)
            if (not objeto or objeto[1] != 'table' or
                    sha256(objeto[3].strip().encode('utf-8')).hexdigest() != digest):
                raise EsquemaIncompativel(f'DDL de tabela nao suportado: {nome}')
        if tuple(c.execute('SELECT versao,nome FROM esquema_migracoes ORDER BY versao')) != _HISTORICO:
            raise EsquemaIncompativel('Historico de versoes nao suportado')
        for nome, (tipo, sql) in _OBJETOS_ESPERADOS.items():
            objeto = objetos.get(nome)
            if not objeto or objeto[1] != tipo or objeto[3].strip() != sql:
                raise EsquemaIncompativel(f'Objeto divergente: {nome}')
        for nome, tipo, tabela, _ in objetos.values():
            if tipo == 'trigger' and tabela.lower() in _TABELAS_DDL and nome not in _OBJETOS_ESPERADOS:
                raise EsquemaIncompativel(f'Gatilho desconhecido: {nome}')
        cobertas = dict(migracao_3._UNICIDADES_COBERTAS)
        cobertas.update(operacoes_hibridas={('id',), ('chave',)},
            estornos_liquidacoes={('id',), ('lancamento_estorno_id',)},
            reversoes_eventos={('id',), ('evento_id',)},
            reclassificacoes_eventos={('id',), ('operacao_hibrida_id', 'evento_id')})
        for tabela, chaves in cobertas.items():
            for indice in c.execute('SELECT * FROM pragma_index_list(?)', (tabela,)):
                if not indice[2]:
                    continue
                dono, unico, parcial, origem, campos = migracao_3._identidade_indice(c, indice[1])
                if (dono.lower() != tabela or not unico or parcial or origem not in ('c', 'u', 'pk')
                        or migracao_3._chaves_simples(campos) not in chaves):
                    raise EsquemaIncompativel(f'Unicidade nao coberta: {indice[1]}')
    except (sqlite3.Error, ValueError, AttributeError) as erro:
        raise EsquemaIncompativel('Falha ao conferir estrutura SQLite') from erro


def _linhas(c, sql, parametros):
    cursor = c.execute(sql, parametros)
    nomes = tuple(d[0] for d in cursor.description)
    return tuple(LinhaEfeito(tuple(zip(nomes, linha))) for linha in cursor)


def _ler_efeitos(c, operacao_id):
    return EfeitosOperacao(
        _linhas(c, 'SELECT * FROM eventos_financeiros WHERE operacao_hibrida_id=? ORDER BY id', (operacao_id,)),
        _linhas(c, 'SELECT * FROM lancamentos WHERE operacao_hibrida_id=? ORDER BY id', (operacao_id,)),
        _linhas(c, 'SELECT q.* FROM liquidacoes_eventos q JOIN lancamentos l ON l.id=q.lancamento_id '
                'WHERE l.operacao_hibrida_id=? ORDER BY q.id', (operacao_id,)),
        _linhas(c, 'SELECT s.* FROM estornos_liquidacoes s JOIN lancamentos l ON l.id=s.lancamento_estorno_id '
                'WHERE l.operacao_hibrida_id=? ORDER BY s.id', (operacao_id,)),
        _linhas(c, 'SELECT * FROM reversoes_eventos WHERE operacao_hibrida_id=? ORDER BY id', (operacao_id,)),
        _linhas(c, 'SELECT * FROM reclassificacoes_eventos WHERE operacao_hibrida_id=? ORDER BY id', (operacao_id,)))


def _exigir(condicao, mensagem='Efeitos financeiros incompletos ou divergentes'):
    if not condicao:
        raise OperacaoIncompleta(mensagem)


def _alvo(c, tabela, id_alvo):
    # Tabelas sao constantes internas, nunca dados da requisicao.
    linhas = _linhas(c, f'SELECT * FROM {tabela} WHERE id=?', (id_alvo,))
    _exigir(len(linhas) == 1, 'Referencia de efeito inexistente')
    return linhas[0]


def _conferir_evento(evento, p, req):
    _exigir(evento['id'] > 0 and evento['origem_tipo'] == 'manual' and
            evento['situacao_competencia'] == 'confirmada' and
            evento['chave_origem'] == 'manual:' + req.chave + ':evento:0')
    for campo in ('tipo', 'descricao', 'categoria_id', 'valor_centavos',
                  'data_competencia', 'data_vencimento'):
        _exigir(evento[campo] == p[campo])
    _exigir(all(evento[k] is None for k in ('compra_cartao_id', 'parcelamento_id',
                 'parcela_comum_id', 'ocorrencia_id', 'lancamento_legado_id')))


def _recuperar_recibo(c, req, op_id):
    """Confere efeitos originais imutaveis, nao saldo/classificacao correntes."""
    p = json.loads(req.requisicao_canonica)['parametros']
    e = _ler_efeitos(c, op_id)
    grupos = (e.eventos, e.lancamentos, e.liquidacoes, e.estornos, e.reversoes, e.reclassificacoes)
    perfis = {'registrar_evento': (1, 0, 0, 0, 0, 0), 'registrar_imediata': (1, 1, 1, 0, 0, 0),
              'liquidar_evento': (0, 1, 1, 0, 0, 0), 'estornar_liquidacao': (0, 1, 0, 1, 0, 0),
              'reverter_evento': (0, 0, 0, 0, 1, 0), 'reclassificar_evento': (0, 0, 0, 0, 0, 1)}
    _exigir(tuple(map(len, grupos)) == perfis[req.tipo_operacao])
    if e.eventos:
        evento = e.eventos[0]
        _conferir_evento(evento, p, req)
    elif e.estornos:
        q = _alvo(c, 'liquidacoes_eventos', p['liquidacao_id'])
        evento = _alvo(c, 'eventos_financeiros', q['evento_id'])
    else:
        evento = _alvo(c, 'eventos_financeiros', p['evento_id'])
    _exigir(evento['origem_tipo'] == 'manual' and evento['situacao_competencia'] == 'confirmada')
    _exigir(evento['id'] > 0 and type(evento['valor_centavos']) is int and
            1 <= evento['valor_centavos'] <= MAX_CENTAVOS)
    def categoria_compativel(categoria_id):
        return c.execute('SELECT tipo FROM categorias WHERE id=?', (categoria_id,)).fetchone() == (evento['tipo'],)
    _exigir(categoria_compativel(evento['categoria_id']))
    if e.lancamentos:
        l = e.lancamentos[0]
        negativo = req.tipo_operacao == 'estornar_liquidacao'
        valor = p['valor_centavos'] * (-1 if negativo else 1)
        data_caixa = p['data_estorno'] if negativo else p['data_liquidacao']
        _exigir(l['id'] > 0 and l['tipo'] == evento['tipo'] and l['valor_centavos'] == valor and
                l['data'] == data_caixa and l['recorrencia_id'] is None and l['parcelamento_id'] is None)
        _exigir(c.execute('SELECT valor = CAST(valor_centavos AS REAL)/100.0 FROM lancamentos WHERE id=?',
                         (l['id'],)).fetchone() == (1,))
        _exigir(categoria_compativel(l['categoria_id']))
        confirmar_datas(interpretar_data_iso(evento['data_competencia']),
                        interpretar_data_iso(data_caixa), p['confirmar_datas_divergentes'])
        if req.tipo_operacao == 'registrar_imediata':
            _exigir(l['descricao'] == p['descricao'] and l['categoria_id'] == evento['categoria_id'])
        elif not negativo:
            _exigir(l['descricao'] == (p['descricao_caixa'] if p['descricao_caixa'] is not None else evento['descricao']))
        if e.liquidacoes:
            q = e.liquidacoes[0]
            _exigir(q['evento_id'] == evento['id'] and q['lancamento_id'] == l['id'] and
                    q['valor_centavos'] == valor)
        if e.estornos:
            s = e.estornos[0]
            _exigir(l['descricao'] == _descricao_estorno_v1(p['liquidacao_id'], p['natureza'], p['motivo']))
            original = _alvo(c, 'lancamentos', q['lancamento_id'])
            _exigir(s['liquidacao_id'] == q['id'] and s['lancamento_estorno_id'] == l['id'] and
                    s['natureza'] == p['natureza'] and s['motivo'] == p['motivo'])
            _exigir(all(l[k] == original[k] for k in ('tipo', 'categoria_id', 'categoria')))
            _exigir((p['natureza'] == 'devolucao_real' and l['data'] >= original['data']) or
                    (p['natureza'] == 'correcao_registro' and l['data'] == original['data']))
    if e.reversoes:
        r = e.reversoes[0]
        _exigir(r['id'] > 0 and r['operacao_hibrida_id'] == op_id and
                r['evento_id'] == evento['id'] and r['data_competencia'] == p['data_reversao'] and
                r['motivo'] == p['motivo'] and categoria_compativel(r['categoria_id']))
    if e.reclassificacoes:
        r = e.reclassificacoes[0]
        _exigir(r['id'] > 0 and r['operacao_hibrida_id'] == op_id and
                r['evento_id'] == evento['id'] and r['categoria_nova_id'] == p['categoria_nova_id'] and
                r['motivo'] == p['motivo'] and categoria_compativel(r['categoria_nova_id']) and
                categoria_compativel(r['categoria_anterior_id']))
        anterior = c.execute('SELECT categoria_nova_id FROM reclassificacoes_eventos '
                             'WHERE evento_id=? AND id<? ORDER BY id DESC LIMIT 1',
                             (evento['id'], r['id'])).fetchone()
        _exigir(r['categoria_anterior_id'] == (anterior[0] if anterior else evento['categoria_id']))
        if p['categoria_anterior_esperada_id'] is not None:
            _exigir(r['categoria_anterior_id'] == p['categoria_anterior_esperada_id'])
    # Recupera somente identidades, nao dados mutaveis da visao corrente.
    ids = [tuple(linha['id'] for linha in grupo) for grupo in grupos]
    ids[0] = (evento['id'],)
    if e.estornos:
        ids[2] = (q['id'],)
    return ResultadoOperacao(op_id, req.chave, req.tipo_operacao, *ids)


def _buscar_operacao(c, req):
    linha = c.execute('SELECT id,chave,tipo,requisicao_canonica,estado FROM operacoes_hibridas WHERE chave=?',
                     (req.chave,)).fetchone()
    if linha is None:
        return None
    op = OperacaoPersistida(*linha)
    if (op.tipo, op.requisicao_canonica) != (req.tipo_operacao, req.requisicao_canonica):
        raise ConflitoIdempotencia('Chave ja usada com outra intencao')
    if op.estado != 'concluida':
        raise OperacaoIncompleta('Operacao anterior nao concluida')
    return _recuperar_recibo(c, req, op.id)


def _erro_sqlite(erro):
    codigo = getattr(erro, 'sqlite_errorcode', 0) & 255
    if codigo in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return BancoOcupado('Banco ocupado; repita a intencao com a mesma chave')
    return FalhaPersistencia('Falha SQLite; transacao nao retornou sucesso')


class _UnidadeTrabalho:
    """Uso privado pelos futuros servicos; nenhum produtor financeiro embutido.

    resultado so fica disponivel depois de __exit__ confirmar commit. Acesso
    privado a _conexao serve aos auxiliares; nao e interface de SQL ao usuario.
    """
    def __init__(self, requisicao):
        _conferir_requisicao(requisicao)
        self._req = requisicao
        self._conexao = None
        self._op_id = None
        self._pendente = None
        self._resultado = None
        self._usada = False
        self.anterior = None

    def __enter__(self):
        if self._usada:
            raise OperacaoIncompleta('Unidade transacional nao pode ser reutilizada')
        self._usada = True
        try:
            self._conexao = banco.abrir_conexao()
            for pragma in ('foreign_keys', 'recursive_triggers'):
                self._conexao.execute(f'PRAGMA {pragma}=ON')
                if self._conexao.execute(f'PRAGMA {pragma}').fetchone() != (1,):
                    raise EsquemaIncompativel(f'PRAGMA obrigatorio indisponivel: {pragma}')
            self._conexao.execute('BEGIN IMMEDIATE')
            _verificar_esquema(self._conexao)
            self._max_op = self._conexao.execute('SELECT COALESCE(MAX(id),0) FROM operacoes_hibridas').fetchone()[0]
            self.anterior = _buscar_operacao(self._conexao, self._req)
            return self
        except BaseException as erro:
            self._limpar(erro)
            if isinstance(erro, sqlite3.Error):
                raise _erro_sqlite(erro) from erro
            raise

    def _iniciar_operacao(self):
        if self.anterior is not None or self._op_id is not None:
            raise OperacaoIncompleta('Operacao ja existente nesta unidade')
        if self._max_op == MAX_CENTAVOS:
            raise IdentificadoresEsgotados('IDs de operacao esgotados')
        self._op_id = self._conexao.execute('INSERT INTO operacoes_hibridas '
            '(chave,tipo,requisicao_canonica) VALUES (?,?,?)',
            (self._req.chave, self._req.tipo_operacao, self._req.requisicao_canonica)).lastrowid
        return self._op_id

    def _concluir(self):
        if self._op_id is None or self._pendente is not None:
            raise OperacaoIncompleta('Operacao ausente ou ja fechada')
        recibo = _recuperar_recibo(self._conexao, self._req, self._op_id)
        cursor = self._conexao.execute("UPDATE operacoes_hibridas SET estado='concluida' WHERE id=? AND estado='aberta'",
                                       (self._op_id,))
        _exigir(cursor.rowcount == 1, 'Operacao nao estava aberta')
        self._pendente = recibo

    @property
    def resultado(self):
        if self._resultado is None:
            raise OperacaoIncompleta('Resultado indisponivel antes do commit')
        return self._resultado

    def _limpar(self, original):
        if self._conexao is None:
            return
        try:
            if self._conexao.in_transaction:
                self._conexao.rollback()
        except BaseException as erro:
            original.add_note(f'Falha adicional no rollback: {erro!r}')
        finally:
            try:
                self._conexao.close()
            except BaseException as erro:
                original.add_note(f'Falha adicional no fechamento: {erro!r}')

    def __exit__(self, tipo, erro, traceback):
        if erro is not None:
            self._limpar(erro)
            if isinstance(erro, sqlite3.Error):
                raise _erro_sqlite(erro) from erro
            return False
        try:
            _exigir(self._conexao.in_transaction, 'Transacao encerrada fora do controlador')
            if self.anterior is not None:
                _exigir(self._conexao.total_changes == 0, 'Replay nao pode escrever')
                recibo = self.anterior
            else:
                _exigir(self._pendente is not None, 'Operacao nao foi concluida')
                recibo = _recuperar_recibo(self._conexao, self._req, self._op_id)
                _exigir(recibo == self._pendente)
                _exigir(not self._conexao.execute("SELECT 1 FROM operacoes_hibridas WHERE id>? AND estado='aberta'",
                                                  (self._max_op,)).fetchone(), 'Operacao aberta na transacao')
            self._conexao.commit()
        except BaseException as falha:
            self._limpar(falha)
            if isinstance(falha, sqlite3.Error):
                raise _erro_sqlite(falha) from falha
            raise
        # Falha de close apos commit nao implica rollback de algo ja confirmado.
        try:
            self._conexao.close()
        except sqlite3.Error as falha:
            raise FalhaPersistencia('Commit pode ter ocorrido; recupere pela mesma chave') from falha
        self._resultado = recibo
        return False


def registrar_evento_manual(
    *,
    chave: str,
    tipo: TipoEconomico,
    descricao: str,
    categoria_id: int,
    valor_centavos: int,
    data_competencia: date,
    data_vencimento: date,
    confirmar_ocorrencia: bool,
) -> ResultadoOperacao:
    """Registra exatamente uma competencia manual confirmada, sem caixa.

    Validacao estatica precede a abertura; categoria e capacidade de IDs sao
    conferidas sob BEGIN IMMEDIATE somente para uma intencao nova. O controlador
    existente recupera replay, confere os efeitos e confirma ou reverte tudo.
    """
    req = canonicalizar_requisicao(
        'registrar_evento_manual', chave=chave, tipo=tipo, descricao=descricao,
        categoria_id=categoria_id, valor_centavos=valor_centavos,
        data_competencia=data_competencia, data_vencimento=data_vencimento,
        confirmar_ocorrencia=confirmar_ocorrencia,
    )
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            categoria = c.execute('SELECT tipo FROM categorias WHERE id=?',
                                  (p['categoria_id'],)).fetchone()
            if categoria is None:
                raise CategoriaInexistente('Categoria nao encontrada')
            if categoria[0] != p['tipo']:
                raise CategoriaIncompativel('Categoria e evento devem ter o mesmo tipo')
            maior_id = c.execute('SELECT MAX(id) FROM eventos_financeiros').fetchone()[0]
            if maior_id == MAX_CENTAVOS:
                raise IdentificadoresEsgotados('IDs de evento esgotados')
            # PK compartilhada nao e AUTOINCREMENT. Com historico somente nao
            # positivo, solicitar ID automatico pode atribuir zero/negativo.
            novo_id = 1 if maior_id is not None and maior_id <= 0 else None
            operacao_id = unidade._iniciar_operacao()
            cursor = c.execute('''INSERT INTO eventos_financeiros
                (id,tipo,descricao,categoria_id,valor_centavos,data_competencia,
                 situacao_competencia,chave_origem,operacao_hibrida_id,
                 data_vencimento,origem_tipo)
                VALUES (?,?,?,?,?,?,'confirmada',?,?,?,'manual')''',
                (novo_id, p['tipo'], p['descricao'], p['categoria_id'], p['valor_centavos'],
                 p['data_competencia'], 'manual:' + req.chave + ':evento:0',
                 operacao_id, p['data_vencimento']))
            _exigir(cursor.rowcount == 1, 'Evento manual nao foi inserido')
            unidade._concluir()
    return unidade.resultado


def _id_positivo_para_insercao(c, tabela):
    """Preserva o alocador nativo, exceto o caso nao positivo sem AUTOINCREMENT.

    Chamado sob BEGIN IMMEDIATE, com nomes internos fechados. Nunca calcula
    MAX(id)+1 nem reescreve registros/seq. Tabelas AUTOINCREMENT preservam seu
    high-water mark, inclusive quando o maior registro anterior foi excluido.
    """
    if tabela not in ('eventos_financeiros', 'lancamentos', 'liquidacoes_eventos',
                      'estornos_liquidacoes', 'reversoes_eventos', 'reclassificacoes_eventos'):
        raise ParametroInvalido('Tabela de identificadores nao suportada')
    maior = c.execute(f'SELECT MAX(id) FROM {tabela}').fetchone()[0]
    if maior == MAX_CENTAVOS:
        raise IdentificadoresEsgotados(f'IDs esgotados: {tabela}')
    if tabela in ('lancamentos', 'reclassificacoes_eventos'):
        sequencia = c.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (tabela,)).fetchone()
        if sequencia and sequencia[0] >= MAX_CENTAVOS:
            raise IdentificadoresEsgotados(f'Sequencia de {tabela} esgotada')
        return None
    return 1 if maior is not None and maior <= 0 else None


def registrar_operacao_imediata(
    *,
    chave: str,
    tipo: TipoEconomico,
    descricao: str,
    categoria_id: int,
    valor_centavos: int,
    data_competencia: date,
    data_vencimento: date,
    data_liquidacao: date,
    confirmar_ocorrencia: bool,
    confirmar_datas_divergentes: bool,
) -> ResultadoOperacao:
    """Cria competencia, caixa positivo e conciliacao integral atomicamente.

    Centavos inteiros sao autoritativos. REAL e apenas projecao SQL para os
    leitores legados. Nenhum servico publico e chamado dentro da transacao.
    """
    req = canonicalizar_requisicao(
        'registrar_operacao_imediata', chave=chave, tipo=tipo, descricao=descricao,
        categoria_id=categoria_id, valor_centavos=valor_centavos,
        data_competencia=data_competencia, data_vencimento=data_vencimento,
        data_liquidacao=data_liquidacao, confirmar_ocorrencia=confirmar_ocorrencia,
        confirmar_datas_divergentes=confirmar_datas_divergentes,
    )
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            categoria = c.execute('SELECT nome,tipo FROM categorias WHERE id=?',
                                  (p['categoria_id'],)).fetchone()
            if categoria is None:
                raise CategoriaInexistente('Categoria nao encontrada')
            if categoria[1] != p['tipo']:
                raise CategoriaIncompativel('Categoria e evento devem ter o mesmo tipo')
            id_evento = _id_positivo_para_insercao(c, 'eventos_financeiros')
            id_caixa = _id_positivo_para_insercao(c, 'lancamentos')
            id_liquidacao = _id_positivo_para_insercao(c, 'liquidacoes_eventos')
            operacao_id = unidade._iniciar_operacao()
            cursor = c.execute('''INSERT INTO eventos_financeiros
                (id,tipo,descricao,categoria_id,valor_centavos,data_competencia,
                 situacao_competencia,chave_origem,operacao_hibrida_id,
                 data_vencimento,origem_tipo)
                VALUES (?,?,?,?,?,?,'confirmada',?,?,?,'manual')''',
                (id_evento, p['tipo'], p['descricao'], p['categoria_id'], p['valor_centavos'],
                 p['data_competencia'], 'manual:' + req.chave + ':evento:0',
                 operacao_id, p['data_vencimento']))
            _exigir(cursor.rowcount == 1, 'Evento imediato nao foi inserido')
            evento_id = cursor.lastrowid
            cursor = c.execute('''INSERT INTO lancamentos
                (id,data,descricao,tipo,categoria,categoria_id,valor_centavos,valor,operacao_hibrida_id)
                VALUES (?,?,?,?,?,?,?,CAST(? AS REAL)/100.0,?)''',
                (id_caixa, p['data_liquidacao'], p['descricao'], p['tipo'], categoria[0],
                 p['categoria_id'], p['valor_centavos'], p['valor_centavos'], operacao_id))
            _exigir(cursor.rowcount == 1, 'Caixa imediato nao foi inserido')
            lancamento_id = cursor.lastrowid
            cursor = c.execute('''INSERT INTO liquidacoes_eventos
                (id,evento_id,lancamento_id,valor_centavos) VALUES (?,?,?,?)''',
                (id_liquidacao, evento_id, lancamento_id, p['valor_centavos']))
            _exigir(cursor.rowcount == 1, 'Liquidacao integral nao foi inserida')
            unidade._concluir()
    return unidade.resultado


def _descricao_estorno_v1(liquidacao_id, natureza, motivo):
    """Regra imutavel da versao 1; entradas ja canonicalizadas."""
    return f'Estorno L#{liquidacao_id} [{natureza}]: {motivo}'


def estornar_liquidacao(
    *,
    chave: str,
    liquidacao_id: int,
    valor_centavos: int,
    natureza: NaturezaEstorno,
    motivo: str,
    data_estorno: date,
    confirmar_datas_divergentes: bool,
) -> ResultadoOperacao:
    """Cria um contramovimento e seu vinculo, sem alterar os efeitos originais."""
    _identificador(liquidacao_id)
    if liquidacao_id <= 0:
        raise ParametroInvalido('liquidacao_id deve ser positivo')
    req = canonicalizar_requisicao('estornar_liquidacao', chave=chave,
        liquidacao_id=liquidacao_id, valor_centavos=valor_centavos, natureza=natureza,
        motivo=motivo, data_estorno=data_estorno,
        confirmar_datas_divergentes=confirmar_datas_divergentes)
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            linhas = _linhas(c, 'SELECT * FROM liquidacoes_eventos WHERE id=?', (liquidacao_id,))
            if not linhas:
                raise LiquidacaoInexistente('Liquidacao nao encontrada')
            q = linhas[0]
            evento = _alvo(c, 'eventos_financeiros', q['evento_id'])
            if (evento['id'] <= 0 or evento['origem_tipo'] != 'manual' or
                    evento['situacao_competencia'] != 'confirmada' or
                    evento['tipo'] not in ('receita', 'despesa') or
                    type(evento['valor_centavos']) is not int or
                    not 1 <= evento['valor_centavos'] <= MAX_CENTAVOS):
                raise EventoNaoElegivel('Evento deve ser manual confirmado do fluxo hibrido')
            if c.execute('SELECT 1 FROM reversoes_eventos WHERE evento_id=?', (evento['id'],)).fetchone():
                raise EventoRevertido('Evento ja revertido')
            op = _alvo(c, 'operacoes_hibridas', evento['operacao_hibrida_id'])
            _exigir(op['estado'] == 'concluida' and op['tipo'] in
                    ('registrar_evento', 'registrar_imediata'), 'Operacao do evento inconsistente')
            _exigir(all(evento[k] is None for k in ('compra_cartao_id', 'parcelamento_id',
                     'parcela_comum_id', 'ocorrencia_id', 'lancamento_legado_id')),
                    'Origens incompatíveis no evento manual')
            _exigir(c.execute('SELECT tipo FROM categorias WHERE id=?', (evento['categoria_id'],)).fetchone()
                    == (evento['tipo'],), 'Categoria original do evento inconsistente')
            try:
                competencia = interpretar_data_iso(evento['data_competencia'])
                interpretar_data_iso(evento['data_vencimento'])
                normalizar_texto(evento['descricao'])
            except ParametroInvalido as erro:
                raise OperacaoIncompleta('Dados originais do evento inconsistentes') from erro
            # Valida o grafo necessario, incluindo referencias sem JOIN, sinais,
            # classificacoes, capacidade do caixa e limites acumulados em int Python.
            _saldo_aberto_validado(c, evento)
            original = _alvo(c, 'lancamentos', q['lancamento_id'])
            estornavel = q['valor_centavos']
            for s in _linhas(c, 'SELECT * FROM estornos_liquidacoes WHERE liquidacao_id=?', (liquidacao_id,)):
                estornavel += _alvo(c, 'lancamentos', s['lancamento_estorno_id'])['valor_centavos']
            _exigir(type(estornavel) is int and 0 <= estornavel <= q['valor_centavos'],
                    'Saldo estornavel inconsistente')
            if p['valor_centavos'] > estornavel:
                raise EstornoExcessivo('Valor solicitado excede o saldo estornavel')
            data_original = interpretar_data_iso(original['data'])
            if ((p['natureza'] == 'devolucao_real' and data_estorno < data_original) or
                    (p['natureza'] == 'correcao_registro' and data_estorno != data_original)):
                raise DataInvalida('Data incompativel com a natureza do estorno')
            confirmar_datas(competencia, data_estorno, confirmar_datas_divergentes)
            id_caixa = _id_positivo_para_insercao(c, 'lancamentos')
            id_estorno = _id_positivo_para_insercao(c, 'estornos_liquidacoes')
            op_id = unidade._iniciar_operacao()
            negativo = -p['valor_centavos']
            cursor = c.execute('''INSERT INTO lancamentos
                (id,data,descricao,tipo,categoria,categoria_id,valor_centavos,valor,operacao_hibrida_id)
                VALUES (?,?,?,?,?,?,?,CAST(? AS REAL)/100.0,?)''',
                (id_caixa, p['data_estorno'], _descricao_estorno_v1(liquidacao_id, p['natureza'], p['motivo']),
                 original['tipo'], original['categoria'], original['categoria_id'], negativo, negativo, op_id))
            _exigir(cursor.rowcount == 1, 'Caixa de estorno nao inserido')
            cursor = c.execute('''INSERT INTO estornos_liquidacoes
                (id,liquidacao_id,lancamento_estorno_id,natureza,motivo) VALUES (?,?,?,?,?)''',
                (id_estorno, liquidacao_id, cursor.lastrowid, p['natureza'], p['motivo']))
            _exigir(cursor.rowcount == 1, 'Estorno nao inserido')
            unidade._concluir()
    return unidade.resultado


def reverter_evento(
    *,
    chave: str,
    evento_id: int,
    data_reversao: date,
    motivo: str,
) -> ResultadoOperacao:
    """Compensa integralmente a competencia, sem produzir movimento de caixa."""
    _identificador(evento_id)
    if evento_id <= 0:
        raise ParametroInvalido('evento_id deve ser positivo')
    req = canonicalizar_requisicao('reverter_evento', chave=chave, evento_id=evento_id,
        data_reversao=data_reversao, motivo=motivo)
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            linhas = _linhas(c, 'SELECT * FROM eventos_financeiros WHERE id=?', (evento_id,))
            if not linhas:
                raise EventoInexistente('Evento nao encontrado')
            evento = linhas[0]
            if (evento['origem_tipo'] != 'manual' or evento['situacao_competencia'] != 'confirmada' or
                    evento['tipo'] not in ('receita', 'despesa') or
                    type(evento['valor_centavos']) is not int or
                    not 1 <= evento['valor_centavos'] <= MAX_CENTAVOS):
                raise EventoNaoElegivel('Evento deve ser manual confirmado do fluxo hibrido')
            if c.execute('SELECT 1 FROM reversoes_eventos WHERE evento_id=?', (evento_id,)).fetchone():
                raise EventoJaRevertido('Evento ja revertido')
            op = _alvo(c, 'operacoes_hibridas', evento['operacao_hibrida_id'])
            _exigir(op['estado'] == 'concluida' and op['tipo'] in
                    ('registrar_evento', 'registrar_imediata'), 'Operacao do evento inconsistente')
            _exigir(all(evento[k] is None for k in ('compra_cartao_id', 'parcelamento_id',
                     'parcela_comum_id', 'ocorrencia_id', 'lancamento_legado_id')),
                    'Origens incompatíveis no evento manual')
            categoria_id = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                                      (evento_id,)).fetchone()[0]
            categoria = c.execute('SELECT tipo FROM categorias WHERE id=?', (categoria_id,)).fetchone()
            if categoria is None:
                raise CategoriaInexistente('Categoria corrente nao encontrada')
            if categoria[0] != evento['tipo']:
                raise CategoriaIncompativel('Categoria corrente e evento devem ter o mesmo tipo')
            _exigir(c.execute('SELECT tipo FROM categorias WHERE id=?', (evento['categoria_id'],)).fetchone()
                    == (evento['tipo'],), 'Categoria original do evento inconsistente')
            try:
                interpretar_data_iso(evento['data_competencia'])
                interpretar_data_iso(evento['data_vencimento'])
                normalizar_texto(evento['descricao'])
            except ParametroInvalido as erro:
                raise OperacaoIncompleta('Dados originais do evento inconsistentes') from erro
            # Cada liquidacao deve ser consistente individualmente: nao permitir
            # que um estorno excessivo compense outra liquidacao ainda ativa.
            saldo_aberto = _saldo_aberto_validado(c, evento)
            liquidado_liquido = evento['valor_centavos'] - saldo_aberto
            if liquidado_liquido != 0:
                raise EventoAindaLiquidado('Evento possui liquidacao liquida positiva')
            id_reversao = _id_positivo_para_insercao(c, 'reversoes_eventos')
            op_id = unidade._iniciar_operacao()
            cursor = c.execute('''INSERT INTO reversoes_eventos
                (id,evento_id,operacao_hibrida_id,data_competencia,categoria_id,motivo)
                VALUES (?,?,?,?,?,?)''',
                (id_reversao, evento_id, op_id, p['data_reversao'], categoria_id, p['motivo']))
            _exigir(cursor.rowcount == 1, 'Reversao nao inserida')
            # A categoria capturada e conferida somente na criacao. Replay le o
            # registro imutavel, sem depender da classificacao corrente do evento.
            reversao = _alvo(c, 'reversoes_eventos', cursor.lastrowid)
            _exigir(reversao['categoria_id'] == categoria_id, 'Categoria da reversao divergente')
            unidade._concluir()
    return unidade.resultado


def reclassificar_evento(
    *,
    chave: str,
    evento_id: int,
    categoria_nova_id: int,
    motivo: str,
    categoria_anterior_esperada_id: int | None = None,
) -> ResultadoOperacao:
    """Registra a nova classificacao sem atualizar evento ou caixa historicos."""
    _identificador(evento_id)
    if evento_id <= 0:
        raise ParametroInvalido('evento_id deve ser positivo')
    req = canonicalizar_requisicao('reclassificar_evento', chave=chave, evento_id=evento_id,
        categoria_nova_id=categoria_nova_id, motivo=motivo,
        categoria_anterior_esperada_id=categoria_anterior_esperada_id)
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            linhas = _linhas(c, 'SELECT * FROM eventos_financeiros WHERE id=?', (evento_id,))
            if not linhas:
                raise EventoInexistente('Evento nao encontrado')
            evento = linhas[0]
            if (evento['origem_tipo'] != 'manual' or evento['situacao_competencia'] != 'confirmada' or
                    evento['tipo'] not in ('receita', 'despesa') or
                    type(evento['valor_centavos']) is not int or
                    not 1 <= evento['valor_centavos'] <= MAX_CENTAVOS):
                raise EventoNaoElegivel('Evento deve ser manual confirmado do fluxo hibrido')
            if c.execute('SELECT 1 FROM reversoes_eventos WHERE evento_id=?', (evento_id,)).fetchone():
                raise EventoRevertido('Evento ja revertido')
            op = _alvo(c, 'operacoes_hibridas', evento['operacao_hibrida_id'])
            _exigir(op['estado'] == 'concluida' and op['tipo'] in
                    ('registrar_evento', 'registrar_imediata'), 'Operacao do evento inconsistente')
            _exigir(all(evento[k] is None for k in ('compra_cartao_id', 'parcelamento_id',
                     'parcela_comum_id', 'ocorrencia_id', 'lancamento_legado_id')),
                    'Origens incompatíveis no evento manual')
            try:
                interpretar_data_iso(evento['data_competencia'])
                interpretar_data_iso(evento['data_vencimento'])
                normalizar_texto(evento['descricao'])
            except ParametroInvalido as erro:
                raise OperacaoIncompleta('Dados originais do evento inconsistentes') from erro
            anterior_id = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                                     (evento_id,)).fetchone()[0]
            for id_categoria in (anterior_id, p['categoria_nova_id']):
                categoria = c.execute('SELECT tipo FROM categorias WHERE id=?', (id_categoria,)).fetchone()
                if categoria is None:
                    raise CategoriaInexistente('Categoria nao encontrada')
                if categoria[0] != evento['tipo']:
                    raise CategoriaIncompativel('Categorias e evento devem ter o mesmo tipo')
            _exigir(c.execute('SELECT tipo FROM categorias WHERE id=?', (evento['categoria_id'],)).fetchone()
                    == (evento['tipo'],), 'Categoria original do evento inconsistente')
            if p['categoria_anterior_esperada_id'] is not None and p['categoria_anterior_esperada_id'] != anterior_id:
                raise ConflitoEstado('Categoria corrente difere da esperada')
            if p['categoria_nova_id'] == anterior_id:
                raise ReclassificacaoSemAlteracao('Categoria nova ja e a corrente')
            ultimo_id = c.execute('SELECT MAX(id) FROM reclassificacoes_eventos WHERE evento_id=?',
                                  (evento_id,)).fetchone()[0]
            # Esta tabela tem AUTOINCREMENT: somente verificar capacidade,
            # deixar SQLite atribuir o ID e preservar seu high-water mark.
            _id_positivo_para_insercao(c, 'reclassificacoes_eventos')
            op_id = unidade._iniciar_operacao()
            cursor = c.execute('''INSERT INTO reclassificacoes_eventos
                (evento_id,operacao_hibrida_id,categoria_anterior_id,categoria_nova_id,motivo)
                VALUES (?,?,?,?,?)''',
                (evento_id, op_id, anterior_id, p['categoria_nova_id'], p['motivo']))
            _exigir(cursor.rowcount == 1, 'Reclassificacao nao inserida')
            _exigir(type(cursor.lastrowid) is int and cursor.lastrowid > 0 and
                    (ultimo_id is None or cursor.lastrowid > ultimo_id), 'Sequencia de reclassificacao invalida')
            historico = _alvo(c, 'reclassificacoes_eventos', cursor.lastrowid)
            _exigir(historico['categoria_anterior_id'] == anterior_id, 'Categoria anterior divergente')
            _exigir(c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                             (evento_id,)).fetchone() == (p['categoria_nova_id'],), 'Classificacao corrente divergente')
            unidade._concluir()
    return unidade.resultado


def _saldo_aberto_validado(c, evento):
    """Le somente o grafo necessario ao saldo, sem JOIN que esconda orfaos.

    OperacaoIncompleta sinaliza dados relacionados inconsistentes. Somas usam
    int Python (inclusive para detectar excessos int64 sem overflow/REAL).
    Nao reinterpreta caixa legado nem repara registros. Uso somente sob lock.
    """
    caixas = {}

    def caixa(id_caixa, negativo=False):
        chave = (id_caixa, negativo)
        if chave in caixas:
            return caixas[chave]
        l = _alvo(c, 'lancamentos', id_caixa)
        valor = l['valor_centavos']
        _exigir(type(l['id']) is int and l['id'] > 0 and type(valor) is int and
                (1 <= -valor <= MAX_CENTAVOS if negativo else 1 <= valor <= MAX_CENTAVOS),
                'Sinal ou valor de caixa inconsistente')
        _exigir(l['tipo'] == evento['tipo'] and l['recorrencia_id'] is None and
                l['parcelamento_id'] is None, 'Tipo ou origem do caixa inconsistente')
        _exigir(c.execute('SELECT tipo FROM categorias WHERE id=?', (l['categoria_id'],)).fetchone()
                == (evento['tipo'],), 'Categoria historica do caixa inconsistente')
        op = _alvo(c, 'operacoes_hibridas', l['operacao_hibrida_id'])
        tipos = ('estornar_liquidacao',) if negativo else ('registrar_imediata', 'liquidar_evento')
        _exigir(op['estado'] == 'concluida' and op['tipo'] in tipos,
                'Operacao do caixa nao concluida ou incompativel')
        _exigir(c.execute('SELECT valor=CAST(valor_centavos AS REAL)/100.0 FROM lancamentos WHERE id=?',
                         (id_caixa,)).fetchone() == (1,), 'Projecao de caixa inconsistente')
        try:
            interpretar_data_iso(l['data'])
        except DataInvalida as erro:
            raise OperacaoIncompleta('Data historica do caixa inconsistente') from erro
        caixas[chave] = l
        return l

    total_liquido = 0
    alocacoes_conferidas = set()
    for q in _linhas(c, 'SELECT * FROM liquidacoes_eventos WHERE evento_id=? ORDER BY id', (evento['id'],)):
        _exigir(q['id'] > 0 and type(q['valor_centavos']) is int and
                1 <= q['valor_centavos'] <= evento['valor_centavos'], 'Liquidacao original inconsistente')
        original = caixa(q['lancamento_id'])
        if original['id'] not in alocacoes_conferidas:
            alocado = 0
            for outra in _linhas(c, 'SELECT * FROM liquidacoes_eventos WHERE lancamento_id=?', (original['id'],)):
                _exigir(outra['id'] > 0 and type(outra['valor_centavos']) is int and
                        1 <= outra['valor_centavos'] <= MAX_CENTAVOS, 'Alocacao de caixa inconsistente')
                alvo = _alvo(c, 'eventos_financeiros', outra['evento_id'])
                _exigir(alvo['origem_tipo'] == 'manual' and alvo['situacao_competencia'] == 'confirmada'
                        and alvo['tipo'] == original['tipo'], 'Destino da alocacao inconsistente')
                alocado += outra['valor_centavos']
            _exigir(alocado <= original['valor_centavos'], 'Caixa original superalocado')
            alocacoes_conferidas.add(original['id'])
        estornado = 0
        for s in _linhas(c, 'SELECT * FROM estornos_liquidacoes WHERE liquidacao_id=? ORDER BY id', (q['id'],)):
            retorno = caixa(s['lancamento_estorno_id'], negativo=True)
            _exigir(s['id'] > 0 and all(retorno[k] == original[k]
                    for k in ('tipo', 'categoria_id', 'categoria')), 'Classificacao de estorno inconsistente')
            _exigir((s['natureza'] == 'devolucao_real' and retorno['data'] >= original['data']) or
                    (s['natureza'] == 'correcao_registro' and retorno['data'] == original['data']),
                    'Natureza ou data de estorno inconsistente')
            _exigir(not c.execute('SELECT 1 FROM liquidacoes_eventos WHERE lancamento_id=?',
                                  (retorno['id'],)).fetchone(), 'Caixa negativo usado como liquidacao')
            estornado += -retorno['valor_centavos']
        _exigir(estornado <= q['valor_centavos'], 'Estornos excedem liquidacao original')
        total_liquido += q['valor_centavos'] - estornado
    _exigir(0 <= total_liquido <= evento['valor_centavos'], 'Saldo liquidado inconsistente')
    return evento['valor_centavos'] - total_liquido


def liquidar_evento(
    *,
    chave: str,
    evento_id: int,
    valor_centavos: int,
    data_liquidacao: date,
    confirmar_datas_divergentes: bool,
    descricao_caixa: str | None = None,
) -> ResultadoOperacao:
    """Liquida parcial/integralmente um evento sem criar nova competencia."""
    _identificador(evento_id)
    if evento_id <= 0:
        raise ParametroInvalido('evento_id deve ser positivo')
    req = canonicalizar_requisicao('liquidar_evento', chave=chave, evento_id=evento_id,
        valor_centavos=valor_centavos, data_liquidacao=data_liquidacao,
        confirmar_datas_divergentes=confirmar_datas_divergentes, descricao_caixa=descricao_caixa)
    p = json.loads(req.requisicao_canonica)['parametros']
    with _UnidadeTrabalho(req) as unidade:
        if unidade.anterior is None:
            c = unidade._conexao
            linhas = _linhas(c, 'SELECT * FROM eventos_financeiros WHERE id=?', (evento_id,))
            if not linhas:
                raise EventoInexistente('Evento nao encontrado')
            evento = linhas[0]
            if (evento['origem_tipo'] != 'manual' or evento['situacao_competencia'] != 'confirmada' or
                    evento['tipo'] not in ('receita', 'despesa') or
                    type(evento['valor_centavos']) is not int or not 1 <= evento['valor_centavos'] <= MAX_CENTAVOS):
                raise EventoNaoElegivel('Evento deve ser manual, confirmado e com valor positivo')
            op_evento = _alvo(c, 'operacoes_hibridas', evento['operacao_hibrida_id'])
            _exigir(op_evento['estado'] == 'concluida' and op_evento['tipo'] in
                    ('registrar_evento', 'registrar_imediata'), 'Operacao de competencia inconsistente')
            if c.execute('SELECT 1 FROM reversoes_eventos WHERE evento_id=?', (evento_id,)).fetchone():
                raise EventoRevertido('Evento ja revertido')
            categoria_id = c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?',
                                     (evento_id,)).fetchone()[0]
            categoria = c.execute('SELECT nome,tipo FROM categorias WHERE id=?', (categoria_id,)).fetchone()
            if categoria is None:
                raise CategoriaInexistente('Categoria corrente nao encontrada')
            if categoria[1] != evento['tipo']:
                raise CategoriaIncompativel('Categoria corrente e evento devem ter o mesmo tipo')
            _exigir(c.execute('SELECT tipo FROM categorias WHERE id=?', (evento['categoria_id'],)).fetchone()
                    == (evento['tipo'],), 'Categoria original do evento inconsistente')
            _exigir(all(evento[k] is None for k in ('compra_cartao_id', 'parcelamento_id',
                    'parcela_comum_id', 'ocorrencia_id', 'lancamento_legado_id')),
                    'Origens incompatíveis no evento manual')
            try:
                competencia = interpretar_data_iso(evento['data_competencia'])
                interpretar_data_iso(evento['data_vencimento'])
                normalizar_texto(evento['descricao'])  # Valida sem substituir a descricao imutavel.
            except ParametroInvalido as erro:
                raise OperacaoIncompleta('Dados originais do evento inconsistentes') from erro
            confirmar_datas(competencia, data_liquidacao, confirmar_datas_divergentes)
            saldo = _saldo_aberto_validado(c, evento)
            if p['valor_centavos'] > saldo:
                raise SaldoInsuficiente('Valor solicitado excede o saldo aberto do evento')
            id_caixa = _id_positivo_para_insercao(c, 'lancamentos')
            id_liquidacao = _id_positivo_para_insercao(c, 'liquidacoes_eventos')
            op_id = unidade._iniciar_operacao()
            descricao = evento['descricao'] if p['descricao_caixa'] is None else p['descricao_caixa']
            cursor = c.execute('''INSERT INTO lancamentos
                (id,data,descricao,tipo,categoria,categoria_id,valor_centavos,valor,operacao_hibrida_id)
                VALUES (?,?,?,?,?,?,?,CAST(? AS REAL)/100.0,?)''',
                (id_caixa, p['data_liquidacao'], descricao, evento['tipo'], categoria[0], categoria_id,
                 p['valor_centavos'], p['valor_centavos'], op_id))
            _exigir(cursor.rowcount == 1, 'Caixa de liquidacao nao inserido')
            lancamento_id = cursor.lastrowid
            cursor = c.execute('''INSERT INTO liquidacoes_eventos
                (id,evento_id,lancamento_id,valor_centavos) VALUES (?,?,?,?)''',
                (id_liquidacao, evento_id, lancamento_id, p['valor_centavos']))
            _exigir(cursor.rowcount == 1, 'Liquidacao nao inserida')
            unidade._concluir()
    return unidade.resultado
