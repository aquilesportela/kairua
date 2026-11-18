"""Consultas híbridas 3.3C.1, sem escrita ou migração.

Cada chamada usa mode=ro, query_only e um snapshot curto, encerrado antes da
apresentação. Os resultados são imutáveis; elegibilidade é apenas informativa.
O serviço de escrita continua responsável pela validação definitiva sob lock.

A instalação é conferida apenas quanto às versões, colunas e views usadas na
leitura; isto não substitui o manifesto completo dos serviços. Não se utiliza
SUM da view _hibrido_liquidacoes: lemos os vínculos sem esconder órfãos e somamos
inteiros Python, inclusive quando os totais brutos superam int64. REAL é lido
somente pelo SQLite para conferir sua projeção, nunca para calcular saldos.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sqlite3

import banco
import migracao_3
import servicos_financeiros as sf


class ConsultaIndisponivel(sf.ErroFinanceiro):
    """Banco ausente, inacessível ou falha de leitura; nenhum dado foi reparado."""


@dataclass(frozen=True)
class Categoria:
    id: int
    nome: str


@dataclass(frozen=True)
class DetalheEstorno:
    id: int
    liquidacao_id: int
    lancamento_id: int
    operacao_id: int
    valor_centavos: int  # Contramovimento negativo; totais estornados são magnitudes.
    data: date
    natureza: str
    motivo: str
    tipo: str
    categoria_historica: Categoria
    descricao: str


@dataclass(frozen=True)
class DetalheLiquidacao:
    id: int
    evento_id: int
    lancamento_id: int
    operacao_id: int
    valor_original_centavos: int  # Alocação desta liquidação, não o caixa inteiro.
    valor_caixa_centavos: int
    total_estornado_centavos: int
    saldo_estornavel_centavos: int
    data_caixa: date
    tipo: str
    categoria_historica: Categoria
    descricao_caixa: str
    estornos: tuple[DetalheEstorno, ...]
    elegivel_estorno: bool


@dataclass(frozen=True)
class DetalheReversao:
    id: int
    operacao_id: int
    data: date
    motivo: str
    categoria: Categoria


@dataclass(frozen=True)
class DetalheEvento:
    id: int
    tipo: str
    descricao: str
    data_competencia: date
    data_vencimento: date
    categoria_atual: Categoria
    valor_original_centavos: int
    total_liquidado_bruto_centavos: int
    total_estornado_centavos: int
    total_liquidado_liquido_centavos: int
    saldo_aberto_centavos: int
    liquidacoes: tuple[DetalheLiquidacao, ...]
    reversao: DetalheReversao | None


_COLUNAS = {
    'eventos_financeiros': 'id tipo descricao categoria_id valor_centavos data_competencia '
        'situacao_competencia chave_origem compra_cartao_id parcelamento_id parcela_comum_id '
        'ocorrencia_id lancamento_legado_id operacao_hibrida_id data_vencimento origem_tipo',
    'lancamentos': 'id data descricao tipo categoria categoria_id valor valor_centavos '
        'operacao_hibrida_id recorrencia_id parcelamento_id',
    'liquidacoes_eventos': 'id evento_id lancamento_id valor_centavos',
    'estornos_liquidacoes': 'id liquidacao_id lancamento_estorno_id natureza motivo',
    'reversoes_eventos': 'id evento_id operacao_hibrida_id data_competencia categoria_id motivo',
    'reclassificacoes_eventos': 'id evento_id operacao_hibrida_id categoria_anterior_id categoria_nova_id motivo',
    'operacoes_hibridas': 'id chave tipo requisicao_canonica estado',
    'categorias': 'id nome tipo',
}


def _exigir(condicao, mensagem):
    if not condicao:
        raise sf.OperacaoIncompleta(mensagem)


def _inteiro(valor, positivo=False):
    _exigir(type(valor) is int and (1 if positivo else -sf.MAX_CENTAVOS-1) <= valor <= sf.MAX_CENTAVOS,
            'Identificador ou valor inteiro inconsistente.')
    return valor


def _data(valor):
    try:
        return sf.interpretar_data_iso(valor)
    except sf.ParametroInvalido as erro:
        raise sf.OperacaoIncompleta('Data financeira inconsistente.') from erro


def _texto(valor):
    try:
        sf.normalizar_texto(valor)
        return valor
    except sf.ParametroInvalido as erro:
        raise sf.OperacaoIncompleta('Texto financeiro inconsistente.') from erro


def _verificar_esquema(c):
    nomes = {r['name']: r['type'] for r in c.execute('SELECT name,type FROM sqlite_master')}
    if nomes.get('esquema_migracoes') != 'table':
        raise sf.EsquemaIncompativel('Histórico de migrações indisponível.')
    historico = [tuple(r) for r in c.execute('SELECT versao,nome FROM esquema_migracoes ORDER BY versao')]
    if historico != [(m[0], m[1]) for m in banco.MIGRACOES]:
        raise sf.EsquemaIncompativel('Versões do esquema não suportadas pela consulta.')
    for tabela, campos in _COLUNAS.items():
        if nomes.get(tabela) != 'table':
            raise sf.EsquemaIncompativel(f'Tabela necessária ausente: {tabela}.')
        existentes = {r['name'] for r in c.execute(f'PRAGMA table_info("{tabela}")')}
        if not set(campos.split()) <= existentes:
            raise sf.EsquemaIncompativel(f'Colunas incompatíveis: {tabela}.')
    nome = 'eventos_classificacao_atual'
    esperado = next(sql for sql in migracao_3.SQL_MIGRACAO_3 if sql.startswith(f'CREATE VIEW {nome} AS'))
    atual = c.execute('SELECT sql FROM sqlite_master WHERE type=\'view\' AND name=?', (nome,)).fetchone()
    if atual is None or atual['sql'].strip() != esperado.strip():
        raise sf.EsquemaIncompativel('View de classificação corrente incompatível.')


@contextmanager
def _snapshot():
    c = None
    try:
        # as_uri escapa ?, # e caracteres especiais. mode=ro não cria arquivo
        # ausente; não usamos immutable=1, pois o banco pode receber commits.
        uri = Path(banco.obter_caminho_banco()).absolute().as_uri() + '?mode=ro'
        c = sqlite3.connect(uri, uri=True, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')
        _verificar_esquema(c)  # A primeira leitura fixa o snapshot.
        yield _Grafo(c)
    except sqlite3.Error as erro:
        codigo = getattr(erro, 'sqlite_errorcode', 0) & 255
        if codigo in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise sf.BancoOcupado('Consulta temporariamente bloqueada.') from erro
        if 'no such table' in str(erro).lower() or 'no such column' in str(erro).lower():
            raise sf.EsquemaIncompativel('Estrutura necessária à consulta indisponível.') from erro
        raise ConsultaIndisponivel('Não foi possível ler o banco configurado.') from erro
    finally:
        if c is not None:
            try:
                if c.in_transaction:
                    c.rollback()
            finally:
                c.close()


class _Grafo:
    def __init__(self, conexao):
        self.c = conexao
        self.bases = {}
        self.eventos = {}
        self.caixas = {}
        self.liquidacoes = {}
        # Somente estruturas híbridas: não varre FKs de lançamentos legados.
        for tabela, coluna, alvo in (
            ('liquidacoes_eventos', 'evento_id', 'eventos_financeiros'),
            ('liquidacoes_eventos', 'lancamento_id', 'lancamentos'),
            ('estornos_liquidacoes', 'liquidacao_id', 'liquidacoes_eventos'),
            ('estornos_liquidacoes', 'lancamento_estorno_id', 'lancamentos'),
            ('reversoes_eventos', 'evento_id', 'eventos_financeiros'),
            ('reclassificacoes_eventos', 'evento_id', 'eventos_financeiros'),
        ):
            orfao = self.c.execute(f'SELECT t.id FROM {tabela} t LEFT JOIN {alvo} a '
                f'ON a.id=t.{coluna} WHERE a.id IS NULL LIMIT 1').fetchone()
            _exigir(orfao is None, f'Referência inexistente: {tabela}.{coluna}.')

    def _linha(self, tabela, identificador):
        # Chamadores usam somente nomes internos, nunca texto recebido da UI.
        _inteiro(identificador)
        r = self.c.execute(f'SELECT * FROM {tabela} WHERE id=?', (identificador,)).fetchone()
        _exigir(r is not None, f'Referência inexistente em {tabela}.')
        return r

    def _operacao(self, identificador, tipos):
        _inteiro(identificador, True)
        r = self._linha('operacoes_hibridas', identificador)
        _exigir(r['estado'] == 'concluida' and r['tipo'] in tipos, 'Operação não concluída ou incompatível.')

    def _categoria(self, identificador, tipo):
        r = self._linha('categorias', identificador)
        _exigir(r['tipo'] == tipo, 'Categoria economicamente incompatível.')
        return Categoria(r['id'], _texto(r['nome']))

    @staticmethod
    def _legado(e):
        return e['origem_tipo'] is None and e['operacao_hibrida_id'] is None

    def _base(self, identificador):
        if identificador in self.bases:
            return self.bases[identificador]
        e = self._linha('eventos_financeiros', identificador)
        if self._legado(e):
            raise sf.EventoNaoElegivel('Evento histórico não adotado pelo fluxo híbrido.')
        _inteiro(e['id'], True)
        _inteiro(e['valor_centavos'], True)
        _exigir(e['origem_tipo'] == 'manual' and e['situacao_competencia'] == 'confirmada'
                and e['tipo'] in ('receita', 'despesa'), 'Evento manual inconsistente.')
        _exigir(all(e[k] is None for k in ('compra_cartao_id', 'parcelamento_id', 'parcela_comum_id',
                'ocorrencia_id', 'lancamento_legado_id')), 'Origens incompatíveis no evento manual.')
        self._operacao(e['operacao_hibrida_id'], ('registrar_evento', 'registrar_imediata'))
        _texto(e['descricao'])
        _data(e['data_competencia'])
        _data(e['data_vencimento'])
        categoria = self._categoria(e['categoria_id'], e['tipo'])
        for r in self.c.execute('SELECT * FROM reclassificacoes_eventos WHERE evento_id=? ORDER BY id', (e['id'],)):
            _inteiro(r['id'], True)
            self._operacao(r['operacao_hibrida_id'], ('reclassificar_evento',))
            _texto(r['motivo'])
            _exigir(r['categoria_anterior_id'] == categoria.id and r['categoria_nova_id'] != categoria.id,
                    'Sequência de reclassificação inconsistente.')
            categoria = self._categoria(r['categoria_nova_id'], e['tipo'])
        atual = self.c.execute('SELECT categoria_atual_id FROM eventos_classificacao_atual WHERE id=?', (e['id'],)).fetchone()
        _exigir(atual is not None and atual[0] == categoria.id, 'Classificação corrente inconsistente.')
        reversoes = self.c.execute('SELECT * FROM reversoes_eventos WHERE evento_id=?', (e['id'],)).fetchall()
        _exigir(len(reversoes) <= 1, 'Reversões duplicadas.')
        reversao = None
        if reversoes:
            r = reversoes[0]
            _inteiro(r['id'], True)
            self._operacao(r['operacao_hibrida_id'], ('reverter_evento',))
            _exigir(r['categoria_id'] == categoria.id, 'Classificação da reversão inconsistente.')
            reversao = DetalheReversao(r['id'], r['operacao_hibrida_id'], _data(r['data_competencia']),
                                      _texto(r['motivo']), categoria)
        self.bases[e['id']] = (e, categoria, reversao)
        return self.bases[e['id']]

    def _caixa(self, identificador, negativo=False):
        chave = (identificador, negativo)
        if chave in self.caixas:
            return self.caixas[chave]
        l = self._linha('lancamentos', identificador)
        _inteiro(l['id'], True)
        valor = _inteiro(l['valor_centavos'])
        _exigir(1 <= (-valor if negativo else valor) <= sf.MAX_CENTAVOS,
                'Sinal ou valor do caixa inconsistente.')
        _exigir(l['tipo'] in ('receita', 'despesa') and l['recorrencia_id'] is None
                and l['parcelamento_id'] is None, 'Tipo ou origem do caixa inconsistente.')
        self._operacao(l['operacao_hibrida_id'],
                       ('estornar_liquidacao',) if negativo else ('registrar_imediata', 'liquidar_evento'))
        self._categoria(l['categoria_id'], l['tipo'])
        _texto(l['categoria'])  # Nome capturado; não substituir pelo cadastro atual.
        _texto(l['descricao'])
        _data(l['data'])
        _exigir(self.c.execute('SELECT valor=CAST(valor_centavos AS REAL)/100.0 FROM lancamentos WHERE id=?',
                              (l['id'],)).fetchone()[0] == 1, 'Projeção de caixa inconsistente.')
        vinculos = self.c.execute('SELECT * FROM liquidacoes_eventos WHERE lancamento_id=?', (l['id'],)).fetchall()
        retornos = self.c.execute('SELECT id FROM estornos_liquidacoes WHERE lancamento_estorno_id=?', (l['id'],)).fetchall()
        if negativo:
            _exigir(not vinculos and len(retornos) == 1, 'Vínculos do caixa de estorno inconsistentes.')
        else:
            _exigir(bool(vinculos) and not retornos, 'Caixa positivo sem conciliação ou usado como estorno.')
            alocado = 0
            eventos = set()
            for q in vinculos:
                _inteiro(q['id'], True)
                montante = _inteiro(q['valor_centavos'], True)
                outro, _, _ = self._base(q['evento_id'])
                _exigir(outro['tipo'] == l['tipo'] and montante <= outro['valor_centavos']
                        and outro['id'] not in eventos, 'Alocação de caixa inconsistente.')
                eventos.add(outro['id'])
                alocado += montante
            _exigir(alocado <= valor, 'Caixa original superalocado.')
        self.caixas[chave] = l
        return l

    def _liquidacao(self, q):
        if q['id'] in self.liquidacoes:
            return self.liquidacoes[q['id']]
        _inteiro(q['id'], True)
        valor = _inteiro(q['valor_centavos'], True)
        e, _, reversao = self._base(q['evento_id'])
        _exigir(valor <= e['valor_centavos'], 'Liquidação superior ao evento.')
        original = self._caixa(q['lancamento_id'])
        _exigir(original['tipo'] == e['tipo'], 'Tipos de evento e caixa divergentes.')
        categoria = Categoria(original['categoria_id'], original['categoria'])
        estornos = []
        total = 0
        for s in self.c.execute('SELECT * FROM estornos_liquidacoes WHERE liquidacao_id=? ORDER BY id', (q['id'],)):
            _inteiro(s['id'], True)
            retorno = self._caixa(s['lancamento_estorno_id'], negativo=True)
            _exigir(all(retorno[k] == original[k] for k in ('tipo', 'categoria_id', 'categoria')),
                    'Classificação histórica do estorno divergente.')
            data_retorno, data_original = _data(retorno['data']), _data(original['data'])
            _exigir((s['natureza'] == 'devolucao_real' and data_retorno >= data_original)
                    or (s['natureza'] == 'correcao_registro' and data_retorno == data_original),
                    'Natureza ou data do estorno inconsistente.')
            total += -retorno['valor_centavos']
            estornos.append(DetalheEstorno(s['id'], q['id'], retorno['id'], retorno['operacao_hibrida_id'],
                retorno['valor_centavos'], data_retorno, s['natureza'], _texto(s['motivo']),
                retorno['tipo'], categoria, retorno['descricao']))
        _exigir(total <= valor, 'Estornos superiores à liquidação original.')
        detalhe = DetalheLiquidacao(q['id'], e['id'], original['id'], original['operacao_hibrida_id'],
            valor, original['valor_centavos'], total, valor-total, _data(original['data']), e['tipo'],
            categoria, original['descricao'], tuple(estornos), reversao is None and valor > total)
        self.liquidacoes[q['id']] = detalhe
        return detalhe

    def evento(self, identificador):
        if identificador in self.eventos:
            return self.eventos[identificador]
        e, categoria, reversao = self._base(identificador)
        liquidacoes = tuple(self._liquidacao(q) for q in self.c.execute(
            'SELECT * FROM liquidacoes_eventos WHERE evento_id=? ORDER BY id', (e['id'],)))
        bruto = sum(q.valor_original_centavos for q in liquidacoes)
        estornado = sum(q.total_estornado_centavos for q in liquidacoes)
        liquido = bruto - estornado
        _exigir(0 <= liquido <= e['valor_centavos'], 'Liquidação líquida do evento inconsistente.')
        _exigir(reversao is None or liquido == 0, 'Evento revertido com liquidação líquida ativa.')
        # Reversão integral cancela o compromisso; o valor original e todo o
        # histórico continuam visíveis. Não apresentar obrigação reaberta.
        saldo = 0 if reversao else e['valor_centavos'] - liquido
        detalhe = DetalheEvento(e['id'], e['tipo'], e['descricao'], _data(e['data_competencia']),
            _data(e['data_vencimento']), categoria, e['valor_centavos'], bruto, estornado, liquido,
            saldo, liquidacoes, reversao)
        self.eventos[e['id']] = detalhe
        return detalhe


def _id_consulta(valor):
    if type(valor) is not int or not 1 <= valor <= sf.MAX_CENTAVOS:
        raise sf.ParametroInvalido('Informe um ID híbrido positivo int64.')


def listar_eventos_liquidaveis():
    with _snapshot() as g:
        eventos = (g.evento(r['id']) for r in g.c.execute('SELECT id FROM eventos_financeiros '
            'WHERE origem_tipo IS NOT NULL OR operacao_hibrida_id IS NOT NULL ORDER BY data_vencimento,id'))
        return tuple(e for e in eventos if e.reversao is None and e.saldo_aberto_centavos > 0)


def obter_detalhe_evento(evento_id):
    _id_consulta(evento_id)
    with _snapshot() as g:
        if not g.c.execute('SELECT 1 FROM eventos_financeiros WHERE id=?', (evento_id,)).fetchone():
            raise sf.EventoInexistente('Evento não encontrado.')
        return g.evento(evento_id)


def listar_liquidacoes_estornaveis():
    with _snapshot() as g:
        resultado = []
        for q in g.c.execute('SELECT * FROM liquidacoes_eventos ORDER BY id'):
            e = g._linha('eventos_financeiros', q['evento_id'])
            if g._legado(e):
                continue
            g.evento(e['id'])  # Confere também o saldo agregado do evento.
            detalhe = g._liquidacao(q)
            if detalhe.elegivel_estorno:
                resultado.append(detalhe)
        return tuple(resultado)


def obter_detalhe_liquidacao(liquidacao_id):
    _id_consulta(liquidacao_id)
    with _snapshot() as g:
        q = g.c.execute('SELECT * FROM liquidacoes_eventos WHERE id=?', (liquidacao_id,)).fetchone()
        if q is None:
            raise sf.LiquidacaoInexistente('Liquidação não encontrada.')
        g.evento(q['evento_id'])
        return g._liquidacao(q)
