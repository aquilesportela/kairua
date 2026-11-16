"""DDL e pre-condicao da etapa 3.1B; nenhuma operacao financeira de servico."""

import sqlite3


def _data_iso(expressao):
    return f"""length({expressao}) = 10
        AND {expressao} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
        AND substr({expressao}, 1, 4) >= '0001'
        AND date({expressao}, '+0 days') IS NOT NULL
        AND date({expressao}, '+0 days') = {expressao}"""


_SQL = []
_OBJETOS = set()


def _objeto(tipo, nome, sql):
    _OBJETOS.add(nome)
    _SQL.append(sql)


def _gatilho(nome, momento, evento, tabela, corpo):
    _objeto('trigger', nome, f"""CREATE TRIGGER {nome}
        {momento} {evento} ON {tabela} BEGIN {corpo} END""")


def _exigir(condicao, erro):
    return f"SELECT RAISE(ABORT, '{erro}') WHERE ({condicao}) IS NOT 1;"


def _proibir(condicao, erro):
    return f"SELECT RAISE(ABORT, '{erro}') WHERE ({condicao});"


def _operacao(coluna, tipos):
    return f"""EXISTS (SELECT 1 FROM operacoes_hibridas o
        WHERE o.id = {coluna} AND o.estado = 'aberta' AND o.tipo IN ({tipos}))"""


_objeto('table', 'operacoes_hibridas', """CREATE TABLE operacoes_hibridas (
    id INTEGER PRIMARY KEY CHECK (id > 0),
    chave TEXT NOT NULL UNIQUE CHECK (length(trim(chave)) > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('registrar_evento', 'registrar_imediata',
        'liquidar_evento', 'estornar_liquidacao', 'reverter_evento', 'reclassificar_evento')),
    requisicao_canonica TEXT NOT NULL CHECK (length(requisicao_canonica) > 0),
    estado TEXT NOT NULL DEFAULT 'aberta' CHECK (estado IN ('aberta', 'concluida')),
    registrada_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)""")

_SQL.extend((
    """ALTER TABLE lancamentos ADD COLUMN operacao_hibrida_id INTEGER
        REFERENCES operacoes_hibridas(id) ON DELETE RESTRICT""",
    """ALTER TABLE lancamentos ADD COLUMN valor_centavos INTEGER CHECK (
        (operacao_hibrida_id IS NULL AND valor_centavos IS NULL) OR
        (operacao_hibrida_id IS NOT NULL AND valor_centavos IS NOT NULL
         AND typeof(valor_centavos) = 'integer'
         AND valor_centavos BETWEEN -9223372036854775807 AND 9223372036854775807
         AND valor_centavos <> 0 AND tipo IN ('receita', 'despesa')))""",
    """ALTER TABLE eventos_financeiros ADD COLUMN operacao_hibrida_id INTEGER
        REFERENCES operacoes_hibridas(id) ON DELETE RESTRICT""",
    f"""ALTER TABLE eventos_financeiros ADD COLUMN data_vencimento TEXT
        CHECK (data_vencimento IS NULL OR ({_data_iso('data_vencimento')}))""",
    """ALTER TABLE eventos_financeiros ADD COLUMN origem_tipo TEXT CHECK (
        origem_tipo IS NULL OR (origem_tipo = 'manual' AND operacao_hibrida_id IS NOT NULL
        AND situacao_competencia = 'confirmada' AND data_vencimento IS NOT NULL
        AND compra_cartao_id IS NULL AND parcelamento_id IS NULL
        AND parcela_comum_id IS NULL AND ocorrencia_id IS NULL AND lancamento_legado_id IS NULL))""",
))

_objeto('table', 'estornos_liquidacoes', """CREATE TABLE estornos_liquidacoes (
    id INTEGER PRIMARY KEY CHECK (id > 0),
    liquidacao_id INTEGER NOT NULL REFERENCES liquidacoes_eventos(id) ON DELETE RESTRICT,
    lancamento_estorno_id INTEGER NOT NULL UNIQUE REFERENCES lancamentos(id) ON DELETE RESTRICT,
    natureza TEXT NOT NULL CHECK (natureza IN ('devolucao_real', 'correcao_registro')),
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0)
)""")
_objeto('table', 'reversoes_eventos', f"""CREATE TABLE reversoes_eventos (
    id INTEGER PRIMARY KEY CHECK (id > 0),
    evento_id INTEGER NOT NULL UNIQUE REFERENCES eventos_financeiros(id) ON DELETE RESTRICT,
    operacao_hibrida_id INTEGER NOT NULL REFERENCES operacoes_hibridas(id) ON DELETE RESTRICT,
    data_competencia TEXT NOT NULL CHECK ({_data_iso('data_competencia')}),
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0)
)""")
_objeto('table', 'reclassificacoes_eventos', """CREATE TABLE reclassificacoes_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id > 0),
    evento_id INTEGER NOT NULL REFERENCES eventos_financeiros(id) ON DELETE RESTRICT,
    operacao_hibrida_id INTEGER NOT NULL REFERENCES operacoes_hibridas(id) ON DELETE RESTRICT,
    categoria_anterior_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    categoria_nova_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    CHECK (categoria_anterior_id <> categoria_nova_id),
    UNIQUE (operacao_hibrida_id, evento_id)
)""")

for _nome, _alvo in (
    ('idx_lancamentos_operacao_hibrida', 'lancamentos(operacao_hibrida_id) WHERE operacao_hibrida_id IS NOT NULL'),
    ('idx_eventos_operacao_hibrida', 'eventos_financeiros(operacao_hibrida_id) WHERE operacao_hibrida_id IS NOT NULL'),
    ('idx_eventos_manuais_vencimento', "eventos_financeiros(data_vencimento) WHERE origem_tipo = 'manual'"),
    ('idx_estornos_liquidacao', 'estornos_liquidacoes(liquidacao_id)'),
    ('idx_reversoes_operacao', 'reversoes_eventos(operacao_hibrida_id)'),
    ('idx_reversoes_competencia', 'reversoes_eventos(data_competencia)'),
    ('idx_reversoes_categoria', 'reversoes_eventos(categoria_id)'),
    ('idx_reclassificacoes_evento', 'reclassificacoes_eventos(evento_id, id)'),
    ('idx_reclassificacoes_categoria_anterior', 'reclassificacoes_eventos(categoria_anterior_id)'),
    ('idx_reclassificacoes_categoria_nova', 'reclassificacoes_eventos(categoria_nova_id)'),
):
    _objeto('index', _nome, f'CREATE INDEX {_nome} ON {_alvo}')

_objeto('view', 'eventos_classificacao_atual', """CREATE VIEW eventos_classificacao_atual AS
    SELECT e.*, COALESCE((SELECT r.categoria_nova_id FROM reclassificacoes_eventos r
        WHERE r.evento_id = e.id ORDER BY r.id DESC LIMIT 1), e.categoria_id) AS categoria_atual_id
    FROM eventos_financeiros e""")
_objeto('view', '_hibrido_liquidacoes', """CREATE VIEW _hibrido_liquidacoes AS
    SELECT q.*, q.valor_centavos + COALESCE((SELECT SUM(l.valor_centavos)
        FROM estornos_liquidacoes s JOIN lancamentos l ON l.id = s.lancamento_estorno_id
        WHERE s.liquidacao_id = q.id), 0) AS valor_liquido
    FROM liquidacoes_eventos q""")
_objeto('view', '_hibrido_categorias_em_uso', """CREATE VIEW _hibrido_categorias_em_uso AS
    SELECT categoria_id AS id FROM lancamentos
    UNION SELECT categoria_id FROM eventos_financeiros
    UNION SELECT categoria_id FROM compras_cartao
    UNION SELECT categoria_id FROM recorrencias
    UNION SELECT categoria_id FROM parcelamentos
    UNION SELECT categoria_id FROM reversoes_eventos
    UNION SELECT categoria_anterior_id FROM reclassificacoes_eventos
    UNION SELECT categoria_nova_id FROM reclassificacoes_eventos""")

_gatilho('tr_operacoes_bi', 'BEFORE', 'INSERT', 'operacoes_hibridas',
    _exigir("NEW.estado = 'aberta'", 'operacao_estado_invalido') +
    _proibir("EXISTS (SELECT 1 FROM operacoes_hibridas WHERE (NEW.id > 0 AND id = NEW.id) OR chave = NEW.chave)",
             'operacao_duplicada'))
_gatilho('tr_operacoes_bu', 'BEFORE', 'UPDATE', 'operacoes_hibridas', _exigir("""
    OLD.estado = 'aberta' AND NEW.estado = 'concluida' AND NEW.id IS OLD.id
    AND NEW.chave IS OLD.chave AND NEW.tipo IS OLD.tipo
    AND NEW.requisicao_canonica IS OLD.requisicao_canonica
    AND NEW.registrada_em IS OLD.registrada_em""", 'operacao_imutavel'))
_gatilho('tr_operacoes_bd', 'BEFORE', 'DELETE', 'operacoes_hibridas',
         "SELECT RAISE(ABORT, 'operacao_imutavel');")

_gatilho('tr_eventos_bi', 'BEFORE', 'INSERT', 'eventos_financeiros',
    _proibir("EXISTS (SELECT 1 FROM eventos_financeiros WHERE (NEW.id > 0 AND id = NEW.id) OR chave_origem = NEW.chave_origem)",
             'evento_duplicado') +
    _exigir("NEW.origem_tipo = 'manual' AND NEW.situacao_competencia = 'confirmada'", 'evento_manual_invalido') +
    _exigir(_operacao('NEW.operacao_hibrida_id', "'registrar_evento', 'registrar_imediata'"), 'operacao_evento_invalida') +
    _exigir("EXISTS (SELECT 1 FROM categorias WHERE id = NEW.categoria_id AND tipo = NEW.tipo)", 'categoria_evento_invalida'))
_gatilho('tr_eventos_ai', 'AFTER', 'INSERT', 'eventos_financeiros',
         _exigir('NEW.id > 0', 'identificador_hibrido_invalido'))


def _caixa_protegido(id_sql, marcador):
    return f"""{marcador} IS NOT NULL
        OR EXISTS (SELECT 1 FROM liquidacoes_eventos WHERE lancamento_id = {id_sql})
        OR EXISTS (SELECT 1 FROM estornos_liquidacoes WHERE lancamento_estorno_id = {id_sql})
        OR EXISTS (SELECT 1 FROM eventos_financeiros WHERE lancamento_legado_id = {id_sql})"""


_gatilho('tr_lancamentos_bi', 'BEFORE', 'INSERT', 'lancamentos',
    _proibir(f"EXISTS (SELECT 1 FROM lancamentos l WHERE NEW.id <> -1 AND l.id = NEW.id AND ({_caixa_protegido('l.id', 'l.operacao_hibrida_id')}))",
             'caixa_protegido') +
    _proibir(f"""(NEW.operacao_hibrida_id IS NOT NULL OR NEW.valor_centavos IS NOT NULL) AND (
        ({_operacao('NEW.operacao_hibrida_id', "'registrar_imediata', 'liquidar_evento', 'estornar_liquidacao'")}) IS NOT 1
        OR (typeof(NEW.valor) IN ('integer', 'real') AND NEW.valor IS NOT NULL
            AND NEW.valor = CAST(NEW.valor_centavos AS REAL) / 100.0) IS NOT 1
        OR ({_data_iso('NEW.data')}) IS NOT 1
        OR NEW.recorrencia_id IS NOT NULL OR NEW.parcelamento_id IS NOT NULL
        OR NOT EXISTS (SELECT 1 FROM categorias WHERE id = NEW.categoria_id AND tipo = NEW.tipo)
        OR NOT EXISTS (SELECT 1 FROM operacoes_hibridas o WHERE o.id = NEW.operacao_hibrida_id AND (
            (o.tipo IN ('registrar_imediata', 'liquidar_evento') AND NEW.valor_centavos > 0)
            OR (o.tipo = 'estornar_liquidacao' AND NEW.valor_centavos < 0))))""", 'caixa_hibrido_invalido'))
_gatilho('tr_lancamentos_ai', 'AFTER', 'INSERT', 'lancamentos',
    _exigir('NEW.operacao_hibrida_id IS NULL OR NEW.id > 0', 'identificador_hibrido_invalido') +
    # ID -1 em BEFORE pode ser provisório. Depois da atribuição, referências
    # persistentes denunciam REPLACE de um ID legado protegido, não um ID novo.
    _proibir(f"NEW.id = -1 AND ({_caixa_protegido('NEW.id', 'NEW.operacao_hibrida_id')})", 'caixa_protegido'))
_gatilho('tr_lancamentos_bu', 'BEFORE', 'UPDATE', 'lancamentos', _proibir(
    f"""({_caixa_protegido('OLD.id', 'OLD.operacao_hibrida_id')})
    OR NEW.operacao_hibrida_id IS NOT NULL OR NEW.valor_centavos IS NOT NULL
    OR EXISTS (SELECT 1 FROM lancamentos l WHERE l.id = NEW.id AND
        ({_caixa_protegido('l.id', 'l.operacao_hibrida_id')}))""", 'caixa_protegido'))
_gatilho('tr_lancamentos_bd', 'BEFORE', 'DELETE', 'lancamentos',
         _proibir(_caixa_protegido('OLD.id', 'OLD.operacao_hibrida_id'), 'caixa_protegido'))

_gatilho('tr_liquidacoes_bi', 'BEFORE', 'INSERT', 'liquidacoes_eventos',
    _proibir("""EXISTS (SELECT 1 FROM liquidacoes_eventos WHERE (NEW.id > 0 AND id = NEW.id) OR
        (evento_id = NEW.evento_id AND lancamento_id = NEW.lancamento_id))""", 'liquidacao_duplicada') +
    _exigir(f"""EXISTS (SELECT 1 FROM eventos_financeiros e JOIN lancamentos l ON l.id = NEW.lancamento_id
        WHERE e.id = NEW.evento_id AND e.origem_tipo = 'manual' AND e.situacao_competencia = 'confirmada'
        AND NOT EXISTS (SELECT 1 FROM reversoes_eventos WHERE evento_id = e.id)
        AND l.valor_centavos > 0 AND l.tipo = e.tipo
        AND {_operacao('l.operacao_hibrida_id', "'registrar_imediata', 'liquidar_evento'")}
        AND NEW.valor_centavos <= e.valor_centavos - COALESCE((SELECT SUM(valor_liquido)
            FROM _hibrido_liquidacoes WHERE evento_id = e.id), 0)
        AND NEW.valor_centavos <= l.valor_centavos - COALESCE((SELECT SUM(valor_centavos)
            FROM liquidacoes_eventos WHERE lancamento_id = l.id), 0))""", 'liquidacao_invalida_ou_excessiva'))
_gatilho('tr_liquidacoes_ai', 'AFTER', 'INSERT', 'liquidacoes_eventos',
         _exigir('NEW.id > 0', 'identificador_hibrido_invalido'))

_gatilho('tr_estornos_bi', 'BEFORE', 'INSERT', 'estornos_liquidacoes',
    _proibir("EXISTS (SELECT 1 FROM estornos_liquidacoes WHERE (NEW.id > 0 AND id = NEW.id) OR lancamento_estorno_id = NEW.lancamento_estorno_id)",
             'estorno_duplicado') +
    _exigir(f"""EXISTS (SELECT 1 FROM _hibrido_liquidacoes q
        JOIN eventos_financeiros e ON e.id = q.evento_id
        JOIN lancamentos original ON original.id = q.lancamento_id
        JOIN lancamentos retorno ON retorno.id = NEW.lancamento_estorno_id
        WHERE q.id = NEW.liquidacao_id AND e.origem_tipo = 'manual'
        AND NOT EXISTS (SELECT 1 FROM reversoes_eventos WHERE evento_id = e.id)
        AND original.valor_centavos > 0 AND retorno.valor_centavos < 0
        AND retorno.tipo = original.tipo AND retorno.categoria_id = original.categoria_id
        AND retorno.categoria = original.categoria
        AND {_operacao('retorno.operacao_hibrida_id', "'estornar_liquidacao'")}
        AND -retorno.valor_centavos <= q.valor_liquido
        AND ((NEW.natureza = 'devolucao_real' AND retorno.data >= original.data)
            OR (NEW.natureza = 'correcao_registro' AND retorno.data = original.data)))""", 'estorno_invalido_ou_excessivo'))

_gatilho('tr_reversoes_bi', 'BEFORE', 'INSERT', 'reversoes_eventos',
    _proibir("EXISTS (SELECT 1 FROM reversoes_eventos WHERE evento_id = NEW.evento_id OR (NEW.id > 0 AND id = NEW.id))", 'evento_ja_revertido') +
    _exigir(_operacao('NEW.operacao_hibrida_id', "'reverter_evento'"), 'operacao_reversao_invalida') +
    _exigir("""EXISTS (SELECT 1 FROM eventos_classificacao_atual e JOIN categorias c ON c.id = NEW.categoria_id
        WHERE e.id = NEW.evento_id AND e.origem_tipo = 'manual' AND e.situacao_competencia = 'confirmada'
        AND NEW.categoria_id = e.categoria_atual_id AND c.tipo = e.tipo
        AND COALESCE((SELECT SUM(valor_liquido) FROM _hibrido_liquidacoes WHERE evento_id = e.id), 0) = 0)""",
        'reversao_invalida_ou_evento_liquidado'))

_gatilho('tr_reclassificacoes_bi', 'BEFORE', 'INSERT', 'reclassificacoes_eventos',
    _proibir("""EXISTS (SELECT 1 FROM reclassificacoes_eventos WHERE (NEW.id > 0 AND id = NEW.id) OR
        (operacao_hibrida_id = NEW.operacao_hibrida_id AND evento_id = NEW.evento_id))""", 'reclassificacao_duplicada') +
    _exigir(_operacao('NEW.operacao_hibrida_id', "'reclassificar_evento'"), 'operacao_reclassificacao_invalida') +
    _exigir("""EXISTS (SELECT 1 FROM eventos_classificacao_atual e
        JOIN categorias anterior ON anterior.id = NEW.categoria_anterior_id
        JOIN categorias nova ON nova.id = NEW.categoria_nova_id
        WHERE e.id = NEW.evento_id AND e.origem_tipo = 'manual' AND e.situacao_competencia = 'confirmada'
        AND e.categoria_atual_id = NEW.categoria_anterior_id AND anterior.tipo = e.tipo AND nova.tipo = e.tipo
        AND NOT EXISTS (SELECT 1 FROM reversoes_eventos WHERE evento_id = e.id))""", 'reclassificacao_invalida'))
_gatilho('tr_reclassificacoes_ai', 'AFTER', 'INSERT', 'reclassificacoes_eventos',
    _proibir("EXISTS (SELECT 1 FROM reclassificacoes_eventos WHERE evento_id = NEW.evento_id AND id > NEW.id)",
             'reclassificacao_fora_de_ordem'))

for _tabela, _prefixo in (
    ('eventos_financeiros', 'eventos'), ('liquidacoes_eventos', 'liquidacoes'),
    ('estornos_liquidacoes', 'estornos'), ('reversoes_eventos', 'reversoes'),
    ('reclassificacoes_eventos', 'reclassificacoes'),
):
    for _acao, _sufixo in (('UPDATE', 'bu'), ('DELETE', 'bd')):
        _gatilho(f'tr_{_prefixo}_{_sufixo}', 'BEFORE', _acao, _tabela,
                 f"SELECT RAISE(ABORT, '{_prefixo}_imutaveis');")

# Protege as origens preexistentes inclusive quando a exclusao implicita de
# REPLACE nao dispara DELETE triggers (recursive_triggers OFF).
for _tabela, _prefixo, _campo, _chave in (
    ('compras_cartao', 'compras', 'compra_cartao_id', '0'),
    ('parcelamentos', 'parcelamentos', 'parcelamento_id', '0'),
    ('parcelamento_parcelas', 'parcelas', 'parcela_comum_id',
     'p.parcelamento_id = NEW.parcelamento_id AND p.numero_parcela = NEW.numero_parcela'),
    ('recorrencia_ocorrencias', 'ocorrencias', 'ocorrencia_id',
     'p.recorrencia_id = NEW.recorrencia_id AND p.data_vencimento = NEW.data_vencimento'),
):
    _colisao = f"""SELECT 1 FROM {_tabela} p JOIN eventos_financeiros e ON e.{_campo} = p.id
        WHERE ((NEW.id <> -1 AND p.id = NEW.id) OR ({_chave}))"""
    _gatilho(f'tr_{_prefixo}_origem_bi', 'BEFORE', 'INSERT', _tabela,
             _proibir(f'EXISTS ({_colisao})', 'origem_protegida'))
    _gatilho(f'tr_{_prefixo}_origem_ai', 'AFTER', 'INSERT', _tabela,
             _proibir(f'NEW.id = -1 AND EXISTS (SELECT 1 FROM eventos_financeiros WHERE {_campo} = NEW.id)',
                      'origem_protegida'))
    _gatilho(f'tr_{_prefixo}_origem_bu', 'BEFORE', 'UPDATE', _tabela,
             _proibir(f"""(NEW.id IS NOT OLD.id AND EXISTS (SELECT 1 FROM eventos_financeiros WHERE {_campo} = OLD.id))
                 OR EXISTS (SELECT 1 FROM {_tabela} p JOIN eventos_financeiros e ON e.{_campo} = p.id
                    WHERE (p.id = NEW.id OR ({_chave})) AND p.id <> OLD.id)""", 'origem_protegida'))
    _gatilho(f'tr_{_prefixo}_origem_bd', 'BEFORE', 'DELETE', _tabela,
             _proibir(f'EXISTS (SELECT 1 FROM eventos_financeiros WHERE {_campo} = OLD.id)', 'origem_protegida'))

_categoria_colisao = """SELECT 1 FROM categorias c JOIN _hibrido_categorias_em_uso u ON u.id = c.id
    WHERE ((NEW.id <> -1 AND c.id = NEW.id) OR c.nome = NEW.nome)"""
_gatilho('tr_categorias_bi', 'BEFORE', 'INSERT', 'categorias',
    _proibir(f"""EXISTS ({_categoria_colisao} AND
        ((NEW.id = -1 OR NEW.id = c.id) AND NEW.nome IS c.nome AND NEW.tipo IS c.tipo) IS NOT 1)""",
             'categoria_protegida') +
    f"SELECT RAISE(IGNORE) WHERE EXISTS ({_categoria_colisao});")
_gatilho('tr_categorias_ai', 'AFTER', 'INSERT', 'categorias',
         _proibir('NEW.id = -1 AND EXISTS (SELECT 1 FROM _hibrido_categorias_em_uso WHERE id = NEW.id)',
                  'categoria_protegida'))
_gatilho('tr_categorias_bu', 'BEFORE', 'UPDATE', 'categorias', _proibir("""
    ((NEW.id IS NOT OLD.id OR NEW.tipo IS NOT OLD.tipo)
        AND EXISTS (SELECT 1 FROM _hibrido_categorias_em_uso WHERE id = OLD.id))
    OR EXISTS (SELECT 1 FROM categorias c JOIN _hibrido_categorias_em_uso u ON u.id = c.id
        WHERE c.id <> OLD.id AND (c.id = NEW.id OR c.nome = NEW.nome))""", 'categoria_protegida'))
_gatilho('tr_categorias_bd', 'BEFORE', 'DELETE', 'categorias',
         _proibir('EXISTS (SELECT 1 FROM _hibrido_categorias_em_uso WHERE id = OLD.id)', 'categoria_protegida'))

SQL_MIGRACAO_3 = tuple(_SQL)
OBJETOS_MIGRACAO_3 = frozenset(_OBJETOS)
# SQLite valida CHECKs novos por quick_check durante estes DDLs exatos.
# Nao e uma permissao generica para PRAGMA nem para ALTERs externos ao catalogo.
ALTERS_COM_CHECK_MIGRACAO_3 = {
    sql: ('lancamentos' if sql.startswith('ALTER TABLE lancamentos ') else 'eventos_financeiros')
    for sql in SQL_MIGRACAO_3 if sql.startswith('ALTER TABLE ') and 'CHECK' in sql
}


def _identidade_indice(conexao, nome):
    """Identidade estrutural, incluindo chaves de expressao e collations."""
    registro = conexao.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ? COLLATE NOCASE", (nome,)
    ).fetchone()
    if registro is None:
        raise ValueError(f'Indice ausente: {nome}')
    tabela = registro[0]
    lista = [r for r in conexao.execute('SELECT * FROM pragma_index_list(?)', (tabela,))
             if r[1].casefold() == nome.casefold()]
    if len(lista) != 1:
        raise ValueError(f'Metadados de indice invalidos: {nome}')
    chaves = tuple((r[2], r[3], r[4], r[1]) for r in conexao.execute(
        'SELECT * FROM pragma_index_xinfo(?) ORDER BY seqno', (nome,)) if r[5])
    return tabela, bool(lista[0][2]), bool(lista[0][4]), lista[0][3], chaves


def _chaves_simples(chaves):
    # cid negativo identifica expressao/rowid; desc/collation fazem parte da
    # semantica conhecida. Nunca inferir colisao generica de SQL textual.
    if any(cid < 0 or coluna is None or desc != 0 or collation != 'BINARY'
           for coluna, desc, collation, cid in chaves):
        return None
    return tuple(coluna for coluna, _, _, _ in chaves)


_UNICIDADES_COBERTAS = {
    'lancamentos': {('id',)},
    'categorias': {('id',), ('nome',)},
    'compras_cartao': {('id',)},
    'parcelamentos': {('id',)},
    'recorrencias': {('id',)},
    'parcelamento_parcelas': {('id',), ('parcelamento_id', 'numero_parcela')},
    'recorrencia_ocorrencias': {('id',), ('recorrencia_id', 'data_vencimento')},
    'eventos_financeiros': {('id',), ('chave_origem',), ('compra_cartao_id',),
        ('parcelamento_id',), ('parcela_comum_id',), ('ocorrencia_id',), ('lancamento_legado_id',)},
    'liquidacoes_eventos': {('id',), ('evento_id', 'lancamento_id')},
}


def validar_migracao_3(conexao, instrucoes, esquema_2):
    """Falha fechada: exige o esquema conhecido da etapa 2 e o legado usado."""
    def tabela(nome):
        registro = conexao.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = ? COLLATE NOCASE", (nome,)
        ).fetchone()
        if registro is None or registro[0] != 'table':
            raise ValueError(f'Tabela obrigatoria ausente: {nome}')
        return registro[1]

    try:
        # Comparacao conservadora do DDL publicado; nao aceita CHECKs omitidos
        # nem considera a mera versao registrada como prova de compatibilidade.
        for nome, sql in zip(('eventos_financeiros', 'liquidacoes_eventos'), esquema_2[:2]):
            if tabela(nome).strip() != sql.strip():
                raise ValueError(f'DDL da etapa 2 divergente: {nome}')
        obrigatorias = {
            'lancamentos': {'id': 'INTEGER', 'data': 'TEXT', 'descricao': 'TEXT', 'tipo': 'TEXT',
                'categoria': 'TEXT', 'valor': 'REAL', 'categoria_id': 'INTEGER',
                'recorrencia_id': 'INTEGER', 'parcelamento_id': 'INTEGER'},
            'categorias': {'id': 'INTEGER', 'nome': 'TEXT', 'tipo': 'TEXT'},
            'compras_cartao': {'id': 'INTEGER', 'categoria_id': 'INTEGER'},
            'parcelamentos': {'id': 'INTEGER', 'categoria_id': 'INTEGER'},
            'recorrencias': {'id': 'INTEGER', 'categoria_id': 'INTEGER'},
            'parcelamento_parcelas': {'id': 'INTEGER', 'parcelamento_id': 'INTEGER', 'numero_parcela': 'INTEGER'},
            'recorrencia_ocorrencias': {'id': 'INTEGER', 'recorrencia_id': 'INTEGER', 'data_vencimento': 'TEXT'},
        }
        for nome, esperadas in obrigatorias.items():
            tabela(nome)
            colunas = {r[1]: r for r in conexao.execute('SELECT * FROM pragma_table_info(?)', (nome,))}
            if any(c not in colunas or colunas[c][2].upper() != tipo for c, tipo in esperadas.items()):
                raise ValueError(f'Colunas legadas incompativeis: {nome}')
            if [c for c, r in colunas.items() if r[5]] != ['id']:
                raise ValueError(f'Chave primaria incompativel: {nome}')
            if nome in ('lancamentos', 'categorias'):
                anulaveis = {'id', 'categoria_id', 'recorrencia_id', 'parcelamento_id'}
                if any(not colunas[c][3] for c in esperadas if c not in anulaveis):
                    raise ValueError(f'NOT NULL legado ausente: {nome}')
        protegidas = (*obrigatorias, 'eventos_financeiros', 'liquidacoes_eventos')
        marcadores = ','.join('?' for _ in protegidas)
        if conexao.execute(
            f"SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND tbl_name COLLATE NOCASE IN ({marcadores}) LIMIT 1",
            protegidas
        ).fetchone():
            raise ValueError('Gatilhos legados desconhecidos em tabelas protegidas')
        for nome, cobertas in _UNICIDADES_COBERTAS.items():
            for indice in conexao.execute('SELECT * FROM pragma_index_list(?)', (nome,)):
                if not indice[2]:
                    continue  # Indices nao unicos nao podem excluir por REPLACE.
                tabela, unico, parcial, origem, chaves = _identidade_indice(conexao, indice[1])
                if (tabela != nome or not unico or parcial or origem not in ('c', 'u', 'pk')
                        or _chaves_simples(chaves) not in cobertas):
                    raise ValueError(f'Unicidade nao coberta pelos gatilhos: {nome}.{indice[1]}')
        for nome, chave in (
            ('categorias', ['nome']),
            ('parcelamento_parcelas', ['parcelamento_id', 'numero_parcela']),
            ('recorrencia_ocorrencias', ['recorrencia_id', 'data_vencimento']),
        ):
            unicas = []
            for indice in conexao.execute('SELECT * FROM pragma_index_list(?)', (nome,)):
                if indice[2] and not indice[4]:
                    unicas.append([r[2] for r in conexao.execute(
                        'SELECT * FROM pragma_index_info(?)', (indice[1],))])
            if chave not in unicas:
                raise ValueError(f'Unicidade legada ausente: {nome}')
        for nome, tabela_esperada, alvo in (
            ('idx_eventos_competencia', 'eventos_financeiros', ('data_competencia',)),
            ('idx_eventos_categoria_competencia', 'eventos_financeiros', ('categoria_id', 'data_competencia')),
            ('idx_liquidacoes_lancamento', 'liquidacoes_eventos', ('lancamento_id',)),
        ):
            tabela, unico, parcial, origem, chaves = _identidade_indice(conexao, nome)
            if (tabela != tabela_esperada or unico or parcial or origem != 'c'
                    or _chaves_simples(chaves) != alvo):
                raise ValueError(f'Indice da etapa 2 incompativel: {nome}')
        existentes = {r[0].casefold() for r in conexao.execute('SELECT name FROM sqlite_master')}
        if existentes & {n.casefold() for n in OBJETOS_MIGRACAO_3}:
            raise ValueError('Objetos da etapa 3 ja existentes')
        for nome, novas in (
            ('lancamentos', {'operacao_hibrida_id', 'valor_centavos'}),
            ('eventos_financeiros', {'operacao_hibrida_id', 'data_vencimento', 'origem_tipo'}),
        ):
            if novas & {r[1] for r in conexao.execute('SELECT * FROM pragma_table_info(?)', (nome,))}:
                raise ValueError(f'Colunas da etapa 3 ja existentes: {nome}')
    except (ValueError, sqlite3.DatabaseError) as erro:
        raise ValueError(f'Esquema incompativel para migracao 3: {erro}') from erro
