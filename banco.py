import sqlite3
from datetime import datetime, timedelta
import calendar
import os

def obter_caminho_banco():
    return os.environ.get(
        "KAIRUA_DB_PATH",
        "financeiro.db"
    )

def criar_banco():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            descricao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL
        )
    """)

    conexao.commit()
    conexao.close()


def criar_categorias():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            tipo TEXT NOT NULL
        )
    """)

    categorias_padrao = [
        ("Alimentação", "despesa"),
        ("Moradia", "despesa"),
        ("Transporte", "despesa"),
        ("Educação", "despesa"),
        ("Lazer", "despesa"),
        ("Tecnologia", "despesa"),
        ("Compras", "despesa"),
        ("Saúde", "despesa"),
        ("Salário", "receita"),
        ("Outras Receitas", "receita"),
        ("Outros", "despesa")
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO categorias (nome, tipo)
        VALUES (?, ?)
    """, categorias_padrao)

    conexao.commit()
    conexao.close()

def migrar_datas():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id, data
        FROM lancamentos
    """)

    lancamentos = cursor.fetchall()

    for id_lancamento, data in lancamentos:

        if "/" not in data:
            continue

        partes = data.split("/")

        if len(partes) != 3:
            continue

        dia, mes, ano = partes

        data_iso = f"{ano}-{mes}-{dia}"

        cursor.execute("""
            UPDATE lancamentos
            SET data = ?
            WHERE id = ?
        """, (data_iso, id_lancamento))

    conexao.commit()
    conexao.close()


def migrar_categorias():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("PRAGMA table_info(lancamentos)")
    colunas = cursor.fetchall()

    nomes_colunas = [coluna[1] for coluna in colunas]

    if "categoria_id" not in nomes_colunas:
        cursor.execute("""
            ALTER TABLE lancamentos
            ADD COLUMN categoria_id INTEGER
        """)

    cursor.execute("""
        SELECT id, categoria, tipo
        FROM lancamentos
        WHERE categoria_id IS NULL
    """)

    lancamentos = cursor.fetchall()

    for id_lancamento, nome_categoria, tipo in lancamentos:

        cursor.execute("""
            SELECT id
            FROM categorias
            WHERE LOWER(nome) = LOWER(?)
        """, (nome_categoria,))

        categoria = cursor.fetchone()

        if categoria:
            categoria_id = categoria[0]

        else:
            cursor.execute("""
                INSERT OR IGNORE INTO categorias (nome, tipo)
                VALUES (?, ?)
            """, (nome_categoria, tipo))

            cursor.execute("""
                SELECT id
                FROM categorias
                WHERE LOWER(nome) = LOWER(?)
            """, (nome_categoria,))

            categoria_id = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE lancamentos
            SET categoria_id = ?
            WHERE id = ?
        """, (categoria_id, id_lancamento))

    conexao.commit()
    conexao.close()


def adicionar_lancamento(
    data,
    descricao,
    tipo,
    categoria_id,
    valor
):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        INSERT INTO lancamentos
        (data, descricao, tipo, categoria, valor, categoria_id)
        SELECT ?, ?, ?, nome, ?, id
        FROM categorias
        WHERE id = ?
    """, (
        data,
        descricao,
        tipo,
        valor,
        categoria_id
    ))

    conexao.commit()
    conexao.close()


def listar_categorias(tipo=None):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    if tipo:
        cursor.execute("""
            SELECT id, nome
            FROM categorias
            WHERE tipo = ?
            ORDER BY id
        """, (tipo,))

    else:
        cursor.execute("""
            SELECT id, nome, tipo
            FROM categorias
            ORDER BY nome
        """)

    categorias = cursor.fetchall()

    conexao.close()

    return categorias


def listar_lancamentos(
    data_inicio=None,
    data_fim=None,
    tipo=None,
    categoria_id=None
):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    consulta = """
        SELECT
            lancamentos.id,
            lancamentos.data,
            lancamentos.descricao,
            lancamentos.tipo,
            categorias.nome,
            lancamentos.valor
        FROM lancamentos
        LEFT JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE 1 = 1
    """

    parametros = []

    if data_inicio:
        consulta += """
            AND lancamentos.data >= ?
        """
        parametros.append(data_inicio)

    if data_fim:
        consulta += """
            AND lancamentos.data < ?
        """
        parametros.append(data_fim)

    if tipo:
        consulta += """
            AND lancamentos.tipo = ?
        """
        parametros.append(tipo)

    if categoria_id:
        consulta += """
            AND lancamentos.categoria_id = ?
        """
        parametros.append(categoria_id)

    consulta += """
        ORDER BY lancamentos.data, lancamentos.id
    """

    cursor.execute(
        consulta,
        parametros
    )

    lancamentos = cursor.fetchall()

    conexao.close()

    return lancamentos

def listar_lancamentos_mensal(ano, mes):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    inicio = f"{ano:04d}-{mes:02d}-01"

    if mes == 12:
        proximo_ano = ano + 1
        proximo_mes = 1
    else:
        proximo_ano = ano
        proximo_mes = mes + 1

    fim = f"{proximo_ano:04d}-{proximo_mes:02d}-01"

    cursor.execute("""
        SELECT
            lancamentos.id,
            lancamentos.data,
            lancamentos.descricao,
            lancamentos.tipo,
            categorias.nome,
            lancamentos.valor
        FROM lancamentos
        LEFT JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.data >= ?
        AND lancamentos.data < ?
        ORDER BY lancamentos.data, lancamentos.id
    """, (inicio, fim))

    lancamentos = cursor.fetchall()

    conexao.close()

    return lancamentos

def listar_lancamentos_tipo(tipo):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            lancamentos.id,
            lancamentos.data,
            lancamentos.descricao,
            lancamentos.tipo,
            categorias.nome,
            lancamentos.valor
        FROM lancamentos
        LEFT JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.tipo = ?
        ORDER BY lancamentos.data, lancamentos.id
    """, (tipo,))

    lancamentos = cursor.fetchall()

    conexao.close()

    return lancamentos

def listar_lancamentos_categoria(categoria_id):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            lancamentos.id,
            lancamentos.data,
            lancamentos.descricao,
            lancamentos.tipo,
            categorias.nome,
            lancamentos.valor
        FROM lancamentos
        LEFT JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.categoria_id = ?
        ORDER BY lancamentos.data, lancamentos.id
    """, (categoria_id,))

    lancamentos = cursor.fetchall()

    conexao.close()

    return lancamentos

def calcular_resumo():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT tipo, SUM(valor)
        FROM lancamentos
        GROUP BY tipo
    """)

    resultados = cursor.fetchall()

    conexao.close()

    receitas = 0
    despesas = 0

    for tipo, total in resultados:

        if tipo == "receita":
            receitas = total

        elif tipo == "despesa":
            despesas = total

    saldo = receitas - despesas

    return receitas, despesas, saldo

def calcular_resumo_mensal(ano, mes):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    inicio = f"{ano:04d}-{mes:02d}-01"

    if mes == 12:
        proximo_ano = ano + 1
        proximo_mes = 1
    else:
        proximo_ano = ano
        proximo_mes = mes + 1

    fim = f"{proximo_ano:04d}-{proximo_mes:02d}-01"

    cursor.execute("""
        SELECT tipo, SUM(valor)
        FROM lancamentos
        WHERE data >= ?
        AND data < ?
        GROUP BY tipo
    """, (inicio, fim))

    resultados = cursor.fetchall()

    conexao.close()

    receitas = 0
    despesas = 0

    for tipo, total in resultados:

        if tipo == "receita":
            receitas = total

        elif tipo == "despesa":
            despesas = total

    saldo = receitas - despesas

    return receitas, despesas, saldo

def despesas_por_categoria():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            categorias.nome,
            SUM(lancamentos.valor)
        FROM lancamentos
        INNER JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.tipo = 'despesa'
        GROUP BY categorias.id, categorias.nome
        ORDER BY SUM(lancamentos.valor) DESC
    """)

    resultados = cursor.fetchall()

    conexao.close()

    return resultados


def despesas_por_categoria_mensal(ano, mes):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    inicio = f"{ano:04d}-{mes:02d}-01"

    if mes == 12:
        proximo_ano = ano + 1
        proximo_mes = 1

    else:
        proximo_ano = ano
        proximo_mes = mes + 1

    fim = (
        f"{proximo_ano:04d}-"
        f"{proximo_mes:02d}-01"
    )

    cursor.execute("""
        SELECT
            categorias.nome,
            SUM(lancamentos.valor)
        FROM lancamentos
        INNER JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.tipo = 'despesa'
        AND lancamentos.data >= ?
        AND lancamentos.data < ?
        GROUP BY categorias.id, categorias.nome
        ORDER BY SUM(lancamentos.valor) DESC
    """, (inicio, fim))

    resultados = cursor.fetchall()

    conexao.close()

    return resultados

def buscar_lancamento(id_lancamento):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT
            lancamentos.id,
            lancamentos.data,
            lancamentos.descricao,
            lancamentos.tipo,
            categorias.nome,
            lancamentos.valor,
            lancamentos.categoria_id
        FROM lancamentos
        LEFT JOIN categorias
            ON lancamentos.categoria_id = categorias.id
        WHERE lancamentos.id = ?
        """,
        (id_lancamento,)
    )

    lancamento = cursor.fetchone()

    conexao.close()

    return lancamento


def atualizar_lancamento(
    id_lancamento,
    data,
    descricao,
    tipo,
    categoria_id,
    valor
):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT nome
        FROM categorias
        WHERE id = ?
        """,
        (categoria_id,)
    )

    categoria = cursor.fetchone()

    if categoria is None:
        conexao.close()
        return False

    nome_categoria = categoria[0]

    cursor.execute(
        """
        UPDATE lancamentos
        SET
            data = ?,
            descricao = ?,
            tipo = ?,
            categoria = ?,
            categoria_id = ?,
            valor = ?
        WHERE id = ?
        """,
        (
            data,
            descricao,
            tipo,
            nome_categoria,
            categoria_id,
            valor,
            id_lancamento
        )
    )

    atualizado = cursor.rowcount > 0

    conexao.commit()
    conexao.close()

    return atualizado

def excluir_lancamento(id_lancamento):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        DELETE FROM lancamentos
        WHERE id = ?
        """,
        (id_lancamento,)
    )

    excluido = cursor.rowcount > 0

    conexao.commit()
    conexao.close()

    return excluido

def adicionar_categoria(nome, tipo):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT id
        FROM categorias
        WHERE LOWER(nome) = LOWER(?)
        AND tipo = ?
        """,
        (nome, tipo)
    )

    existente = cursor.fetchone()

    if existente is not None:
        conexao.close()
        return False

    cursor.execute(
        """
        INSERT INTO categorias (
            nome,
            tipo
        )
        VALUES (?, ?)
        """,
        (nome, tipo)
    )

    conexao.commit()
    conexao.close()

    return True

def atualizar_categoria(id_categoria, nome, tipo):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT id
        FROM categorias
        WHERE LOWER(nome) = LOWER(?)
        AND tipo = ?
        AND id != ?
        """,
        (
            nome,
            tipo,
            id_categoria
        )
    )

    existente = cursor.fetchone()

    if existente is not None:
        conexao.close()
        return False

    cursor.execute(
        """
        UPDATE categorias
        SET
            nome = ?,
            tipo = ?
        WHERE id = ?
        """,
        (
            nome,
            tipo,
            id_categoria
        )
    )

    atualizado = cursor.rowcount > 0

    conexao.commit()
    conexao.close()

    return atualizado

def excluir_categoria(id_categoria):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM lancamentos
        WHERE categoria_id = ?
        """,
        (id_categoria,)
    )

    quantidade = cursor.fetchone()[0]

    if quantidade > 0:
        conexao.close()
        return False, quantidade

    cursor.execute(
        """
        DELETE FROM categorias
        WHERE id = ?
        """,
        (id_categoria,)
    )

    excluida = cursor.rowcount > 0

    conexao.commit()
    conexao.close()

    return excluida, 0

def criar_recorrencias():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    # ========================================
    # TABELA DE RECORRÊNCIAS
    # ========================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            frequencia TEXT NOT NULL,
            data_inicio TEXT NOT NULL,
            data_fim TEXT,
            ativa INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (categoria_id)
                REFERENCES categorias(id)
        )
    """)

    # ========================================
    # TABELA DE OCORRÊNCIAS
    # ========================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recorrencia_ocorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorrencia_id INTEGER NOT NULL,
            data_vencimento TEXT NOT NULL,
            valor REAL NOT NULL,
            pago INTEGER NOT NULL DEFAULT 0,
            data_pagamento TEXT,
            lancamento_id INTEGER,
            FOREIGN KEY (recorrencia_id)
                REFERENCES recorrencias(id),
            FOREIGN KEY (lancamento_id)
                REFERENCES lancamentos(id),
            UNIQUE (
                recorrencia_id,
                data_vencimento
            )
        )
    """)

    conexao.commit()
    conexao.close()


def migrar_lancamentos_recorrencia():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        PRAGMA table_info(lancamentos)
        """
    )

    colunas = cursor.fetchall()

    nomes_colunas = [
        coluna[1]
        for coluna in colunas
    ]

    if "recorrencia_id" not in nomes_colunas:
        cursor.execute(
            """
            ALTER TABLE lancamentos
            ADD COLUMN recorrencia_id INTEGER
            """
        )

    conexao.commit()
    conexao.close()

def migrar_lancamentos_parcelamento():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        PRAGMA table_info(lancamentos)
    """)

    colunas = cursor.fetchall()

    nomes_colunas = [
        coluna[1]
        for coluna in colunas
    ]

    if "parcelamento_id" not in nomes_colunas:
        cursor.execute("""
            ALTER TABLE lancamentos
            ADD COLUMN parcelamento_id INTEGER
        """)

    conexao.commit()
    conexao.close()

def adicionar_recorrencia(
    descricao,
    tipo,
    categoria_id,
    valor,
    frequencia,
    data_inicio,
    data_fim=None
):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute(
        """
        INSERT INTO recorrencias (
            descricao,
            tipo,
            categoria_id,
            valor,
            frequencia,
            data_inicio,
            data_fim,
            ativa
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            descricao,
            tipo,
            categoria_id,
            valor,
            frequencia,
            data_inicio,
            data_fim
        )
    )

    recorrencia_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO recorrencia_ocorrencias (
            recorrencia_id,
            data_vencimento,
            valor,
            pago
        )
        VALUES (?, ?, ?, 0)
        """,
        (
            recorrencia_id,
            data_inicio,
            valor
        )
    )

    conexao.commit()
    conexao.close()

    return recorrencia_id

def listar_recorrencias():
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            recorrencias.id,
            recorrencias.descricao,
            recorrencias.tipo,
            categorias.nome,
            recorrencias.valor,
            recorrencias.frequencia,
            recorrencias.data_inicio,
            recorrencias.data_fim,
            recorrencias.ativa
        FROM recorrencias
        INNER JOIN categorias
            ON recorrencias.categoria_id = categorias.id
        ORDER BY recorrencias.ativa DESC,
                 recorrencias.id
    """)

    recorrencias = cursor.fetchall()

    conexao.close()

    return recorrencias

def listar_ocorrencias_recorrencia(id_recorrencia):
    conexao = sqlite3.connect(obter_caminho_banco())

    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            recorrencia_ocorrencias.id,
            recorrencia_ocorrencias.data_vencimento,
            recorrencia_ocorrencias.valor,
            recorrencia_ocorrencias.pago,
            recorrencia_ocorrencias.data_pagamento,
            recorrencia_ocorrencias.lancamento_id
        FROM recorrencia_ocorrencias
        WHERE recorrencia_ocorrencias.recorrencia_id = ?
        ORDER BY recorrencia_ocorrencias.data_vencimento
    """, (id_recorrencia,))

    ocorrencias = cursor.fetchall()

    conexao.close()

    return ocorrencias    

def marcar_ocorrencia_paga(id_ocorrencia, data_pagamento):
    from datetime import datetime

    try:
        datetime.strptime(data_pagamento, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False

    conexao = sqlite3.connect(obter_caminho_banco())
    recorrencia_id = None

    try:
        cursor = conexao.cursor()
        conexao.execute("BEGIN IMMEDIATE")

        cursor.execute("""
            SELECT recorrencia_id, valor
            FROM recorrencia_ocorrencias
            WHERE id = ?
              AND pago = 0
        """, (id_ocorrencia,))

        ocorrencia = cursor.fetchone()

        if ocorrencia is None:
            return False

        recorrencia_id, valor = ocorrencia

        cursor.execute("""
            SELECT descricao, tipo, categoria_id
            FROM recorrencias
            WHERE id = ?
        """, (recorrencia_id,))

        recorrencia = cursor.fetchone()

        if recorrencia is None:
            return False

        descricao, tipo, categoria_id = recorrencia

        cursor.execute("""
            SELECT nome
            FROM categorias
            WHERE id = ?
        """, (categoria_id,))

        categoria = cursor.fetchone()

        if categoria is None:
            return False

        nome_categoria = categoria[0]

        cursor.execute("""
            INSERT INTO lancamentos (
                data,
                descricao,
                tipo,
                categoria,
                valor,
                categoria_id,
                recorrencia_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data_pagamento,
            descricao,
            tipo,
            nome_categoria,
            valor,
            categoria_id,
            recorrencia_id
        ))

        lancamento_id = cursor.lastrowid

        cursor.execute("""
            UPDATE recorrencia_ocorrencias
            SET
                pago = 1,
                data_pagamento = ?,
                lancamento_id = ?
            WHERE id = ?
              AND pago = 0
        """, (
            data_pagamento,
            lancamento_id,
            id_ocorrencia
        ))

        if cursor.rowcount != 1:
            conexao.rollback()
            return False

        conexao.commit()

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()

    # O pagamento ja foi confirmado.
    # Uma falha na geracao nao desfaz o pagamento.
    try:
        gerar_proxima_ocorrencia(recorrencia_id)
    except Exception as erro:
        print(
            "Aviso: pagamento registrado, mas houve "
            f"falha ao gerar a proxima ocorrencia: {erro}"
        )

    return True

def calcular_proxima_data_recorrencia(
    ultima_data,
    data_inicio,
    frequencia
):
    import calendar
    from datetime import datetime, timedelta

    if isinstance(ultima_data, str):
        ultima_data = datetime.strptime(
            ultima_data, "%Y-%m-%d"
        ).date()

    if isinstance(data_inicio, str):
        data_inicio = datetime.strptime(
            data_inicio, "%Y-%m-%d"
        ).date()

    if frequencia == "semanal":
        return ultima_data + timedelta(days=7)

    if frequencia == "mensal":
        mes = ultima_data.month + 1
        ano = ultima_data.year

        if mes > 12:
            mes = 1
            ano += 1

        ultimo_dia = calendar.monthrange(ano, mes)[1]

        dia = min(
            data_inicio.day,
            ultimo_dia
        )

        return ultima_data.replace(
            year=ano,
            month=mes,
            day=dia
        )

    if frequencia == "anual":
        ano = ultima_data.year + 1
        mes = data_inicio.month

        ultimo_dia = calendar.monthrange(ano, mes)[1]

        dia = min(
            data_inicio.day,
            ultimo_dia
        )

        return ultima_data.replace(
            year=ano,
            month=mes,
            day=dia
        )

    raise ValueError(
        f"Frequencia invalida: {frequencia}"
    )

def gerar_proxima_ocorrencia(id_recorrencia):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            valor,
            frequencia,
            data_fim,
            ativa,
            data_inicio
        FROM recorrencias
        WHERE id = ?
    """, (id_recorrencia,))

    recorrencia = cursor.fetchone()

    if recorrencia is None:
        conexao.close()
        return False

    valor, frequencia, data_fim, ativa, data_inicio = recorrencia

    if not ativa:
        conexao.close()
        return False

    cursor.execute("""
        SELECT
            data_vencimento
        FROM recorrencia_ocorrencias
        WHERE recorrencia_id = ?
        ORDER BY data_vencimento DESC
        LIMIT 1
    """, (id_recorrencia,))

    ultima_ocorrencia = cursor.fetchone()

    if ultima_ocorrencia is None:
        conexao.close()
        return False

    ultima_data = datetime.strptime(
        ultima_ocorrencia[0],
        "%Y-%m-%d"
       )

    if not data_inicio:
        conexao.close()
        return False

    if frequencia not in ("semanal", "mensal", "anual"):
        conexao.close()
        return False

    proxima_data = calcular_proxima_data_recorrencia(
        ultima_data,
        data_inicio,
        frequencia
    )

    proxima_data_str = proxima_data.strftime(
        "%Y-%m-%d"
    )

    if data_fim is not None:
        data_fim_objeto = datetime.strptime(
            data_fim,
            "%Y-%m-%d"
        )

        if proxima_data > data_fim_objeto:
            conexao.close()
            return False

    cursor.execute("""
        SELECT id
        FROM recorrencia_ocorrencias
        WHERE recorrencia_id = ?
        AND data_vencimento = ?
    """, (
        id_recorrencia,
        proxima_data_str
    ))

    existente = cursor.fetchone()

    if existente is not None:
        conexao.close()
        return False

    cursor.execute("""
        INSERT INTO recorrencia_ocorrencias (
            recorrencia_id,
            data_vencimento,
            valor,
            pago
        )
        VALUES (?, ?, ?, 0)
    """, (
        id_recorrencia,
        proxima_data_str,
        valor
    ))

    conexao.commit()
    conexao.close()

    return True    

def atualizar_recorrencia(
    id_recorrencia,
    descricao,
    tipo,
    categoria_id,
    valor,
    frequencia,
    data_fim
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id
        FROM recorrencias
        WHERE id = ?
    """, (id_recorrencia,))

    recorrencia = cursor.fetchone()

    if recorrencia is None:
        conexao.close()
        return False

    cursor.execute("""
        UPDATE recorrencias
        SET
            descricao = ?,
            tipo = ?,
            categoria_id = ?,
            valor = ?,
            frequencia = ?,
            data_fim = ?
        WHERE id = ?
    """, (
        descricao,
        tipo,
        categoria_id,
        valor,
        frequencia,
        data_fim,
        id_recorrencia
    ))

    # Atualiza o valor das ocorrências
    # que ainda não foram pagas.
    cursor.execute("""
        UPDATE recorrencia_ocorrencias
        SET valor = ?
        WHERE recorrencia_id = ?
        AND pago = 0
    """, (
        valor,
        id_recorrencia
    ))

    conexao.commit()
    conexao.close()

    return True

def alterar_status_recorrencia(
    id_recorrencia,
    ativa
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        UPDATE recorrencias
        SET ativa = ?
        WHERE id = ?
    """, (
        1 if ativa else 0,
        id_recorrencia
    ))

    alteracoes = cursor.rowcount

    conexao.commit()
    conexao.close()

    return alteracoes > 0    

def excluir_recorrencia(id_recorrencia):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("BEGIN")

        cursor.execute("""
            SELECT id
            FROM recorrencias
            WHERE id = ?
        """, (id_recorrencia,))

        recorrencia = cursor.fetchone()

        if recorrencia is None:
            conexao.rollback()
            conexao.close()
            return False

        # Remove o vínculo dos lançamentos já criados.
        # Os lançamentos financeiros permanecem no banco.
        cursor.execute("""
            UPDATE lancamentos
            SET recorrencia_id = NULL
            WHERE recorrencia_id = ?
        """, (id_recorrencia,))

        # Remove as ocorrências da recorrência.
        cursor.execute("""
            DELETE FROM recorrencia_ocorrencias
            WHERE recorrencia_id = ?
        """, (id_recorrencia,))

        # Remove a regra da recorrência.
        cursor.execute("""
            DELETE FROM recorrencias
            WHERE id = ?
        """, (id_recorrencia,))

        conexao.commit()
        conexao.close()

        return True

    except Exception:
        conexao.rollback()
        conexao.close()

        return False

def sincronizar_recorrencias():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            id,
            frequencia,
            data_fim,
            ativa,
            data_inicio
        FROM recorrencias
        WHERE ativa = 1
    """)

    recorrencias = cursor.fetchall()

    hoje = datetime.now().date()

    total_criadas = 0

    for recorrencia in recorrencias:
        (
            id_recorrencia,
            frequencia,
            data_fim,
            ativa,
            data_inicio
        ) = recorrencia

        cursor.execute("""
            SELECT
                data_vencimento
            FROM recorrencia_ocorrencias
            WHERE recorrencia_id = ?
            ORDER BY data_vencimento DESC
            LIMIT 1
        """, (id_recorrencia,))

        ultima_ocorrencia = cursor.fetchone()

        if ultima_ocorrencia is None:
            continue

        ultima_data = datetime.strptime(
            ultima_ocorrencia[0],
            "%Y-%m-%d"
        ).date()

        while True:
            if not data_inicio:
                break

            if frequencia not in ("semanal", "mensal", "anual"):
                break

            proxima_data = calcular_proxima_data_recorrencia(
                ultima_data,
                data_inicio,
                frequencia
            )

            if data_fim is not None:
                data_fim_objeto = datetime.strptime(
                    data_fim,
                    "%Y-%m-%d"
                ).date()

                if proxima_data > data_fim_objeto:
                    break

            if proxima_data > hoje:
                break

            proxima_data_str = (
                proxima_data.strftime("%Y-%m-%d")
            )

            cursor.execute("""
                SELECT id
                FROM recorrencia_ocorrencias
                WHERE recorrencia_id = ?
                AND data_vencimento = ?
            """, (
                id_recorrencia,
                proxima_data_str
            ))

            existente = cursor.fetchone()

            if existente is None:
                cursor.execute("""
                    SELECT valor
                    FROM recorrencias
                    WHERE id = ?
                """, (id_recorrencia,))

                resultado_valor = cursor.fetchone()

                if resultado_valor is None:
                    break

                valor = resultado_valor[0]

                cursor.execute("""
                    INSERT INTO recorrencia_ocorrencias (
                        recorrencia_id,
                        data_vencimento,
                        valor,
                        pago
                    )
                    VALUES (?, ?, ?, 0)
                """, (
                    id_recorrencia,
                    proxima_data_str,
                    valor
                ))

                total_criadas += 1

            ultima_data = proxima_data

    conexao.commit()
    conexao.close()

    return total_criadas

def resumo_ocorrencias_recorrencia(id_recorrencia):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(
                CASE
                    WHEN pago = 1 THEN 1
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 0 THEN 1
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 1 THEN valor
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 0 THEN valor
                    ELSE 0
                END
            ), 0)
        FROM recorrencia_ocorrencias
        WHERE recorrencia_id = ?
    """, (id_recorrencia,))

    resultado = cursor.fetchone()

    conexao.close()

    return resultado

def criar_parcelamentos():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parcelamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria_id INTEGER NOT NULL,
            valor_total REAL NOT NULL,
            quantidade_parcelas INTEGER NOT NULL,
            data_inicio TEXT NOT NULL,
            ativa INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (categoria_id)
                REFERENCES categorias(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parcelamento_parcelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parcelamento_id INTEGER NOT NULL,
            numero_parcela INTEGER NOT NULL,
            data_vencimento TEXT NOT NULL,
            valor REAL NOT NULL,
            pago INTEGER NOT NULL DEFAULT 0,
            data_pagamento TEXT,
            lancamento_id INTEGER,
            FOREIGN KEY (parcelamento_id)
                REFERENCES parcelamentos(id),
            FOREIGN KEY (lancamento_id)
                REFERENCES lancamentos(id),
            UNIQUE (
                parcelamento_id,
                numero_parcela
            )
        )
    """)

    conexao.commit()
    conexao.close()    

def adicionar_parcelamento(
    descricao,
    tipo,
    categoria_id,
    valor_total,
    quantidade_parcelas,
    data_inicio
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    valor_parcela = (
        valor_total / quantidade_parcelas
    )

    cursor.execute("""
        INSERT INTO parcelamentos (
            descricao,
            tipo,
            categoria_id,
            valor_total,
            quantidade_parcelas,
            data_inicio,
            ativa
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        descricao,
        tipo,
        categoria_id,
        valor_total,
        quantidade_parcelas,
        data_inicio
    ))

    parcelamento_id = cursor.lastrowid

    data_atual = datetime.strptime(
        data_inicio,
        "%Y-%m-%d"
    )

    for numero_parcela in range(
        1,
        quantidade_parcelas + 1
    ):
        if numero_parcela == 1:
            data_vencimento = data_atual

        else:
            mes = data_atual.month + 1
            ano = data_atual.year

            if mes > 12:
                mes = 1
                ano += 1

            try:
                data_atual = data_atual.replace(
                    year=ano,
                    month=mes
                )

            except ValueError:
                import calendar

                ultimo_dia = calendar.monthrange(
                    ano,
                    mes
                )[1]

                data_atual = data_atual.replace(
                    year=ano,
                    month=mes,
                    day=ultimo_dia
                )

            data_vencimento = data_atual

        data_vencimento_str = (
            data_vencimento.strftime(
                "%Y-%m-%d"
            )
        )

        cursor.execute("""
            INSERT INTO parcelamento_parcelas (
                parcelamento_id,
                numero_parcela,
                data_vencimento,
                valor,
                pago
            )
            VALUES (?, ?, ?, ?, 0)
        """, (
            parcelamento_id,
            numero_parcela,
            data_vencimento_str,
            valor_parcela
        ))

    conexao.commit()
    conexao.close()

    return parcelamento_id    

def listar_parcelamentos():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            parcelamentos.id,
            parcelamentos.descricao,
            parcelamentos.tipo,
            categorias.nome,
            parcelamentos.valor_total,
            parcelamentos.quantidade_parcelas,
            parcelamentos.data_inicio,
            parcelamentos.ativa
        FROM parcelamentos
        INNER JOIN categorias
            ON parcelamentos.categoria_id = categorias.id
        ORDER BY parcelamentos.ativa DESC,
                 parcelamentos.id
    """)

    parcelamentos = cursor.fetchall()

    conexao.close()

    return parcelamentos    

def listar_parcelas_parcelamento(id_parcelamento):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            id,
            numero_parcela,
            data_vencimento,
            valor,
            pago,
            data_pagamento,
            lancamento_id
        FROM parcelamento_parcelas
        WHERE parcelamento_id = ?
        ORDER BY numero_parcela
    """, (id_parcelamento,))

    parcelas = cursor.fetchall()

    conexao.close()

    return parcelas    

def resumo_parcelas_parcelamento(id_parcelamento):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(
                CASE
                    WHEN pago = 1 THEN 1
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 0 THEN 1
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 1 THEN valor
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN pago = 0 THEN valor
                    ELSE 0
                END
            ), 0)
        FROM parcelamento_parcelas
        WHERE parcelamento_id = ?
    """, (id_parcelamento,))

    resultado = cursor.fetchone()

    conexao.close()

    return resultado    

def marcar_parcela_paga(id_parcela, data_pagamento):
    from datetime import datetime

    try:
        datetime.strptime(data_pagamento, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False

    conexao = sqlite3.connect(obter_caminho_banco())

    try:
        cursor = conexao.cursor()

        # Inicia transacao de escrita antes de consultar o status.
        conexao.execute("BEGIN IMMEDIATE")

        cursor.execute("""
            SELECT
                parcelamento_id,
                valor
            FROM parcelamento_parcelas
            WHERE id = ?
              AND pago = 0
        """, (id_parcela,))

        parcela = cursor.fetchone()

        if parcela is None:
            return False

        parcelamento_id, valor = parcela

        cursor.execute("""
            SELECT
                descricao,
                tipo,
                categoria_id
            FROM parcelamentos
            WHERE id = ?
        """, (parcelamento_id,))

        parcelamento = cursor.fetchone()

        if parcelamento is None:
            return False

        descricao, tipo, categoria_id = parcelamento

        cursor.execute("""
            SELECT nome
            FROM categorias
            WHERE id = ?
        """, (categoria_id,))

        categoria = cursor.fetchone()

        if categoria is None:
            return False

        nome_categoria = categoria[0]

        cursor.execute("""
            INSERT INTO lancamentos (
                data,
                descricao,
                tipo,
                categoria,
                valor,
                categoria_id,
                parcelamento_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data_pagamento,
            descricao,
            tipo,
            nome_categoria,
            valor,
            categoria_id,
            parcelamento_id
        ))

        lancamento_id = cursor.lastrowid

        cursor.execute("""
            UPDATE parcelamento_parcelas
            SET
                pago = 1,
                data_pagamento = ?,
                lancamento_id = ?
            WHERE id = ?
              AND pago = 0
        """, (
            data_pagamento,
            lancamento_id,
            id_parcela
        ))

        if cursor.rowcount != 1:
            conexao.rollback()
            return False

        conexao.commit()
        return True

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()

def atualizar_parcelamento(
    id_parcelamento,
    descricao,
    categoria_id
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id
        FROM parcelamentos
        WHERE id = ?
    """, (id_parcelamento,))

    parcelamento = cursor.fetchone()

    if parcelamento is None:
        conexao.close()
        return False

    cursor.execute("""
        UPDATE parcelamentos
        SET
            descricao = ?,
            categoria_id = ?
        WHERE id = ?
    """, (
        descricao,
        categoria_id,
        id_parcelamento
    ))

    conexao.commit()
    conexao.close()

    return True    

def alterar_status_parcelamento(
    id_parcelamento,
    ativa
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id
        FROM parcelamentos
        WHERE id = ?
    """, (id_parcelamento,))

    parcelamento = cursor.fetchone()

    if parcelamento is None:
        conexao.close()
        return False

    cursor.execute("""
        UPDATE parcelamentos
        SET ativa = ?
        WHERE id = ?
    """, (
        ativa,
        id_parcelamento
    ))

    conexao.commit()
    conexao.close()

    return True    

def excluir_parcelamento(id_parcelamento):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT id
        FROM parcelamentos
        WHERE id = ?
    """, (id_parcelamento,))

    parcelamento = cursor.fetchone()

    if parcelamento is None:
        conexao.close()
        return False, "nao_encontrado"

    cursor.execute("""
        SELECT COUNT(*)
        FROM parcelamento_parcelas
        WHERE parcelamento_id = ?
        AND pago = 1
    """, (id_parcelamento,))

    parcelas_pagas = cursor.fetchone()[0]

    if parcelas_pagas > 0:
        conexao.close()
        return False, "possui_pagamentos"

    cursor.execute("""
        DELETE FROM parcelamento_parcelas
        WHERE parcelamento_id = ?
    """, (id_parcelamento,))

    cursor.execute("""
        DELETE FROM parcelamentos
        WHERE id = ?
    """, (id_parcelamento,))

    conexao.commit()
    conexao.close()

    return True, "excluido"    

def criar_cartoes():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cartoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            limite REAL NOT NULL,
            dia_fechamento INTEGER NOT NULL,
            dia_vencimento INTEGER NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1
        )
    """)

    conexao.commit()
    conexao.close()    

def adicionar_cartao(
    nome,
    limite,
    dia_fechamento,
    dia_vencimento
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        INSERT INTO cartoes (
            nome,
            limite,
            dia_fechamento,
            dia_vencimento
        )
        VALUES (?, ?, ?, ?)
    """, (
        nome,
        limite,
        dia_fechamento,
        dia_vencimento
    ))

    conexao.commit()
    conexao.close()    

def listar_cartoes():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            id,
            nome,
            limite,
            dia_fechamento,
            dia_vencimento,
            ativo
        FROM cartoes
        ORDER BY id
    """)

    cartoes = cursor.fetchall()

    conexao.close()

    return cartoes  

def criar_faturas():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            data_fechamento TEXT NOT NULL,
            data_vencimento TEXT NOT NULL,
            valor_total REAL NOT NULL DEFAULT 0,
            paga INTEGER NOT NULL DEFAULT 0,
            data_pagamento TEXT,
            FOREIGN KEY (cartao_id)
                REFERENCES cartoes(id),
            UNIQUE (cartao_id, mes, ano)
        )
    """)

    conexao.commit()
    conexao.close()      

def criar_compras_cartao():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compras_cartao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id INTEGER NOT NULL,
            fatura_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            data_compra TEXT NOT NULL,
            valor REAL NOT NULL,
            FOREIGN KEY (cartao_id)
                REFERENCES cartoes(id),
            FOREIGN KEY (fatura_id)
                REFERENCES faturas(id),
            FOREIGN KEY (categoria_id)
                REFERENCES categorias(id)
        )
    """)

    conexao.commit()
    conexao.close()

def criar_parcelas_cartao():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parcelas_cartao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id INTEGER NOT NULL,
            numero_parcela INTEGER NOT NULL,
            total_parcelas INTEGER NOT NULL,
            fatura_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            FOREIGN KEY (compra_id)
                REFERENCES compras_cartao(id),
            FOREIGN KEY (fatura_id)
                REFERENCES faturas(id),
            UNIQUE (
                compra_id,
                numero_parcela
            )
        )
    """)

    conexao.commit()
    conexao.close()


def calcular_periodo_fatura(
    data_compra,
    dia_fechamento,
    dia_vencimento
):
    data = datetime.strptime(
        data_compra,
        "%Y-%m-%d"
    )

    ano = data.year
    mes = data.month

    # Compras no dia do fechamento entram na próxima fatura.
    if data.day >= dia_fechamento:
        mes += 1

        if mes == 13:
            mes = 1
            ano += 1

    # Calcula a data de fechamento da fatura.
    ultimo_dia_fechamento = calendar.monthrange(
        ano,
        mes
    )[1]

    dia_fechamento_real = min(
        dia_fechamento,
        ultimo_dia_fechamento
    )

    data_fechamento = datetime(
        ano,
        mes,
        dia_fechamento_real
    )

    # O vencimento ocorre no mês seguinte ao fechamento.
    ano_vencimento = ano
    mes_vencimento = mes + 1

    if mes_vencimento == 13:
        mes_vencimento = 1
        ano_vencimento += 1

    ultimo_dia_vencimento = calendar.monthrange(
        ano_vencimento,
        mes_vencimento
    )[1]

    dia_vencimento_real = min(
        dia_vencimento,
        ultimo_dia_vencimento
    )

    data_vencimento = datetime(
        ano_vencimento,
        mes_vencimento,
        dia_vencimento_real
    )

    return (
        ano,
        mes,
        data_fechamento.strftime("%Y-%m-%d"),
        data_vencimento.strftime("%Y-%m-%d")
    )

def obter_ou_criar_fatura(
    cartao_id,
    data_compra
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT
            dia_fechamento,
            dia_vencimento
        FROM cartoes
        WHERE id = ?
    """, (cartao_id,))

    cartao = cursor.fetchone()

    if cartao is None:
        conexao.close()
        return None

    dia_fechamento, dia_vencimento = cartao

    (
        ano,
        mes,
        data_fechamento,
        data_vencimento
    ) = calcular_periodo_fatura(
        data_compra,
        dia_fechamento,
        dia_vencimento
    )

    cursor.execute("""
        SELECT id
        FROM faturas
        WHERE cartao_id = ?
        AND mes = ?
        AND ano = ?
    """, (
        cartao_id,
        mes,
        ano
    ))

    fatura = cursor.fetchone()

    if fatura is not None:
        conexao.close()
        return fatura[0]

    cursor.execute("""
        INSERT INTO faturas (
            cartao_id,
            mes,
            ano,
            data_fechamento,
            data_vencimento
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        cartao_id,
        mes,
        ano,
        data_fechamento,
        data_vencimento
    ))

    id_fatura = cursor.lastrowid

    conexao.commit()
    conexao.close()

    return id_fatura

def listar_faturas(cartao_id=None):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    query = """
        SELECT
            f.id,
            f.cartao_id,
            c.nome,
            f.mes,
            f.ano,
            f.data_fechamento,
            f.data_vencimento,
            f.valor_total,
            f.paga
        FROM faturas f
        INNER JOIN cartoes c
            ON c.id = f.cartao_id
    """

    parametros = []

    if cartao_id is not None:
        query += """
            WHERE f.cartao_id = ?
        """
        parametros.append(cartao_id)

    query += """
        ORDER BY
            f.ano,
            f.mes,
            f.cartao_id
    """

    cursor.execute(query, parametros)

    faturas = cursor.fetchall()

    conexao.close()

    return faturas  

def pagar_fatura(id_fatura, data_pagamento):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT
                paga,
                valor_total
            FROM faturas
            WHERE id = ?
        """, (id_fatura,))

        fatura = cursor.fetchone()

        if fatura is None:
            return False, "fatura_inexistente"

        paga, valor_total = fatura

        if paga == 1:
            return False, "fatura_ja_paga"

        cursor.execute("""
            UPDATE faturas
            SET
                paga = 1,
                data_pagamento = ?
            WHERE id = ?
        """, (
            data_pagamento,
            id_fatura
        ))

        conexao.commit()

        return True, valor_total

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()

def adicionar_compra_cartao(
    cartao_id,
    categoria_id,
    descricao,
    data_compra,
    valor
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT id
            FROM cartoes
            WHERE id = ?
            AND ativo = 1
        """, (cartao_id,))

        cartao = cursor.fetchone()

        if cartao is None:
            return False, "cartao_invalido"

        cursor.execute("""
            SELECT id
            FROM categorias
            WHERE id = ?
            AND tipo = 'despesa'
        """, (categoria_id,))

        categoria = cursor.fetchone()

        if categoria is None:
            return False, "categoria_invalida"

        limite_disponivel = calcular_limite_disponivel(
            cartao_id
        )

        if limite_disponivel is None:
            return False, "cartao_invalido"

        if valor > limite_disponivel:
            return False, (
                "limite_insuficiente",
                limite_disponivel
            )

        cursor.execute("""
            SELECT
                dia_fechamento,
                dia_vencimento
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        dados_cartao = cursor.fetchone()

        dia_fechamento, dia_vencimento = dados_cartao

        (
            ano,
            mes,
            data_fechamento,
            data_vencimento
        ) = calcular_periodo_fatura(
            data_compra,
            dia_fechamento,
            dia_vencimento
        )

        cursor.execute("""
            SELECT id
            FROM faturas
            WHERE cartao_id = ?
            AND mes = ?
            AND ano = ?
        """, (
            cartao_id,
            mes,
            ano
        ))

        fatura = cursor.fetchone()

        if fatura is None:
            cursor.execute("""
                INSERT INTO faturas (
                    cartao_id,
                    mes,
                    ano,
                    data_fechamento,
                    data_vencimento
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                cartao_id,
                mes,
                ano,
                data_fechamento,
                data_vencimento
            ))

            fatura_id = cursor.lastrowid

        else:
            fatura_id = fatura[0]

        cursor.execute("""
            SELECT paga
            FROM faturas
            WHERE id = ?
        """, (fatura_id,))

        fatura_status = cursor.fetchone()

        if fatura_status is None:
            return False, "fatura_invalida"

        if fatura_status[0] == 1:
            return False, "fatura_paga"

        cursor.execute("""
            INSERT INTO compras_cartao (
                cartao_id,
                fatura_id,
                categoria_id,
                descricao,
                data_compra,
                valor
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cartao_id,
            fatura_id,
            categoria_id,
            descricao,
            data_compra,
            valor
        ))

        id_compra = cursor.lastrowid

        
        cursor.execute("""
            UPDATE faturas
            SET valor_total = (
                COALESCE(
                    (
                        SELECT SUM(cc.valor)
                        FROM compras_cartao cc
                        WHERE cc.fatura_id = ?
                        AND NOT EXISTS (
                            SELECT 1
                            FROM parcelas_cartao pc
                            WHERE pc.compra_id = cc.id
                        )
                    ),
                    0
                )
                +
                COALESCE(
                    (
                        SELECT SUM(pc.valor)
                        FROM parcelas_cartao pc
                        WHERE pc.fatura_id = ?
                    ),
                    0
                )
            )
            WHERE id = ?
        """, (
            fatura_id,
            fatura_id,
            fatura_id
        ))

        conexao.commit()

        return True, (
            id_compra,
            fatura_id
        )

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close() 

def listar_compras_cartao(fatura_id=None):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    query = """
        SELECT
            cc.id,
            cc.cartao_id,
            cc.fatura_id,
            c.nome,
            cc.categoria_id,
            cat.nome,
            cc.descricao,
            cc.data_compra,
            cc.valor
        FROM compras_cartao cc
        INNER JOIN cartoes c
            ON c.id = cc.cartao_id
        INNER JOIN categorias cat
            ON cat.id = cc.categoria_id
    """

    parametros = []

    if fatura_id is not None:
        query += """
            WHERE cc.fatura_id = ?
        """
        parametros.append(fatura_id)

    query += """
        ORDER BY cc.data_compra, cc.id
    """

    cursor.execute(query, parametros)

    compras = cursor.fetchall()

    conexao.close()

    return compras  

def adicionar_compra_parcelada_cartao(
    cartao_id,
    categoria_id,
    descricao,
    data_compra,
    valor_total,
    quantidade_parcelas
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
      
        if quantidade_parcelas <= 1:
            return False, "quantidade_invalida"

        if valor_total <= 0:
            return False, "valor_invalido"

        if not descricao.strip():
            return False, "descricao_invalida"

        try:
            datetime.strptime(data_compra, "%Y-%m-%d")
        except (ValueError, TypeError):
            return False, "data_invalida"


        cursor.execute("""
            SELECT
                dia_fechamento,
                dia_vencimento
            FROM cartoes
            WHERE id = ?
            AND ativo = 1
        """, (cartao_id,))

        cartao = cursor.fetchone()

        if cartao is None:
            return False, "cartao_invalido"

        dia_fechamento, dia_vencimento = cartao

        cursor.execute("""
            SELECT id
            FROM categorias
            WHERE id = ?
            AND tipo = 'despesa'
        """, (categoria_id,))

        if cursor.fetchone() is None:
            return False, "categoria_invalida"

        # Verifica o limite antes de criar
        # qualquer fatura ou parcela.
        limite_disponivel = calcular_limite_disponivel(
            cartao_id
        )

        if limite_disponivel is None:
            return False, "cartao_invalido"

        if valor_total > limite_disponivel:
            return False, (
                "limite_insuficiente",
                limite_disponivel
            )

        valor_parcela = round(
            valor_total / quantidade_parcelas,
            2
        )

        data_base = datetime.strptime(
            data_compra,
            "%Y-%m-%d"
        )

        faturas_criadas = []

        for numero in range(
            1,
            quantidade_parcelas + 1
        ):
            mes = data_base.month + numero - 1
            ano = data_base.year

            while mes > 12:
                mes -= 12
                ano += 1

            # Mantém o dia da compra quando ele existe.
            # Se não existir no mês futuro, usa o último dia daquele mês.
            if mes == 12:
                proximo_mes = 1
                proximo_ano = ano + 1
            else:
                proximo_mes = mes + 1
                proximo_ano = ano

            ultimo_dia = (
                datetime(
                    proximo_ano,
                    proximo_mes,
                    1
                )
                - timedelta(days=1)
            ).day

            dia = min(
                data_base.day,
                ultimo_dia
            )

            data_referencia = datetime(
                ano,
                mes,
                dia
            ).strftime("%Y-%m-%d")

            (
                ano_fatura,
                mes_fatura,
                data_fechamento,
                data_vencimento
            ) = calcular_periodo_fatura(
                data_referencia,
                dia_fechamento,
                dia_vencimento
            )

            cursor.execute("""
                SELECT
                    id,
                    paga
                FROM faturas
                WHERE cartao_id = ?
                AND mes = ?
                AND ano = ?
            """, (
                cartao_id,
                mes_fatura,
                ano_fatura
            ))

            fatura = cursor.fetchone()

            if fatura is None:
                cursor.execute("""
                    INSERT INTO faturas (
                        cartao_id,
                        mes,
                        ano,
                        data_fechamento,
                        data_vencimento
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    cartao_id,
                    mes_fatura,
                    ano_fatura,
                    data_fechamento,
                    data_vencimento
                ))

                fatura_id = cursor.lastrowid

            
            else:
                fatura_id, paga = fatura

                if paga == 1:
                    conexao.rollback()
                    return False, "fatura_paga"

                # Atualiza as datas da fatura existente,
                # sem alterar valores nem faturas pagas.
                cursor.execute("""
                    UPDATE faturas
                    SET data_fechamento = ?,
                        data_vencimento = ?
                    WHERE id = ?
                    AND paga = 0
                """, (
                    data_fechamento,
                    data_vencimento,
                    fatura_id
                ))


            faturas_criadas.append(
                fatura_id
            )

        # Cria a compra somente depois
        # de validar todas as faturas.
        primeira_fatura_id = faturas_criadas[0]

        cursor.execute("""
            INSERT INTO compras_cartao (
                cartao_id,
                fatura_id,
                categoria_id,
                descricao,
                data_compra,
                valor
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cartao_id,
            primeira_fatura_id,
            categoria_id,
            descricao,
            data_compra,
            valor_total
        ))

        compra_id = cursor.lastrowid

        for numero, fatura_id in enumerate(
            faturas_criadas,
            start=1
        ):
            if numero == quantidade_parcelas:
                valor = round(
                    valor_total
                    - (
                        valor_parcela
                        * (quantidade_parcelas - 1)
                    ),
                    2
                )
            else:
                valor = valor_parcela

            cursor.execute("""
                INSERT INTO parcelas_cartao (
                    compra_id,
                    numero_parcela,
                    total_parcelas,
                    fatura_id,
                    valor
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                compra_id,
                numero,
                quantidade_parcelas,
                fatura_id,
                valor
            ))

        # Recalcula todas as faturas envolvidas.
        for fatura_id in set(faturas_criadas):

            cursor.execute("""
                UPDATE faturas
                SET valor_total = (
                    COALESCE(
                        (
                            SELECT SUM(cc.valor)
                            FROM compras_cartao cc
                            WHERE cc.fatura_id = ?
                            AND NOT EXISTS (
                                SELECT 1
                                FROM parcelas_cartao pc
                                WHERE pc.compra_id = cc.id
                            )
                        ),
                        0
                    )
                    +
                    COALESCE(
                        (
                            SELECT SUM(pc.valor)
                            FROM parcelas_cartao pc
                            WHERE pc.fatura_id = ?
                        ),
                        0
                    )
                )
                WHERE id = ?
            """, (
                fatura_id,
                fatura_id,
                fatura_id
            ))

        conexao.commit()

        return True, (
            compra_id,
            quantidade_parcelas
        )

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()    

def calcular_limite_utilizado(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN pc.id IS NOT NULL
                        THEN 0
                        ELSE cc.valor
                    END
                ), 0)
            FROM compras_cartao cc
            JOIN faturas f
                ON f.id = cc.fatura_id
            LEFT JOIN parcelas_cartao pc
                ON pc.compra_id = cc.id
            WHERE cc.cartao_id = ?
            AND f.paga = 0
        """, (cartao_id,))

        compras_normais = cursor.fetchone()[0]

        cursor.execute("""
            SELECT
                COALESCE(SUM(pc.valor), 0)
            FROM parcelas_cartao pc
            JOIN compras_cartao cc
                ON cc.id = pc.compra_id
            JOIN faturas f
                ON f.id = pc.fatura_id
            WHERE cc.cartao_id = ?
            AND f.paga = 0
        """, (cartao_id,))

        parcelas_abertas = cursor.fetchone()[0]

        return round(
            compras_normais + parcelas_abertas,
            2
        )

    finally:
        conexao.close()       

def calcular_limite_disponivel(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT limite
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        cartao = cursor.fetchone()

        if cartao is None:
            return None

        limite_total = cartao[0]

        limite_utilizado = calcular_limite_utilizado(
            cartao_id
        )

        return round(
            limite_total - limite_utilizado,
            2
        )

    finally:
        conexao.close()         

def obter_dashboard():
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        # ==============================
        # RECEITAS E DESPESAS
        # ==============================

        cursor.execute("""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN tipo = 'receita' THEN valor
                        ELSE 0
                    END
                ), 0),

                COALESCE(SUM(
                    CASE
                        WHEN tipo = 'despesa' THEN valor
                        ELSE 0
                    END
                ), 0)

            FROM lancamentos
        """)

        receitas, despesas = cursor.fetchone()

        saldo = receitas - despesas

        # ==============================
        # CARTÕES
        # ==============================

        cursor.execute("""
            SELECT COALESCE(SUM(limite), 0)
            FROM cartoes
            WHERE ativo = 1
        """)

        limite_total = cursor.fetchone()[0]

        # Utilização dos cartões
        cursor.execute("""
            SELECT id
            FROM cartoes
            WHERE ativo = 1
        """)

        cartoes = cursor.fetchall()

        limite_utilizado = 0

        for (cartao_id,) in cartoes:
            limite_utilizado += calcular_limite_utilizado(
                cartao_id
            )

        limite_disponivel = limite_total - limite_utilizado
        
        # ==============================
        # INDICADORES
        # ==============================

        cursor.execute("""
            SELECT COUNT(*)
            FROM cartoes
            WHERE ativo = 1
        """)

        quantidade_cartoes_ativos = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM faturas
            WHERE paga = 0
        """)

        quantidade_faturas_abertas = cursor.fetchone()[0]

        if limite_total > 0:
            percentual_limite_utilizado = (
                limite_utilizado / limite_total
            ) * 100
        else:
            percentual_limite_utilizado = 0

        # ==============================
        # FATURAS ABERTAS
        # ==============================

        cursor.execute("""
            SELECT COALESCE(SUM(valor_total), 0)
            FROM faturas
            WHERE paga = 0
        """)

        faturas_abertas = cursor.fetchone()[0]

        # ==============================
        # RECORRÊNCIAS
        # ==============================

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0)
            FROM recorrencia_ocorrencias
            WHERE pago = 0
        """)

        recorrencias_abertas = cursor.fetchone()[0]

        # ==============================
        # PARCELAMENTOS
        # ==============================

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0)
            FROM parcelamento_parcelas
            WHERE pago = 0
        """)

        parcelamentos_abertos = cursor.fetchone()[0]

        return {
            "receitas": round(receitas, 2),
            "despesas": round(despesas, 2),
            "saldo": round(saldo, 2),

            "limite_total": round(limite_total, 2),
            "limite_utilizado": round(limite_utilizado, 2),
            "limite_disponivel": round(limite_disponivel, 2),

            "faturas_abertas": round(faturas_abertas, 2),
            "recorrencias_abertas": round(
                recorrencias_abertas, 2
            ),
            "parcelamentos_abertos": round(
                parcelamentos_abertos, 2
            ),
            "quantidade_cartoes_ativos":
                quantidade_cartoes_ativos,

            "quantidade_faturas_abertas":
                quantidade_faturas_abertas,

            "percentual_limite_utilizado":
                round(
                    percentual_limite_utilizado,
                    2
                )
 
        }

    finally:
        conexao.close()

def obter_resumo_mensal_detalhado(ano, mes):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        periodo = f"{ano:04d}-{mes:02d}"

        # ==============================
        # RECEITAS E DESPESAS
        # ==============================

        cursor.execute("""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN tipo = 'receita' THEN valor
                        ELSE 0
                    END
                ), 0),

                COALESCE(SUM(
                    CASE
                        WHEN tipo = 'despesa' THEN valor
                        ELSE 0
                    END
                ), 0),

                COUNT(
                    CASE
                        WHEN tipo = 'receita' THEN 1
                    END
                ),

                COUNT(
                    CASE
                        WHEN tipo = 'despesa' THEN 1
                    END
                )

            FROM lancamentos
            WHERE substr(data, 1, 7) = ?
        """, (periodo,))

        (
            receitas,
            despesas,
            quantidade_receitas,
            quantidade_despesas
        ) = cursor.fetchone()

        saldo = receitas - despesas

        # ==============================
        # MAIOR CATEGORIA DE DESPESA
        # ==============================

        cursor.execute("""
            SELECT
                c.nome,
                SUM(l.valor)
            FROM lancamentos l
            JOIN categorias c
                ON c.id = l.categoria_id
            WHERE l.tipo = 'despesa'
            AND substr(l.data, 1, 7) = ?
            GROUP BY c.id, c.nome
            ORDER BY SUM(l.valor) DESC
            LIMIT 1
        """, (periodo,))

        maior_categoria = cursor.fetchone()

        # ==============================
        # GASTOS NO CARTÃO
        # ==============================

        cursor.execute("""
            SELECT
                COALESCE(SUM(cc.valor), 0)
            FROM compras_cartao cc
            WHERE substr(cc.data_compra, 1, 7) = ?
        """, (periodo,))

        gastos_cartao = cursor.fetchone()[0]

                # ==============================
        # FATURAS DO MÊS DE FECHAMENTO
        # ==============================

        cursor.execute("""
            SELECT
                COALESCE(SUM(valor_total), 0)
            FROM faturas
            WHERE ano = ?
              AND mes = ?
        """, (ano, mes))

        valor_faturas_mes = cursor.fetchone()[0]

        return {
            "receitas": round(receitas, 2),
            "despesas": round(despesas, 2),
            "saldo": round(saldo, 2),
            "valor_faturas_mes": round(valor_faturas_mes, 2),

            "quantidade_receitas": quantidade_receitas,
            "quantidade_despesas": quantidade_despesas,

            "maior_categoria": (
                maior_categoria[0]
                if maior_categoria
                else None
            ),

            "maior_categoria_valor": (
                round(maior_categoria[1], 2)
                if maior_categoria
                else 0
            ),

            "gastos_cartao": round(
                gastos_cartao,
                2
            )
        }

    finally:
        conexao.close()

def obter_evolucao_anual(ano):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        evolucao = []

        for mes in range(1, 13):

            periodo = f"{ano:04d}-{mes:02d}"

            cursor.execute("""
                SELECT
                    COALESCE(SUM(
                        CASE
                            WHEN tipo = 'receita' THEN valor
                            ELSE 0
                        END
                    ), 0),

                    COALESCE(SUM(
                        CASE
                            WHEN tipo = 'despesa' THEN valor
                            ELSE 0
                        END
                    ), 0)

                FROM lancamentos
                WHERE substr(data, 1, 7) = ?
            """, (periodo,))

            receitas, despesas = cursor.fetchone()

            saldo = receitas - despesas

            evolucao.append({
                "mes": mes,
                "receitas": round(receitas, 2),
                "despesas": round(despesas, 2),
                "saldo": round(saldo, 2)
            })

        return evolucao

    finally:
        conexao.close()        

def obter_comparacao_mensal(ano, mes):
    # Descobre o mês anterior
    if mes == 1:
        ano_anterior = ano - 1
        mes_anterior = 12
    else:
        ano_anterior = ano
        mes_anterior = mes - 1

    # Resumo do mês atual
    receitas_atual, despesas_atual, saldo_atual = (
        calcular_resumo_mensal(
            ano,
            mes
        )
    )

    # Resumo do mês anterior
    receitas_anterior, despesas_anterior, saldo_anterior = (
        calcular_resumo_mensal(
            ano_anterior,
            mes_anterior
        )
    )

    def calcular_variacao(atual, anterior):
        if anterior == 0:
            if atual == 0:
                return 0

            return None

        return round(
            ((atual - anterior) / anterior) * 100,
            2
        )

    return {
        "ano_atual": ano,
        "mes_atual": mes,

        "ano_anterior": ano_anterior,
        "mes_anterior": mes_anterior,

        "receitas_atual": round(
            receitas_atual,
            2
        ),

        "receitas_anterior": round(
            receitas_anterior,
            2
        ),

        "despesas_atual": round(
            despesas_atual,
            2
        ),

        "despesas_anterior": round(
            despesas_anterior,
            2
        ),

        "saldo_atual": round(
            saldo_atual,
            2
        ),

        "saldo_anterior": round(
            saldo_anterior,
            2
        ),

        "variacao_receitas": calcular_variacao(
            receitas_atual,
            receitas_anterior
        ),

        "variacao_despesas": calcular_variacao(
            despesas_atual,
            despesas_anterior
        ),

        "variacao_saldo": calcular_variacao(
            saldo_atual,
            saldo_anterior
        )
    }

def obter_resumo_cartao(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        # ==============================
        # DADOS DO CARTÃO
        # ==============================

        cursor.execute("""
            SELECT
                nome,
                limite,
                dia_fechamento,
                dia_vencimento,
                ativo
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        cartao = cursor.fetchone()

        if cartao is None:
            return None

        (
            nome,
            limite,
            dia_fechamento,
            dia_vencimento,
            ativo
        ) = cartao

        # ==============================
        # LIMITE
        # ==============================

        limite_utilizado = calcular_limite_utilizado(
            cartao_id
        )

        limite_disponivel = limite - limite_utilizado

        if limite > 0:
            percentual_utilizado = (
                limite_utilizado / limite
            ) * 100
        else:
            percentual_utilizado = 0

        # ==============================
        # FATURAS ABERTAS
        # ==============================

        cursor.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(valor_total), 0)
            FROM faturas
            WHERE cartao_id = ?
            AND paga = 0
        """, (cartao_id,))

        quantidade_faturas, total_faturas = (
            cursor.fetchone()
        )

        # ==============================
        # PRÓXIMA FATURA
        # ==============================

        cursor.execute("""
            SELECT
                id,
                mes,
                ano,
                data_fechamento,
                data_vencimento,
                valor_total
            FROM faturas
            WHERE cartao_id = ?
            AND paga = 0
            ORDER BY ano, mes
            LIMIT 1
        """, (cartao_id,))

        proxima_fatura = cursor.fetchone()

        return {
            "id": cartao_id,
            "nome": nome,
            "limite": round(limite, 2),
            "limite_utilizado": round(
                limite_utilizado,
                2
            ),
            "limite_disponivel": round(
                limite_disponivel,
                2
            ),
            "percentual_utilizado": round(
                percentual_utilizado,
                2
            ),
            "dia_fechamento": dia_fechamento,
            "dia_vencimento": dia_vencimento,
            "ativo": ativo,
            "quantidade_faturas": quantidade_faturas,
            "total_faturas": round(
                total_faturas,
                2
            ),
            "proxima_fatura": proxima_fatura
        }

    finally:
        conexao.close()

def obter_gastos_cartao_por_categoria(
    cartao_id,
    ano,
    mes
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        inicio = f"{ano:04d}-{mes:02d}-01"

        if mes == 12:
            proximo_ano = ano + 1
            proximo_mes = 1
        else:
            proximo_ano = ano
            proximo_mes = mes + 1

        fim = (
            f"{proximo_ano:04d}-"
            f"{proximo_mes:02d}-01"
        )

        cursor.execute("""
            SELECT
                c.nome,
                SUM(cc.valor)
            FROM compras_cartao cc
            INNER JOIN categorias c
                ON cc.categoria_id = c.id
            WHERE cc.cartao_id = ?
            AND cc.data_compra >= ?
            AND cc.data_compra < ?
            GROUP BY c.id, c.nome
            ORDER BY SUM(cc.valor) DESC
        """, (
            cartao_id,
            inicio,
            fim
        ))

        resultados = cursor.fetchall()

        conexao.close()

        return resultados

    finally:
        try:
            conexao.close()
        except:
            pass       

def obter_compromisso_faturas_cartao(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT
                f.id,
                f.mes,
                f.ano,
                f.data_fechamento,
                f.data_vencimento,
                f.valor_total,
                f.paga,

                COUNT(DISTINCT cc.id),

                COALESCE(
                    (
                        SELECT SUM(pc.valor)
                        FROM parcelas_cartao pc
                        WHERE pc.fatura_id = f.id
                    ),
                    0
                )

            FROM faturas f

            LEFT JOIN compras_cartao cc
                ON cc.fatura_id = f.id

            WHERE f.cartao_id = ?

            GROUP BY
                f.id,
                f.mes,
                f.ano,
                f.data_fechamento,
                f.data_vencimento,
                f.valor_total,
                f.paga

            ORDER BY
                f.ano,
                f.mes
        """, (cartao_id,))

        resultados = cursor.fetchall()

        compromissos = []

        for resultado in resultados:

            (
                id_fatura,
                mes,
                ano,
                data_fechamento,
                data_vencimento,
                valor_total,
                paga,
                quantidade_compras,
                valor_parcelas
            ) = resultado

            valor_parcelas = round(
                valor_parcelas,
                2
            )

            valor_avista = round(
                valor_total - valor_parcelas,
                2
            )

            compromissos.append({
                "id": id_fatura,
                "mes": mes,
                "ano": ano,
                "data_fechamento":
                    data_fechamento,
                "data_vencimento":
                    data_vencimento,
                "valor_total":
                    round(valor_total, 2),
                "paga": paga,
                "quantidade_compras":
                    quantidade_compras,
                "valor_parcelas":
                    valor_parcelas,
                "valor_avista":
                    valor_avista
            })

        return compromissos

    finally:
        conexao.close()

def obter_projecao_faturas(cartao_id, quantidade_meses=6):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        hoje = datetime.now()

        ano_atual = hoje.year
        mes_atual = hoje.month

        cursor.execute("""
            SELECT
                id,
                mes,
                ano,
                data_vencimento,
                valor_total,
                paga
            FROM faturas
            WHERE cartao_id = ?
            AND paga = 0
            AND (
                ano > ?
                OR (ano = ? AND mes >= ?)
            )
            ORDER BY ano, mes
        """, (
            cartao_id,
            ano_atual,
            ano_atual,
            mes_atual
        ))

        faturas = cursor.fetchall()

        projecao = []

        for fatura in faturas:
            (
                id_fatura,
                mes,
                ano,
                data_vencimento,
                valor_total,
                paga
            ) = fatura

            projecao.append({
                "id": id_fatura,
                "mes": mes,
                "ano": ano,
                "data_vencimento": data_vencimento,
                "valor_total": round(valor_total, 2),
                "paga": paga
            })

            if len(projecao) >= quantidade_meses:
                break

        return projecao

    finally:
        conexao.close()     



def atualizar_cartao(
    cartao_id,
    nome,
    limite,
    dia_fechamento,
    dia_vencimento
):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        nome = nome.strip()

        if not nome:
            return False, "nome_invalido"

        if limite <= 0:
            return False, "limite_invalido"

        if not 1 <= dia_fechamento <= 31:
            return False, "fechamento_invalido"

        if not 1 <= dia_vencimento <= 31:
            return False, "vencimento_invalido"

        cursor.execute("""
            SELECT id
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        if cursor.fetchone() is None:
            return False, "cartao_inexistente"

        cursor.execute("""
            UPDATE cartoes
            SET
                nome = ?,
                limite = ?,
                dia_fechamento = ?,
                dia_vencimento = ?
            WHERE id = ?
        """, (
            nome,
            limite,
            dia_fechamento,
            dia_vencimento,
            cartao_id
        ))

        conexao.commit()

        return True, "cartao_atualizado"

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()


def alterar_status_cartao(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT ativo
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        cartao = cursor.fetchone()

        if cartao is None:
            return False, "cartao_inexistente"

        status_atual = cartao[0]
        novo_status = 0 if status_atual else 1

        cursor.execute("""
            UPDATE cartoes
            SET ativo = ?
            WHERE id = ?
        """, (novo_status, cartao_id))

        conexao.commit()

        return True, novo_status

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()



def excluir_cartao(cartao_id):
    conexao = sqlite3.connect(obter_caminho_banco())
    cursor = conexao.cursor()

    try:
        cursor.execute("""
            SELECT id
            FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        if cursor.fetchone() is None:
            return False, "cartao_inexistente"

        # Bloqueia cartões com compras vinculadas,
        # incluindo compras parceladas.
        cursor.execute("""
            SELECT 1
            FROM compras_cartao
            WHERE cartao_id = ?
            LIMIT 1
        """, (cartao_id,))

        if cursor.fetchone():
            return False, "cartao_com_compras"

        # Proteção adicional para parcelas vinculadas.
        cursor.execute("""
            SELECT 1
            FROM parcelas_cartao pc
            JOIN compras_cartao cc
                ON cc.id = pc.compra_id
            WHERE cc.cartao_id = ?
            LIMIT 1
        """, (cartao_id,))

        if cursor.fetchone():
            return False, "cartao_com_parcelas"

        # Bloqueia qualquer fatura, paga ou aberta.
        cursor.execute("""
            SELECT 1
            FROM faturas
            WHERE cartao_id = ?
            LIMIT 1
        """, (cartao_id,))

        if cursor.fetchone():
            return False, "cartao_com_faturas"

        cursor.execute("""
            DELETE FROM cartoes
            WHERE id = ?
        """, (cartao_id,))

        conexao.commit()
        return True, "cartao_excluido"

    except Exception:
        conexao.rollback()
        raise

    finally:
        conexao.close()

