from banco import (
    criar_banco,
    criar_categorias,
    migrar_categorias,
    migrar_datas,
    criar_recorrencias,
    migrar_lancamentos_recorrencia,
    listar_categorias,
    adicionar_lancamento,
    adicionar_categoria,
    atualizar_categoria,
    excluir_categoria,
    adicionar_recorrencia,
    atualizar_recorrencia,
    alterar_status_recorrencia,
    listar_ocorrencias_recorrencia,
    marcar_ocorrencia_paga,
    listar_lancamentos,
    listar_recorrencias,
    excluir_recorrencia,
    sincronizar_recorrencias,
    resumo_ocorrencias_recorrencia,
    buscar_lancamento,
    atualizar_lancamento,
    excluir_lancamento,
    calcular_resumo,
    calcular_resumo_mensal,
    despesas_por_categoria,
    despesas_por_categoria_mensal,
    criar_parcelamentos,
    adicionar_parcelamento,
    listar_parcelas_parcelamento,
    resumo_parcelas_parcelamento,
    migrar_lancamentos_parcelamento,
    marcar_parcela_paga,
    listar_parcelamentos,
    alterar_status_parcelamento,
    atualizar_parcelamento,
    excluir_parcelamento,
    criar_cartoes,
    adicionar_cartao,
    listar_cartoes,
    atualizar_cartao,
    criar_faturas,
    listar_faturas,
    pagar_fatura,
    criar_compras_cartao,
    listar_compras_cartao,
    adicionar_compra_cartao,
    alterar_status_cartao,
    excluir_cartao,
    listar_categorias,
    criar_parcelas_cartao,
    adicionar_compra_parcelada_cartao,
    calcular_limite_utilizado,
    calcular_limite_disponivel,
    obter_dashboard,
    obter_resumo_mensal_detalhado,
    obter_evolucao_anual,
    obter_comparacao_mensal,
    obter_resumo_cartao,
    obter_gastos_cartao_por_categoria,
    obter_compromisso_faturas_cartao,
    obter_projecao_faturas
)

from utils import (
    ler_data,
    ler_tipo,
    ler_valor,
    formatar_moeda,
    formatar_data
)

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

console = Console()

def exibir_menu(titulo, descricao, opcoes):
    console.print()

    console.print(
        Panel(
            f"[bold cyan]{titulo}[/bold cyan]\n"
            f"[dim]{descricao}[/dim]",
            border_style="cyan",
            expand=False,
            padding=(1, 4)
        )
    )

    tabela = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=False
    )

    tabela.add_column(
        "Opção",
        justify="center",
        style="bold yellow",
        width=7
    )

    tabela.add_column(
        "Funcionalidade",
        style="white",
        min_width=25
    )

    for numero, nome in opcoes:
        if numero == "0":
            nome = f"[red]{nome}[/red]"

        tabela.add_row(numero, nome)

    console.print(tabela)
    console.print()

# ============================================================
# INICIALIZAÇÃO
# ============================================================

criar_banco()
criar_categorias()
migrar_categorias()
migrar_datas()
criar_recorrencias()
migrar_lancamentos_recorrencia()
sincronizar_recorrencias()
criar_parcelamentos()
migrar_lancamentos_parcelamento()
criar_cartoes()
criar_faturas()
criar_compras_cartao()
criar_parcelas_cartao()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def mostrar_lancamento(lancamento):
    (
        id_lancamento,
        data,
        descricao,
        tipo,
        categoria,
        valor
    ) = lancamento

    print(
        f"{id_lancamento} | "
        f"{formatar_data(data)} | "
        f"{descricao} | "
        f"{tipo} | "
        f"{categoria} | "
        f"{formatar_moeda(valor)}"
    )

def mostrar_lancamentos():
    print()
    print("========================================")
    print("           LISTA DE LANÇAMENTOS")
    print("========================================")
    print()

    lancamentos = listar_lancamentos()

    if not lancamentos:
        print("Nenhum lançamento encontrado.")
        return

    print(
        "ID | DATA       | DESCRIÇÃO"
        "                 | TIPO     | CATEGORIA"
        "        | VALOR"
    )
    print("-" * 100)

    for lancamento in lancamentos:
        mostrar_lancamento(lancamento)

    print("-" * 100)

def mostrar_detalhes_lancamento(lancamento):
    (
        id_lancamento,
        data,
        descricao,
        tipo,
        categoria,
        valor,
        categoria_id
    ) = lancamento

    print()
    print("LANÇAMENTO")
    print("----------------------------------------")

    print(
        f"Data:       "
        f"{formatar_data(data)}"
    )

    print(
        f"Descrição:  "
        f"{descricao}"
    )

    print(
        f"Tipo:       "
        f"{tipo}"
    )

    print(
        f"Categoria:  "
        f"{categoria}"
    )

    print(
        f"Valor:      "
        f"{formatar_moeda(valor)}"
    )


# ============================================================
# LANÇAMENTOS
# ============================================================

def adicionar_novo_lancamento():
    print()
    print("========================================")
    print("          NOVO LANÇAMENTO")
    print("========================================")

    data = ler_data()

    descricao = input(
        "Descrição: "
    ).strip()

    while not descricao:
        print("A descrição não pode ficar vazia.")

        descricao = input(
            "Descrição: "
        ).strip()

    tipo = ler_tipo()

    print()
    print("CATEGORIAS")

    categorias = listar_categorias(tipo)

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        categoria_id, nome = categoria

        print(
            f"{numero} - {nome}"
        )

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma categoria: "
                )
            )

            if 1 <= escolha <= len(categorias):
                categoria_id = categorias[
                    escolha - 1
                ][0]

                break

            print("Categoria inválida.")

        except ValueError:
            print(
                "Digite o número da categoria."
            )

    valor = ler_valor()

    adicionar_lancamento(
        data,
        descricao,
        tipo,
        categoria_id,
        valor
    )

    print()
    print(
        "Lançamento adicionado com sucesso!"
    )


def listar_todos_lancamentos():
    print()
    print("========================================")
    print("          MEUS LANÇAMENTOS")
    print("========================================")

    lancamentos = listar_lancamentos()

    if not lancamentos:
        print("Nenhum lançamento cadastrado.")

    else:
        for lancamento in lancamentos:
            mostrar_lancamento(lancamento)


def filtrar_por_periodo():
    while True:
        try:
            ano = int(
                input("Ano: ")
            )

            mes = int(
                input("Mês (1-12): ")
            )

            if 1 <= mes <= 12:
                break

            print(
                "O mês deve estar entre 1 e 12."
            )

        except ValueError:
            print(
                "Digite números válidos."
            )

    inicio = (
        f"{ano:04d}-{mes:02d}-01"
    )

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

    lancamentos = listar_lancamentos(
        data_inicio=inicio,
        data_fim=fim
    )

    print()
    print("========================================")
    print(
        f"       LANÇAMENTOS — {mes:02d}/{ano}"
    )
    print("========================================")

    if not lancamentos:
        print("Nenhum lançamento encontrado.")

    else:
        for lancamento in lancamentos:
            mostrar_lancamento(lancamento)


def filtrar_por_tipo():
    print()
    print("TIPO DE LANÇAMENTO")
    print("1 - Receitas")
    print("2 - Despesas")

    tipo_opcao = input(
        "Escolha uma opção: "
    )

    if tipo_opcao == "1":
        tipo = "receita"

    elif tipo_opcao == "2":
        tipo = "despesa"

    else:
        print("Opção inválida.")
        return

    lancamentos = listar_lancamentos(
        tipo=tipo
    )

    print()
    print("========================================")

    if tipo == "receita":
        print("             RECEITAS")

    else:
        print("             DESPESAS")

    print("========================================")

    if not lancamentos:
        print("Nenhum lançamento encontrado.")

    else:
        for lancamento in lancamentos:
            (
                id_lancamento,
                data,
                descricao,
                tipo_lancamento,
                categoria,
                valor
            ) = lancamento

            print(
                f"{formatar_data(data)} | "
                f"{descricao} | "
                f"{categoria} | "
                f"{formatar_moeda(valor)}"
            )


def filtrar_por_categoria():
    print()
    print("CATEGORIAS")

    categorias = listar_categorias()

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        categoria_id, nome, tipo = categoria

        print(
            f"{numero} - "
            f"{nome} ({tipo})"
        )

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma categoria: "
                )
            )

            if 1 <= escolha <= len(categorias):
                categoria_id = categorias[
                    escolha - 1
                ][0]

                nome_categoria = categorias[
                    escolha - 1
                ][1]

                break

            print("Categoria inválida.")

        except ValueError:
            print(
                "Digite um número válido."
            )

    lancamentos = listar_lancamentos(
        categoria_id=categoria_id
    )

    print()
    print("========================================")
    print(
        f"      CATEGORIA: {nome_categoria}"
    )
    print("========================================")

    if not lancamentos:
        print("Nenhum lançamento encontrado.")

    else:
        for lancamento in lancamentos:
            mostrar_lancamento(lancamento)


def filtrar_combinado():
    print()
    print("========================================")
    print("         FILTRO COMBINADO")
    print("========================================")

    # --------------------------------------------------------
    # PERÍODO
    # --------------------------------------------------------

    print()
    print("PERÍODO")
    print("1 - Todos os períodos")
    print("2 - Um mês específico")

    periodo = input(
        "Escolha uma opção: "
    )

    data_inicio = None
    data_fim = None

    if periodo == "2":
        while True:
            try:
                ano = int(
                    input("Ano: ")
                )

                mes = int(
                    input("Mês (1-12): ")
                )

                if 1 <= mes <= 12:
                    break

                print(
                    "O mês deve estar entre 1 e 12."
                )

            except ValueError:
                print(
                    "Digite números válidos."
                )

        data_inicio = (
            f"{ano:04d}-{mes:02d}-01"
        )

        if mes == 12:
            proximo_ano = ano + 1
            proximo_mes = 1

        else:
            proximo_ano = ano
            proximo_mes = mes + 1

        data_fim = (
            f"{proximo_ano:04d}-"
            f"{proximo_mes:02d}-01"
        )

    elif periodo != "1":
        print("Opção inválida.")
        return

    # --------------------------------------------------------
    # TIPO
    # --------------------------------------------------------

    print()
    print("TIPO")
    print("1 - Todos")
    print("2 - Receita")
    print("3 - Despesa")

    tipo_opcao = input(
        "Escolha uma opção: "
    )

    tipo = None

    if tipo_opcao == "2":
        tipo = "receita"

    elif tipo_opcao == "3":
        tipo = "despesa"

    elif tipo_opcao != "1":
        print("Opção inválida.")
        return

    # --------------------------------------------------------
    # CATEGORIA
    # --------------------------------------------------------

    print()
    print("CATEGORIA")
    print("1 - Todas")
    print("2 - Escolher categoria")

    categoria_opcao = input(
        "Escolha uma opção: "
    )

    categoria_id = None

    if categoria_opcao == "2":
        print()

        categorias = listar_categorias()

        for numero, categoria in enumerate(
            categorias,
            start=1
        ):
            id_categoria, nome, tipo_categoria = categoria

            print(
                f"{numero} - "
                f"{nome} ({tipo_categoria})"
            )

        while True:
            try:
                escolha = int(
                    input(
                        "Escolha uma categoria: "
                    )
                )

                if 1 <= escolha <= len(categorias):
                    categoria_id = categorias[
                        escolha - 1
                    ][0]

                    break

                print("Categoria inválida.")

            except ValueError:
                print(
                    "Digite um número válido."
                )

    elif categoria_opcao != "1":
        print("Opção inválida.")
        return

    # --------------------------------------------------------
    # CONSULTA
    # --------------------------------------------------------

    lancamentos = listar_lancamentos(
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo=tipo,
        categoria_id=categoria_id
    )

    print()
    print("========================================")
    print("          RESULTADO DO FILTRO")
    print("========================================")

    if not lancamentos:
        print("Nenhum lançamento encontrado.")

    else:
        for lancamento in lancamentos:
            mostrar_lancamento(lancamento)


def menu_filtros():
    while True:
        print()
        print("========================================")
        print("       FILTRAR LANÇAMENTOS")
        print("========================================")

        print()
        print("1 - Filtrar por período")
        print("2 - Filtrar por tipo")
        print("3 - Filtrar por categoria")
        print("4 - Combinar filtros")
        print("0 - Voltar")

        opcao = input(
            "Escolha uma opção: "
        )

        if opcao == "1":
            filtrar_por_periodo()

        elif opcao == "2":
            filtrar_por_tipo()

        elif opcao == "3":
            filtrar_por_categoria()

        elif opcao == "4":
            filtrar_combinado()

        elif opcao == "0":
            break

        else:
            print("Opção inválida.")


def editar_lancamento():
    print()
    print("========================================")
    print("          EDITAR LANÇAMENTO")
    print("========================================")

    while True:
        try:
            id_lancamento = int(
                input("ID do lançamento: ")
            )

            break

        except ValueError:
            print("Digite um ID válido.")

    lancamento = buscar_lancamento(
        id_lancamento
    )

    if lancamento is None:
        print()
        print("Lançamento não encontrado.")
        return

    (
        id_atual,
        data_atual,
        descricao_atual,
        tipo_atual,
        categoria_atual,
        valor_atual,
        categoria_id_atual
    ) = lancamento

    mostrar_detalhes_lancamento(
        lancamento
    )

    print()
    print("O que deseja alterar?")
    print("1 - Data")
    print("2 - Descrição")
    print("3 - Tipo")
    print("4 - Categoria")
    print("5 - Valor")
    print("0 - Cancelar")

    campo = input(
        "Escolha uma opção: "
    )

    nova_data = data_atual
    nova_descricao = descricao_atual
    novo_tipo = tipo_atual
    nova_categoria_id = categoria_id_atual
    novo_valor = valor_atual

    if campo == "1":
        print()
        print(
            "Data atual:",
            formatar_data(data_atual)
        )

        nova_data = ler_data()

    elif campo == "2":
        print()
        print(
            f"Descrição atual: "
            f"{descricao_atual}"
        )

        nova_descricao = input(
            "Nova descrição: "
        ).strip()

        while not nova_descricao:
            print(
                "A descrição não pode ficar vazia."
            )

            nova_descricao = input(
                "Nova descrição: "
            ).strip()

    elif campo == "3":
        print()
        print(
            f"Tipo atual: {tipo_atual}"
        )

        novo_tipo = ler_tipo()

        print()
        print("CATEGORIAS")

        categorias = listar_categorias(
            novo_tipo
        )

        for numero, categoria in enumerate(
            categorias,
            start=1
        ):
            categoria_id, nome = categoria

            print(
                f"{numero} - {nome}"
            )

        while True:
            try:
                escolha = int(
                    input(
                        "Escolha uma categoria: "
                    )
                )

                if 1 <= escolha <= len(categorias):
                    nova_categoria_id = categorias[
                        escolha - 1
                    ][0]

                    break

                print("Categoria inválida.")

            except ValueError:
                print(
                    "Digite um número válido."
                )

    elif campo == "4":
        print()
        print("CATEGORIAS")

        categorias = listar_categorias(
            novo_tipo
        )

        for numero, categoria in enumerate(
            categorias,
            start=1
        ):
            categoria_id, nome = categoria

            print(
                f"{numero} - {nome}"
            )

        while True:
            try:
                escolha = int(
                    input(
                        "Escolha uma categoria: "
                    )
                )

                if 1 <= escolha <= len(categorias):
                    nova_categoria_id = categorias[
                        escolha - 1
                    ][0]

                    break

                print("Categoria inválida.")

            except ValueError:
                print(
                    "Digite um número válido."
                )

    elif campo == "5":
        print()
        print(
            f"Valor atual: "
            f"{formatar_moeda(valor_atual)}"
        )

        novo_valor = ler_valor()

    elif campo == "0":
        print()
        print("Edição cancelada.")
        return

    else:
        print()
        print("Opção inválida.")
        return

    sucesso = atualizar_lancamento(
        id_lancamento,
        nova_data,
        nova_descricao,
        novo_tipo,
        nova_categoria_id,
        novo_valor
    )

    print()

    if sucesso:
        print(
            "Lançamento atualizado "
            "com sucesso!"
        )

    else:
        print(
            "Não foi possível atualizar "
            "o lançamento."
        )


def excluir_lancamento_menu():
    print()
    print("========================================")
    print("          EXCLUIR LANÇAMENTO")
    print("========================================")

    while True:
        try:
            id_lancamento = int(
                input("ID do lançamento: ")
            )
            break

        except ValueError:
            print("Digite um ID válido.")

    lancamento = buscar_lancamento(
        id_lancamento
    )

    if lancamento is None:
        print()
        print("Lançamento não encontrado.")
        return

    (
        id_lancamento,
        data,
        descricao,
        tipo,
        categoria,
        valor
    ) = lancamento

    print()
    print("LANÇAMENTO SELECIONADO")
    print("----------------------------------------")

    print(
        f"Data:       {formatar_data(data)}"
    )

    print(
        f"Descrição:  {descricao}"
    )

    print(
        f"Tipo:       {tipo}"
    )

    print(
        f"Categoria:  {categoria}"
    )

    print(
        f"Valor:      {formatar_moeda(valor)}"
    )

    print()
    print("Tem certeza que deseja excluir?")
    print("1 - Sim")
    print("2 - Não")

    confirmacao = input(
        "Escolha uma opção: "
    )

    if confirmacao == "2":
        print()
        print("Exclusão cancelada.")
        return

    if confirmacao != "1":
        print()
        print("Opção inválida.")
        return

    sucesso = excluir_lancamento(
        id_lancamento
    )

    print()

    if sucesso:
        print(
            "Lançamento excluído "
            "com sucesso!"
        )

    else:
        print(
            "Não foi possível excluir "
            "o lançamento."
        )


# ============================================================
# MENU DE LANÇAMENTOS
# ============================================================

def mostrar_recorrencias():
    print()
    print("========================================")
    print("           RECORRÊNCIAS")
    print("========================================")

    recorrencias = listar_recorrencias()

    if not recorrencias:
        print()
        print("Nenhuma recorrência cadastrada.")
        return

    print()

    print(
        f"{'ID':<4}"
        f"{'DESCRIÇÃO':<18}"
        f"{'TIPO':<10}"
        f"{'CATEGORIA':<15}"
        f"{'VALOR':<15}"
        f"{'FREQ.':<10}"
        f"STATUS"
    )

    print("-" * 90)

    for recorrencia in recorrencias:
        (
            id_recorrencia,
            descricao,
            tipo,
            categoria,
            valor,
            frequencia,
            data_inicio,
            data_fim,
            ativa
        ) = recorrencia

        if ativa:
            status = "🟢 ATIVA"
        else:
            status = "⏸️ PAUSADA"

        print(
            f"{id_recorrencia:<4}"
            f"{descricao[:16]:<18}"
            f"{tipo:<10}"
            f"{categoria[:13]:<15}"
            f"{formatar_moeda(valor):<15}"
            f"{frequencia:<10}"
            f"{status}"
        )

    print("-" * 90)

    print()
    print("Legenda:")
    print("🟢 ATIVA")
    print("⏸️ PAUSADA")

def mostrar_ocorrencias_recorrencia():
    print()
    print("========================================")
    print("       OCORRÊNCIAS DA RECORRÊNCIA")
    print("========================================")

    recorrencias = listar_recorrencias()

    if not recorrencias:
        print()
        print("Nenhuma recorrência cadastrada.")
        return

    print()

    for recorrencia in recorrencias:
        id_recorrencia = recorrencia[0]
        descricao = recorrencia[1]

        print(
            f"{id_recorrencia} - {descricao}"
        )

    print()

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma recorrência: "
                )
            )

            ids_validos = [
                recorrencia[0]
                for recorrencia in recorrencias
            ]

            if escolha in ids_validos:
                id_recorrencia = escolha
                break

            print("Recorrência inválida.")

        except ValueError:
            print("Digite um número válido.")

    recorrencia_selecionada = next(
        recorrencia
        for recorrencia in recorrencias
        if recorrencia[0] == id_recorrencia
    )

    descricao = recorrencia_selecionada[1]

    ocorrencias = listar_ocorrencias_recorrencia(
        id_recorrencia
    )

    print()
    print("========================================")
    print(
        f"       OCORRÊNCIAS - {descricao}"
    )
    print("========================================")

    if not ocorrencias:
        print()
        print("Nenhuma ocorrência encontrada.")
        return

    print()

    print(
        f"{'ID':<6}"
        f"{'VENCIMENTO':<15}"
        f"{'VALOR':<17}"
        f"STATUS"
    )

    print("-" * 60)

    for ocorrencia in ocorrencias:
        (
            id_ocorrencia,
            data_vencimento,
            valor,
            pago,
            data_pagamento,
            lancamento_id
        ) = ocorrencia

        if pago:
            status = "🟢 PAGO"
        else:
            status = "🔴 NÃO PAGO"

        print(
            f"{id_ocorrencia:<6}"
            f"{formatar_data(data_vencimento):<15}"
            f"{formatar_moeda(valor):<17}"
            f"{status}"
        )

    print("-" * 60)

    resumo = resumo_ocorrencias_recorrencia(
        id_recorrencia
    )

    (
        total_ocorrencias,
        ocorrencias_pagas,
        ocorrencias_pendentes,
        valor_pago,
        valor_pendente
    ) = resumo

    print()
    print("RESUMO DA RECORRÊNCIA")
    print("----------------------------------------")

    print(
        f"Total de ocorrências: "
        f"{total_ocorrencias}"
    )

    print(
        f"🟢 Pagas: "
        f"{ocorrencias_pagas}"
    )

    print(
        f"🔴 Pendentes: "
        f"{ocorrencias_pendentes}"
    )

    print(
        f"💰 Total pago: "
        f"{formatar_moeda(valor_pago)}"
    )

    print(
        f"⏳ Em aberto: "
        f"{formatar_moeda(valor_pendente)}"
    )

    print("----------------------------------------")

    print()
    print("1 - Marcar ocorrência como paga")
    print("0 - Voltar")

    opcao = input(
        "Escolha uma opção: "
    )

    if opcao == "1":

        ocorrencias_pendentes = [
            ocorrencia
            for ocorrencia in ocorrencias
            if ocorrencia[3] == 0
        ]

        if not ocorrencias_pendentes:
            print()
            print(
                "Não existem ocorrências "
                "pendentes."
            )
            return

        print()
        print("========================================")
        print("        OCORRÊNCIAS NÃO PAGAS")
        print("========================================")

        print()

        print(
            f"{'ID':<6}"
            f"{'VENCIMENTO':<15}"
            f"{'VALOR':<17}"
        )

        print("-" * 45)

        for ocorrencia in ocorrencias_pendentes:
            (
                id_ocorrencia,
                data_vencimento,
                valor,
                pago,
                data_pagamento,
                lancamento_id
            ) = ocorrencia

            print(
                f"{id_ocorrencia:<6}"
                f"{formatar_data(data_vencimento):<15}"
                f"{formatar_moeda(valor):<17}"
            )

        print("-" * 45)

        print()

        while True:
            try:
                id_ocorrencia = int(
                    input(
                        "Escolha a ocorrência: "
                    )
                )

                ids_pendentes = [
                    ocorrencia[0]
                    for ocorrencia
                    in ocorrencias_pendentes
                ]

                if id_ocorrencia in ids_pendentes:
                    break

                print(
                    "Ocorrência inválida."
                )

            except ValueError:
                print(
                    "Digite um número válido."
                )

        print()
        print("DATA DO PAGAMENTO")

        data_pagamento = ler_data()

        sucesso = marcar_ocorrencia_paga(
            id_ocorrencia,
            data_pagamento
        )

        print()

        if sucesso:
            print(
                "Ocorrência marcada como paga!"
            )

            print(
                "O lançamento financeiro "
                "foi criado com sucesso."
            )

        else:
            print(
                "Não foi possível marcar "
                "a ocorrência como paga."
            )

def editar_recorrencia_menu():
    print()
    print("========================================")
    print("         EDITAR RECORRÊNCIA")
    print("========================================")

    recorrencias = listar_recorrencias()

    if not recorrencias:
        print()
        print("Nenhuma recorrência cadastrada.")
        return

    print()

    for recorrencia in recorrencias:
        (
            id_recorrencia,
            descricao,
            tipo,
            categoria,
            valor,
            frequencia,
            data_inicio,
            data_fim,
            ativa
        ) = recorrencia

        status = "ATIVA" if ativa else "PAUSADA"

        print(
            f"{id_recorrencia} - "
            f"{descricao} - "
            f"{categoria} - "
            f"{formatar_moeda(valor)} - "
            f"{status}"
        )

    print()

    while True:
        try:
            id_recorrencia = int(
                input(
                    "Escolha uma recorrência: "
                )
            )

            ids_validos = [
                recorrencia[0]
                for recorrencia in recorrencias
            ]

            if id_recorrencia in ids_validos:
                break

            print("Recorrência inválida.")

        except ValueError:
            print("Digite um número válido.")

    recorrencia_selecionada = next(
        recorrencia
        for recorrencia in recorrencias
        if recorrencia[0] == id_recorrencia
    )

    (
        _,
        descricao_atual,
        tipo_atual,
        categoria_atual,
        valor_atual,
        frequencia_atual,
        data_inicio_atual,
        data_fim_atual,
        ativa_atual
    ) = recorrencia_selecionada

    print()
    print("Pressione ENTER para manter o valor atual.")

    print()
    print(f"Descrição atual: {descricao_atual}")

    nova_descricao = input(
        "Nova descrição: "
    ).strip()

    if not nova_descricao:
        nova_descricao = descricao_atual

    print()
    print(f"Tipo atual: {tipo_atual}")

    nova_tipo = input(
        "Novo tipo (receita/despesa): "
    ).strip().lower()

    if not nova_tipo:
        nova_tipo = tipo_atual

    while nova_tipo not in ["receita", "despesa"]:
        print(
            "Tipo inválido. "
            "Digite receita ou despesa."
        )

        nova_tipo = input(
            "Novo tipo (receita/despesa): "
        ).strip().lower()

    print()
    print(
        f"Valor atual: "
        f"{formatar_moeda(valor_atual)}"
    )

    entrada_valor = input(
        "Novo valor: "
    ).strip()

    if entrada_valor:
        try:
            if "," in entrada_valor:
                entrada_valor = (
                    entrada_valor
                    .replace(".", "")
                    .replace(",", ".")
                )

            novo_valor = float(
                entrada_valor
            )

            if novo_valor <= 0:
                print(
                    "O valor deve ser maior que zero."
                )
                return

        except ValueError:
            print("Valor inválido.")
            return

    else:
        novo_valor = valor_atual

    print()
    print(
        f"Categoria atual: {categoria_atual}"
    )

    print()
    print("Categorias disponíveis:")

    categorias = listar_categorias(nova_tipo)

    for categoria in categorias:
        print(
            f"{categoria[0]} - {categoria[1]}"
        )

    while True:
        entrada_categoria = input(
            "Nova categoria "
            "(ENTER para manter): "
        ).strip()

        if not entrada_categoria:
            categoria_id = next(
                categoria[0]
                for categoria in categorias
                if categoria[1] == categoria_atual
            )
            break

        try:
            categoria_id = int(
                entrada_categoria
            )
        except ValueError:
            print("Digite um número válido.")
            continue

        ids_categorias = [
            categoria[0]
            for categoria in categorias
        ]

        if categoria_id not in ids_categorias:
            print("Categoria inválida.")
            continue

        break

    print()
    print(
        f"Frequência atual: {frequencia_atual}"
    )

    print()
    print("Frequências:")
    print("1 - Semanal")
    print("2 - Mensal")
    print("3 - Anual")

    entrada_frequencia = input(
        "Nova frequência "
        "(ENTER para manter): "
    ).strip()

    if not entrada_frequencia:
        nova_frequencia = frequencia_atual

    elif entrada_frequencia == "1":
        nova_frequencia = "semanal"

    elif entrada_frequencia == "2":
        nova_frequencia = "mensal"

    elif entrada_frequencia == "3":
        nova_frequencia = "anual"

    else:
        print("Frequência inválida.")
        return

    print()

    if data_fim_atual:
        print(
            f"Data final atual: "
            f"{formatar_data(data_fim_atual)}"
        )
    else:
        print("Data final atual: Sem data final")

    entrada_data_fim = input(
        "Nova data final "
        "(ENTER para manter): "
    ).strip()

    if entrada_data_fim:
        try:
            if (
                len(entrada_data_fim) != 8
                or not entrada_data_fim.isdigit()
            ):
                print(
                    "Data inválida. "
                    "Use DDMMAAAA."
                )
                return

            data_fim = (
                f"{entrada_data_fim[:2]}-"
                f"{entrada_data_fim[2:4]}-"
                f"{entrada_data_fim[4:]}"
            )

            datetime.strptime(
                data_fim,
                "%d-%m-%Y"
            )

            data_fim = (
                f"{data_fim[6:10]}-"
                f"{data_fim[3:5]}-"
                f"{data_fim[:2]}"
            )

        except ValueError:
            print("Data final inválida.")
            return

    else:
        data_fim = data_fim_atual

    sucesso = atualizar_recorrencia(
        id_recorrencia,
        nova_descricao,
        nova_tipo,
        categoria_id,
        novo_valor,
        nova_frequencia,
        data_fim
    )

    print()

    if sucesso:
        print(
            "Recorrência atualizada "
            "com sucesso!"
        )
    else:
        print(
            "Não foi possível atualizar "
            "a recorrência."
        )

def alterar_status_recorrencia_menu():
    print()
    print("========================================")
    print("       PAUSAR / REATIVAR RECORRÊNCIA")
    print("========================================")

    recorrencias = listar_recorrencias()

    if not recorrencias:
        print()
        print("Nenhuma recorrência cadastrada.")
        return

    print()

    for recorrencia in recorrencias:
        (
            id_recorrencia,
            descricao,
            tipo,
            categoria,
            valor,
            frequencia,
            data_inicio,
            data_fim,
            ativa
        ) = recorrencia

        if ativa:
            status = "🟢 ATIVA"
        else:
            status = "⏸️ PAUSADA"

        print(
            f"{id_recorrencia} - "
            f"{descricao} - "
            f"{status}"
        )

    print()

    while True:
        try:
            id_recorrencia = int(
                input(
                    "Escolha uma recorrência: "
                )
            )

            ids_validos = [
                recorrencia[0]
                for recorrencia in recorrencias
            ]

            if id_recorrencia in ids_validos:
                break

            print("Recorrência inválida.")

        except ValueError:
            print("Digite um número válido.")

    recorrencia_selecionada = next(
        recorrencia
        for recorrencia in recorrencias
        if recorrencia[0] == id_recorrencia
    )

    ativa_atual = recorrencia_selecionada[8]
    descricao = recorrencia_selecionada[1]

    print()

    if ativa_atual:
        print(
            f"A recorrência '{descricao}' "
            "está ATIVA."
        )

        print()
        print("1 - Pausar recorrência")
        print("0 - Cancelar")

        opcao = input(
            "Escolha uma opção: "
        )

        if opcao == "1":
            sucesso = alterar_status_recorrencia(
                id_recorrencia,
                False
            )

            print()

            if sucesso:
                print(
                    "Recorrência pausada "
                    "com sucesso!"
                )
            else:
                print(
                    "Não foi possível "
                    "pausar a recorrência."
                )

    else:
        print(
            f"A recorrência '{descricao}' "
            "está PAUSADA."
        )

        print()
        print("1 - Reativar recorrência")
        print("0 - Cancelar")

        opcao = input(
            "Escolha uma opção: "
        )

        if opcao == "1":
            sucesso = alterar_status_recorrencia(
                id_recorrencia,
                True
            )

            print()

            if sucesso:
                print(
                    "Recorrência reativada "
                    "com sucesso!"
                )
            else:
                print(
                    "Não foi possível "
                    "reativar a recorrência."
                )

def excluir_recorrencia_menu():
    print()
    print("========================================")
    print("          EXCLUIR RECORRÊNCIA")
    print("========================================")

    recorrencias = listar_recorrencias()

    if not recorrencias:
        print()
        print("Nenhuma recorrência cadastrada.")
        return

    print()

    for recorrencia in recorrencias:
        (
            id_recorrencia,
            descricao,
            tipo,
            categoria,
            valor,
            frequencia,
            data_inicio,
            data_fim,
            ativa
        ) = recorrencia

        if ativa:
            status = "🟢 ATIVA"
        else:
            status = "⏸️ PAUSADA"

        print(
            f"{id_recorrencia} - "
            f"{descricao} - "
            f"{formatar_moeda(valor)} - "
            f"{status}"
        )

    print()

    while True:
        try:
            id_recorrencia = int(
                input(
                    "Escolha uma recorrência: "
                )
            )

            ids_validos = [
                recorrencia[0]
                for recorrencia in recorrencias
            ]

            if id_recorrencia in ids_validos:
                break

            print("Recorrência inválida.")

        except ValueError:
            print("Digite um número válido.")

    recorrencia_selecionada = next(
        recorrencia
        for recorrencia in recorrencias
        if recorrencia[0] == id_recorrencia
    )

    descricao = recorrencia_selecionada[1]

    print()
    print(
        f'Tem certeza que deseja excluir '
        f'"{descricao}"?'
    )

    print()
    print("⚠️ ATENÇÃO:")
    print(
        "A recorrência e suas ocorrências "
        "serão excluídas."
    )
    print(
        "Lançamentos financeiros já criados "
        "serão preservados."
    )

    print()
    print("1 - Sim, excluir")
    print("0 - Cancelar")

    opcao = input(
        "Escolha uma opção: "
    )

    if opcao != "1":
        print()
        print("Exclusão cancelada.")
        return

    sucesso = excluir_recorrencia(
        id_recorrencia
    )

    print()

    if sucesso:
        print(
            "Recorrência excluída "
            "com sucesso!"
        )
    else:
        print(
            "Não foi possível excluir "
            "a recorrência."
        )

def menu_recorrencias():
    while True:
        exibir_menu(
            "RECORRÊNCIAS",
            "Gerencie seus pagamentos e recebimentos recorrentes",
            [
                ("1", "Nova recorrência"),
                ("2", "Listar recorrências"),
                ("3", "Ver ocorrências"),
                ("4", "Editar recorrência"),
                ("5", "Pausar / Reativar recorrência"),
                ("6", "Excluir recorrência"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            nova_recorrencia()

        elif opcao == "2":
            mostrar_recorrencias()

        elif opcao == "3":
            mostrar_ocorrencias_recorrencia()

        elif opcao == "4":
            editar_recorrencia_menu()

        elif opcao == "5":
            alterar_status_recorrencia_menu()

        elif opcao == "6":
            excluir_recorrencia_menu()

        elif opcao == "0":
            return

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )

def mostrar_parcelas_parcelamento():
    print()
    print("========================================")
    print("          VER PARCELAS")
    print("========================================")

    parcelamentos = listar_parcelamentos()

    if not parcelamentos:
        print()
        print("Nenhum parcelamento cadastrado.")
        return

    print()

    for parcelamento in parcelamentos:
        id_parcelamento = parcelamento[0]
        descricao = parcelamento[1]

        print(
            f"{id_parcelamento} - {descricao}"
        )

    print()

    while True:
        try:
            escolha = int(
                input(
                    "Escolha um parcelamento: "
                )
            )

            ids_validos = [
                parcelamento[0]
                for parcelamento in parcelamentos
            ]

            if escolha in ids_validos:
                id_parcelamento = escolha
                break

            print("Parcelamento inválido.")

        except ValueError:
            print("Digite um número válido.")

    parcelamento_selecionado = next(
        parcelamento
        for parcelamento in parcelamentos
        if parcelamento[0] == id_parcelamento
    )

    descricao = parcelamento_selecionado[1]

    parcelas = listar_parcelas_parcelamento(
        id_parcelamento
    )

    print()
    print("========================================")
    print(
        f"       PARCELAS - {descricao}"
    )
    print("========================================")

    if not parcelas:
        print()
        print("Nenhuma parcela encontrada.")
        return

    print()

    print(
        f"{'PARCELA':<10}"
        f"{'VENCIMENTO':<15}"
        f"{'VALOR':<17}"
        f"STATUS"
    )

    print("-" * 60)

    for parcela in parcelas:
        (
            id_parcela,
            numero_parcela,
            data_vencimento,
            valor,
            pago,
            data_pagamento,
            lancamento_id
        ) = parcela

        numero_total = (
            f"{numero_parcela:02d}/"
            f"{len(parcelas):02d}"
        )

        if pago:
            status = "🟢 PAGO"
        else:
            status = "🔴 NÃO PAGO"

        print(
            f"{numero_total:<10}"
            f"{formatar_data(data_vencimento):<15}"
            f"{formatar_moeda(valor):<17}"
            f"{status}"
        )

    print("-" * 60)

    resumo = resumo_parcelas_parcelamento(
        id_parcelamento
    )

    (
        total_parcelas,
        parcelas_pagas,
        parcelas_pendentes,
        valor_pago,
        valor_pendente
    ) = resumo

    print()
    print("RESUMO DO PARCELAMENTO")
    print("----------------------------------------")

    print(
        f"Total de parcelas: "
        f"{total_parcelas}"
    )

    print(
        f"🟢 Pagas: "
        f"{parcelas_pagas}"
    )

    print(
        f"🔴 Pendentes: "
        f"{parcelas_pendentes}"
    )

    print(
        f"💰 Total pago: "
        f"{formatar_moeda(valor_pago)}"
    )

    print(
        f"⏳ Em aberto: "
        f"{formatar_moeda(valor_pendente)}"
    )

    print("----------------------------------------")

    print()
    print("1 - Marcar parcela como paga")
    print("0 - Voltar")

    opcao = input(
        "Escolha uma opção: "
    )

    if opcao == "1":

        parcelas_pendentes = [
            parcela
            for parcela in parcelas
            if parcela[4] == 0
        ]

        if not parcelas_pendentes:
            print()
            print(
                "Não existem parcelas "
                "pendentes."
            )
            return

        print()
        print("========================================")
        print("          PARCELAS NÃO PAGAS")
        print("========================================")

        print()

        print(
            f"{'PARCELA':<10}"
            f"{'VENCIMENTO':<15}"
            f"{'VALOR':<17}"
        )

        print("-" * 45)

        for parcela in parcelas_pendentes:
            (
                id_parcela,
                numero_parcela,
                data_vencimento,
                valor,
                pago,
                data_pagamento,
                lancamento_id
            ) = parcela

            numero_total = (
                f"{numero_parcela:02d}/"
                f"{len(parcelas):02d}"
            )

            print(
                f"{numero_total:<10}"
                f"{formatar_data(data_vencimento):<15}"
                f"{formatar_moeda(valor):<17}"
            )

        print("-" * 45)

        print()

        while True:
            try:
                id_parcela = int(
                    input(
                        "Digite o ID da parcela: "
                    )
                )

                ids_pendentes = [
                    parcela[0]
                    for parcela in parcelas_pendentes
                ]

                if id_parcela in ids_pendentes:
                    break

                print("Parcela inválida.")

            except ValueError:
                print(
                    "Digite um número válido."
                )

        print()
        print("DATA DO PAGAMENTO")

        data_pagamento = ler_data()

        sucesso = marcar_parcela_paga(
            id_parcela,
            data_pagamento
        )

        print()

        if sucesso:
            print(
                "Parcela marcada como paga!"
            )

            print(
                "O lançamento financeiro "
                "foi criado com sucesso."
            )

        else:
            print(
                "Não foi possível marcar "
                "a parcela como paga."
            )

def editar_parcelamento_menu():
    print()
    print("========================================")
    print("        EDITAR PARCELAMENTO")
    print("========================================")

    parcelamentos = listar_parcelamentos()

    if not parcelamentos:
        print()
        print("Nenhum parcelamento cadastrado.")
        return

    print()

    for parcelamento in parcelamentos:
        (
            id_parcelamento,
            descricao,
            tipo,
            categoria,
            valor_total,
            quantidade_parcelas,
            data_inicio,
            ativa
        ) = parcelamento

        print(
            f"{id_parcelamento} - "
            f"{descricao} - "
            f"{formatar_moeda(valor_total)}"
        )

    print()

    while True:
        try:
            id_parcelamento = int(
                input(
                    "Escolha um parcelamento: "
                )
            )

            ids_validos = [
                parcelamento[0]
                for parcelamento in parcelamentos
            ]

            if id_parcelamento in ids_validos:
                break

            print("Parcelamento inválido.")

        except ValueError:
            print("Digite um número válido.")

    parcelamento_selecionado = next(
        parcelamento
        for parcelamento in parcelamentos
        if parcelamento[0] == id_parcelamento
    )

    (
        id_parcelamento,
        descricao_atual,
        tipo,
        categoria_atual,
        valor_total,
        quantidade_parcelas,
        data_inicio,
        ativa
    ) = parcelamento_selecionado

    print()
    print(
        f"Descrição atual: "
        f"{descricao_atual}"
    )

    nova_descricao = input(
        "Nova descrição "
        "(ENTER para manter): "
    ).strip()

    if not nova_descricao:
        nova_descricao = descricao_atual

    print()
    print(
        f"Categoria atual: "
        f"{categoria_atual}"
    )

    categorias = listar_categorias(tipo)

    print()

    for categoria in categorias:
        print(
            f"{categoria[0]} - {categoria[1]}"
        )

    print()

    while True:
        entrada = input(
            "Nova categoria "
            "(ENTER para manter): "
        ).strip()

        if not entrada:
            categoria_id = next(
                categoria[0]
                for categoria in categorias
                if categoria[1] == categoria_atual
            )
            break

        try:
            categoria_id = int(entrada)

            ids_validos = [
                categoria[0]
                for categoria in categorias
            ]

            if categoria_id in ids_validos:
                break

            print("Categoria inválida.")

        except ValueError:
            print("Digite um número válido.")

    print()
    print("ALTERAÇÕES")
    print("----------------------------------------")

    print(
        f"Descrição: "
        f"{descricao_atual} → "
        f"{nova_descricao}"
    )

    nova_categoria = next(
        categoria[1]
        for categoria in categorias
        if categoria[0] == categoria_id
    )

    print(
        f"Categoria: "
        f"{categoria_atual} → "
        f"{nova_categoria}"
    )

    print("----------------------------------------")

    confirmar = input(
        "Confirmar alterações? (s/n): "
    ).strip().lower()

    if confirmar != "s":
        print()
        print("Edição cancelada.")
        return

    sucesso = atualizar_parcelamento(
        id_parcelamento,
        nova_descricao,
        categoria_id
    )

    print()

    if sucesso:
        print(
            "Parcelamento atualizado "
            "com sucesso!"
        )

    else:
        print(
            "Não foi possível atualizar "
            "o parcelamento."
        )

def alterar_status_parcelamento_menu():
    print()
    print("========================================")
    print("      PAUSAR / REATIVAR PARCELAMENTO")
    print("========================================")

    parcelamentos = listar_parcelamentos()

    if not parcelamentos:
        print()
        print("Nenhum parcelamento cadastrado.")
        return

    print()

    for parcelamento in parcelamentos:
        (
            id_parcelamento,
            descricao,
            tipo,
            categoria,
            valor_total,
            quantidade_parcelas,
            data_inicio,
            ativa
        ) = parcelamento

        if ativa:
            status = "🟢 ATIVO"
        else:
            status = "⏸️ INATIVO"

        print(
            f"{id_parcelamento} - "
            f"{descricao} - "
            f"{status}"
        )

    print()

    while True:
        try:
            id_parcelamento = int(
                input(
                    "Escolha um parcelamento: "
                )
            )

            ids_validos = [
                parcelamento[0]
                for parcelamento in parcelamentos
            ]

            if id_parcelamento in ids_validos:
                break

            print("Parcelamento inválido.")

        except ValueError:
            print("Digite um número válido.")

    parcelamento_selecionado = next(
        parcelamento
        for parcelamento in parcelamentos
        if parcelamento[0] == id_parcelamento
    )

    ativa_atual = parcelamento_selecionado[7]
    descricao = parcelamento_selecionado[1]

    print()

    if ativa_atual:
        print(
            f"O parcelamento '{descricao}' "
            f"está ATIVO."
        )

        print()
        print("1 - Pausar parcelamento")
        print("0 - Cancelar")

        opcao = input(
            "Escolha uma opção: "
        )

        if opcao == "1":
            nova_ativa = 0
        else:
            print()
            print("Operação cancelada.")
            return

    else:
        print(
            f"O parcelamento '{descricao}' "
            f"está INATIVO."
        )

        print()
        print("1 - Reativar parcelamento")
        print("0 - Cancelar")

        opcao = input(
            "Escolha uma opção: "
        )

        if opcao == "1":
            nova_ativa = 1
        else:
            print()
            print("Operação cancelada.")
            return

    sucesso = alterar_status_parcelamento(
        id_parcelamento,
        nova_ativa
    )

    print()

    if sucesso:
        if nova_ativa:
            print(
                "Parcelamento reativado "
                "com sucesso!"
            )
        else:
            print(
                "Parcelamento pausado "
                "com sucesso!"
            )

    else:
        print(
            "Não foi possível alterar "
            "o status do parcelamento."
        )

def excluir_parcelamento_menu():
    print()
    print("========================================")
    print("        EXCLUIR PARCELAMENTO")
    print("========================================")

    parcelamentos = listar_parcelamentos()

    if not parcelamentos:
        print()
        print("Nenhum parcelamento cadastrado.")
        return

    print()

    for parcelamento in parcelamentos:
        (
            id_parcelamento,
            descricao,
            tipo,
            categoria,
            valor_total,
            quantidade_parcelas,
            data_inicio,
            ativa
        ) = parcelamento

        print(
            f"{id_parcelamento} - "
            f"{descricao} - "
            f"{formatar_moeda(valor_total)}"
        )

    print()

    while True:
        try:
            id_parcelamento = int(
                input(
                    "Escolha um parcelamento: "
                )
            )

            ids_validos = [
                parcelamento[0]
                for parcelamento in parcelamentos
            ]

            if id_parcelamento in ids_validos:
                break

            print("Parcelamento inválido.")

        except ValueError:
            print("Digite um número válido.")

    parcelamento_selecionado = next(
        parcelamento
        for parcelamento in parcelamentos
        if parcelamento[0] == id_parcelamento
    )

    descricao = parcelamento_selecionado[1]
    valor_total = parcelamento_selecionado[4]
    quantidade_parcelas = parcelamento_selecionado[5]

    print()
    print("⚠️ ATENÇÃO:")
    print()
    print(
        f"Você está prestes a excluir "
        f"o parcelamento '{descricao}'."
    )

    print(
        f"Valor total: "
        f"{formatar_moeda(valor_total)}"
    )

    print(
        f"Quantidade de parcelas: "
        f"{quantidade_parcelas}"
    )

    print()
    print(
        "As parcelas ainda não pagas "
        "também serão excluídas."
    )

    print()
    print("1 - Sim, excluir")
    print("0 - Cancelar")

    opcao = input(
        "Escolha uma opção: "
    )

    if opcao != "1":
        print()
        print("Exclusão cancelada.")
        return

    sucesso, motivo = excluir_parcelamento(
        id_parcelamento
    )

    print()

    if sucesso:
        print(
            "Parcelamento excluído "
            "com sucesso!"
        )

    elif motivo == "possui_pagamentos":
        print(
            "Não é possível excluir "
            "este parcelamento."
        )

        print()
        print(
            "Ele possui parcelas já pagas "
            "e lançamentos financeiros "
            "vinculados."
        )

        print(
            "O histórico financeiro "
            "foi preservado."
        )

    else:
        print(
            "Parcelamento não encontrado."
        )


def menu_parcelamentos():
    while True:
        exibir_menu(
            "PARCELAMENTOS",
            "Gerencie suas compras e compromissos parcelados",
            [
                ("1", "Novo parcelamento"),
                ("2", "Listar parcelamentos"),
                ("3", "Ver parcelas"),
                ("4", "Editar parcelamento"),
                ("5", "Pausar / Reativar parcelamento"),
                ("6", "Excluir parcelamento"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            novo_parcelamento()

        elif opcao == "2":
            mostrar_parcelamentos()

        elif opcao == "3":
            mostrar_parcelas_parcelamento()

        elif opcao == "4":
            editar_parcelamento_menu()

        elif opcao == "5":
            alterar_status_parcelamento_menu()

        elif opcao == "6":
            excluir_parcelamento_menu()

        elif opcao == "0":
            return

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


def novo_parcelamento():
    print()
    print("========================================")
    print("          NOVO PARCELAMENTO")
    print("========================================")

    descricao = input(
        "Descrição: "
    ).strip()

    if not descricao:
        print("A descrição é obrigatória.")
        return

    tipo = ler_tipo()

    print()
    print("Categorias disponíveis:")

    categorias = listar_categorias(tipo)

    for categoria in categorias:
        print(
            f"{categoria[0]} - {categoria[1]}"
        )

    print()

    while True:
        try:
            categoria_id = int(
                input("Categoria: ")
            )

            ids_validos = [
                categoria[0]
                for categoria in categorias
            ]

            if categoria_id in ids_validos:
                break

            print("Categoria inválida.")

        except ValueError:
            print("Digite um número válido.")

    print()

    valor_total = ler_valor()

    print()

    while True:
        try:
            quantidade_parcelas = int(
                input(
                    "Quantidade de parcelas: "
                )
            )

            if quantidade_parcelas <= 0:
                print(
                    "A quantidade deve ser "
                    "maior que zero."
                )
                continue

            break

        except ValueError:
            print(
                "Digite um número inteiro válido."
            )

    print()
    print("DATA DA PRIMEIRA PARCELA")

    data_inicio = ler_data()

    valor_parcela = (
        valor_total / quantidade_parcelas
    )

    print()
    print("RESUMO DO PARCELAMENTO")
    print("----------------------------------------")

    print(
        f"Descrição: {descricao}"
    )

    print(
        f"Tipo: {tipo}"
    )

    print(
        f"Valor total: "
        f"{formatar_moeda(valor_total)}"
    )

    print(
        f"Parcelas: "
        f"{quantidade_parcelas}"
    )

    print(
        f"Valor aproximado por parcela: "
        f"{formatar_moeda(valor_parcela)}"
    )

    print(
        f"Primeira parcela: "
        f"{formatar_data(data_inicio)}"
    )

    print("----------------------------------------")

    confirmar = input(
        "Confirmar? (s/n): "
    ).strip().lower()

    if confirmar != "s":
        print()
        print("Cadastro cancelado.")
        return

    parcelamento_id = adicionar_parcelamento(
        descricao,
        tipo,
        categoria_id,
        valor_total,
        quantidade_parcelas,
        data_inicio
    )

    print()
    print(
        "Parcelamento criado "
        "com sucesso!"
    )

    print(
        f"ID do parcelamento: "
        f"{parcelamento_id}"
    )

def mostrar_parcelamentos():
    print()
    print("========================================")
    print("           PARCELAMENTOS")
    print("========================================")

    parcelamentos = listar_parcelamentos()

    if not parcelamentos:
        print()
        print("Nenhum parcelamento cadastrado.")
        return

    print()

    print(
        f"{'ID':<5}"
        f"{'DESCRIÇÃO':<18}"
        f"{'TIPO':<10}"
        f"{'CATEGORIA':<15}"
        f"{'PARCELA':<16}"
        f"{'TOTAL':<16}"
        f"{'PARCELAS':<10}"
        f"{'PROGRESSO':<14}"
        f"STATUS"
    )

    print("-" * 125)

    for parcelamento in parcelamentos:
        (
            id_parcelamento,
            descricao,
            tipo,
            categoria,
            valor_total,
            quantidade_parcelas,
            data_inicio,
            ativa
        ) = parcelamento

        valor_parcela = (
            valor_total / quantidade_parcelas
        )

        resumo = resumo_parcelas_parcelamento(
            id_parcelamento
        )

        (
            total_parcelas,
            parcelas_pagas,
            parcelas_pendentes,
            valor_pago,
            valor_pendente
        ) = resumo

        progresso = (
            f"{parcelas_pagas}/"
            f"{total_parcelas}"
        )

        if parcelas_pagas == total_parcelas:
            progresso = (
                f"{progresso} 🟢"
            )
        elif parcelas_pagas > 0:
            progresso = (
                f"{progresso} 🟡"
            )
        else:
            progresso = (
                f"{progresso} 🔴"
            )

        if ativa:
            status = "🟢 ATIVO"
        else:
            status = "⏸️ INATIVO"

        print(
            f"{id_parcelamento:<5}"
            f"{descricao[:16]:<18}"
            f"{tipo:<10}"
            f"{categoria[:13]:<15}"
            f"{formatar_moeda(valor_parcela):<16}"
            f"{formatar_moeda(valor_total):<16}"
            f"{quantidade_parcelas:<10}"
            f"{progresso:<14}"
            f"{status}"
        )

    print("-" * 125)

# ============================================================
# RESUMOS
# ============================================================

def mostrar_resumo_financeiro():
    dashboard = obter_dashboard()

    print()
    print("========================================")
    print("          DASHBOARD FINANCEIRO")
    print("========================================")

    print()
    print("MOVIMENTAÇÃO FINANCEIRA")
    print("----------------------------------------")

    print(
        f"Receitas: "
        f"{formatar_moeda(dashboard['receitas'])}"
    )

    print(
        f"Despesas: "
        f"{formatar_moeda(dashboard['despesas'])}"
    )

    print(
        f"Saldo:    "
        f"{formatar_moeda(dashboard['saldo'])}"
    )

    print()
    print("CARTÕES")
    print("----------------------------------------")

    print(
        f"Cartões ativos:    "
        f"{dashboard['quantidade_cartoes_ativos']}"
    )

    print(
        f"Limite total:      "
        f"{formatar_moeda(dashboard['limite_total'])}"
    )

    print(
        f"Limite utilizado:  "
        f"{formatar_moeda(dashboard['limite_utilizado'])}"
    )

    print(
        f"Limite disponível: "
        f"{formatar_moeda(dashboard['limite_disponivel'])}"
    )

    print(
        f"Utilização:        "
        f"{dashboard['percentual_limite_utilizado']:.1f}%"
    )

    print()
    print("COMPROMISSOS")
    print("----------------------------------------")

    print(
        f"Faturas abertas:      "
        f"{dashboard['quantidade_faturas_abertas']}"
    )

    print(
        f"Valor das faturas:    "
        f"{formatar_moeda(dashboard['faturas_abertas'])}"
    )

    print(
        f"Recorrências abertas: "
        f"{formatar_moeda(dashboard['recorrencias_abertas'])}"
    )

    print(
        f"Parcelamentos abertos:"
        f" {formatar_moeda(dashboard['parcelamentos_abertos'])}"
    )

    print("========================================")


def mostrar_resumo_mensal():
    print()
    print("========================================")
    print("            RESUMO MENSAL")
    print("========================================")

    while True:
        try:
            ano = int(
                input("Ano: ")
            )

            mes = int(
                input("Mês (1-12): ")
            )

            if 1 <= mes <= 12:
                break

            print(
                "O mês deve estar entre 1 e 12."
            )

        except ValueError:
            print(
                "Digite números válidos."
            )

    resumo = obter_resumo_mensal_detalhado(
        ano,
        mes
    )

    print()
    print(
        f"PERÍODO: {mes:02d}/{ano}"
    )

    print("----------------------------------------")
    print("MOVIMENTAÇÃO")
    print("----------------------------------------")

    print(
        f"Receitas: "
        f"{formatar_moeda(resumo['receitas'])}"
    )

    print(
        f"Despesas: "
        f"{formatar_moeda(resumo['despesas'])}"
    )

    print(
        f"Saldo:    "
        f"{formatar_moeda(resumo['saldo'])}"
    )

    print()
    print("LANÇAMENTOS")
    print("----------------------------------------")

    print(
        f"Receitas lançadas: "
        f"{resumo['quantidade_receitas']}"
    )

    print(
        f"Despesas lançadas: "
        f"{resumo['quantidade_despesas']}"
    )

    print()
    print("DESTAQUES")
    print("----------------------------------------")

    if resumo["maior_categoria"]:

        print(
            f"Maior categoria: "
            f"{resumo['maior_categoria']}"
        )

        print(
            f"Total: "
            f"{formatar_moeda(resumo['maior_categoria_valor'])}"
        )

    else:
        print(
            "Nenhuma despesa encontrada."
        )

    print()
    print("CARTÃO DE CRÉDITO")
    print("----------------------------------------")

    print(
        f"Gastos no cartão: "
        f"{formatar_moeda(resumo['gastos_cartao'])}"
    )
    
    print(
        f"Faturas do mês (fechamento): "
        f"{formatar_moeda(resumo['valor_faturas_mes'])}"
    )

    print("----------------------------------------")

    print()
    print("DESPESAS POR CATEGORIA")
    print("----------------------------------------")

    categorias = despesas_por_categoria_mensal(
        ano,
        mes
    )

    if not categorias:
        print(
            "Nenhuma despesa encontrada."
        )

    else:
        for categoria, total in categorias:
            print(
                f"{categoria}: "
                f"{formatar_moeda(total)}"
            )
    print()
    print("GRÁFICO — DESPESAS POR CATEGORIA")
    print("----------------------------------------")

    if not categorias:
        print("Não há despesas para representar.")

    else:
        maior_valor = max(
            total
            for _, total in categorias
        )

        total_despesas = sum(
            total
            for _, total in categorias
        )

        tamanho_maximo = 30

        for categoria, total in categorias:

            barra = int(
                (total / maior_valor)
                * tamanho_maximo
            )

            percentual = (
                (total / total_despesas) * 100
            )

            print()
            print(categoria)

            print(
                f"  |"
                f"{'█' * barra}"
                f" {formatar_moeda(total)}"
                f" ({percentual:.1f}%)"
            )

    print()
    print("========================================")

def mostrar_projecao_faturas():
    print()
    print("========================================")
    print("        PROJEÇÃO DE FATURAS")
    print("========================================")

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão cadastrado.")
        return

    for cartao in cartoes:
        cartao_id = cartao[0]
        nome_cartao = cartao[1]

        projecao = obter_projecao_faturas(
            cartao_id
        )

        print()
        print("----------------------------------------")
        print(f"Cartão: {nome_cartao}")
        print("----------------------------------------")

        if not projecao:
            print("Nenhuma fatura em aberto na projeção.")
            continue

        total = 0

        maior_fatura = max(
            projecao,
            key=lambda fatura: fatura["valor_total"]
        )

        maior_valor = maior_fatura["valor_total"]

        print()
        print("FATURAS POR MÊS")
        print("----------------------------------------")

        for fatura in projecao:
            valor = fatura["valor_total"]
            total += valor

            barra = (
                int(valor / maior_valor * 30)
                if maior_valor > 0
                else 0
            )

            print()
            print(
                f"{fatura['mes']:02d}/"
                f"{fatura['ano']}"
            )

            print(
                f"  {'█' * barra} "
                f"{formatar_moeda(valor)}"
            )

        print()
        print("----------------------------------------")
        print("RESUMO DA PROJEÇÃO")
        print("----------------------------------------")

        print(
            f"Total acumulado: "
            f"{formatar_moeda(total)}"
        )

        print(
            f"Maior fatura: "
            f"{maior_fatura['mes']:02d}/"
            f"{maior_fatura['ano']} - "
            f"{formatar_moeda(maior_valor)}"
        )

        print()
        print("ACUMULADO MÊS A MÊS")
        print("----------------------------------------")

        acumulado = 0

        for fatura in projecao:
            acumulado += fatura["valor_total"]

            print(
                f"{fatura['mes']:02d}/"
                f"{fatura['ano']}: "
                f"{formatar_moeda(acumulado)}"
            )


def menu_resumos():
    while True:
        exibir_menu(
            "RESUMOS",
            "Acompanhe sua situação e evolução financeira",
            [
                ("1", "Resumo financeiro"),
                ("2", "Resumo mensal"),
                ("3", "Evolução anual"),
                ("4", "Comparar meses"),
                ("5", "Análise dos cartões"),
                ("6", "Projeção de faturas"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            mostrar_resumo_financeiro()

        elif opcao == "2":
            mostrar_resumo_mensal()

        elif opcao == "3":
            mostrar_evolucao_anual()

        elif opcao == "4":
            mostrar_comparacao_mensal()

        elif opcao == "5":
            mostrar_analise_cartoes()

        elif opcao == "6":
            mostrar_projecao_faturas()

        elif opcao == "0":
            break

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


def mostrar_comparacao_mensal():
    print()
    print("========================================")
    print("          COMPARAÇÃO MENSAL")
    print("========================================")

    while True:
        try:
            ano = int(
                input("Ano: ")
            )

            mes = int(
                input("Mês (1-12): ")
            )

            if 1 <= mes <= 12:
                break

            print(
                "O mês deve estar entre 1 e 12."
            )

        except ValueError:
            print(
                "Digite números válidos."
            )

    comparacao = obter_comparacao_mensal(
        ano,
        mes
    )

    mes_atual = comparacao["mes_atual"]
    ano_atual = comparacao["ano_atual"]

    mes_anterior = comparacao["mes_anterior"]
    ano_anterior = comparacao["ano_anterior"]

    nomes_meses = [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro"
    ]

    print()
    print(
        f"{nomes_meses[mes_anterior - 1]} "
        f"{ano_anterior}"
        f"  →  "
        f"{nomes_meses[mes_atual - 1]} "
        f"{ano_atual}"
    )

    print()
    print("RECEITAS")
    print("----------------------------------------")

    print(
        f"Anterior: "
        f"{formatar_moeda(comparacao['receitas_anterior'])}"
    )

    print(
        f"Atual:    "
        f"{formatar_moeda(comparacao['receitas_atual'])}"
    )

    if comparacao["variacao_receitas"] is None:
        print("Variação: não calculável")

    else:
        print(
            f"Variação: "
            f"{comparacao['variacao_receitas']:.2f}%"
        )

    print()
    print("DESPESAS")
    print("----------------------------------------")

    print(
        f"Anterior: "
        f"{formatar_moeda(comparacao['despesas_anterior'])}"
    )

    print(
        f"Atual:    "
        f"{formatar_moeda(comparacao['despesas_atual'])}"
    )

    if comparacao["variacao_despesas"] is None:
        print("Variação: não calculável")

    else:
        print(
            f"Variação: "
            f"{comparacao['variacao_despesas']:.2f}%"
        )

    print()
    print("SALDO")
    print("----------------------------------------")

    print(
        f"Anterior: "
        f"{formatar_moeda(comparacao['saldo_anterior'])}"
    )

    print(
        f"Atual:    "
        f"{formatar_moeda(comparacao['saldo_atual'])}"
    )

    if comparacao["variacao_saldo"] is None:
        print("Variação: não calculável")

    else:
        print(
            f"Variação: "
            f"{comparacao['variacao_saldo']:.2f}%"
        )

    print()
    print("========================================")

def mostrar_gastos_cartao_categoria(
    cartao_id,
    ano,
    mes
):
    categorias = obter_gastos_cartao_por_categoria(
        cartao_id,
        ano,
        mes
    )

    if not categorias:
        print("Nenhum gasto encontrado no período.")
        return

    total = sum(
        valor
        for _, valor in categorias
    )

    maior_valor = max(
        valor
        for _, valor in categorias
    )

    tamanho_maximo = 30

    print()
    print("GASTOS POR CATEGORIA")
    print("----------------------------------------")

    for categoria, valor in categorias:

        barra = int(
            (valor / maior_valor)
            * tamanho_maximo
        )

        percentual = (
            valor / total
        ) * 100

        print()
        print(categoria)

        print(
            f"  |"
            f"{'█' * barra}"
            f" {formatar_moeda(valor)}"
            f" ({percentual:.1f}%)"
        )

    print("----------------------------------------")
    print(
        f"Total: {formatar_moeda(total)}"
    )

def mostrar_analise_cartoes():
    print()
    print("========================================")
    print("          ANÁLISE DOS CARTÕES")
    print("========================================")

    while True:
        try:
            ano = int(
                input("Ano da análise: ")
            )

            mes = int(
                input("Mês da análise (1-12): ")
            )

            if 1 <= mes <= 12:
                break

            print(
                "O mês deve estar entre 1 e 12."
            )

        except ValueError:
            print(
                "Digite números válidos."
            )

    cartoes = listar_cartoes()

    if not cartoes:
        print()
        print("Nenhum cartão cadastrado.")
        return

    nomes_meses = [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro"
    ]

    print()
    print(
        f"PERÍODO: "
        f"{nomes_meses[mes - 1]} / {ano}"
    )

    for cartao in cartoes:

        cartao_id = cartao[0]

        resumo = obter_resumo_cartao(
            cartao_id
        )

        if resumo is None:
            continue

        print()
        print("----------------------------------------")
        print(
            f"{resumo['nome']}"
        )
        print("----------------------------------------")

        status = (
            "ATIVO"
            if resumo["ativo"]
            else "INATIVO"
        )

        print(
            f"Status:             {status}"
        )

        print(
            f"Limite total:       "
            f"{formatar_moeda(resumo['limite'])}"
        )

        print(
            f"Limite utilizado:   "
            f"{formatar_moeda(resumo['limite_utilizado'])}"
        )

        print(
            f"Limite disponível:  "
            f"{formatar_moeda(resumo['limite_disponivel'])}"
        )

        print(
            f"Utilização:         "
            f"{resumo['percentual_utilizado']:.1f}%"
        )

        print()
        print("CONFIGURAÇÃO")

        print(
            f"Fechamento:         "
            f"dia {resumo['dia_fechamento']:02d}"
        )

        print(
            f"Vencimento:         "
            f"dia {resumo['dia_vencimento']:02d}"
        )

        print()
        print("FATURAS")

        print(
            f"Faturas abertas:    "
            f"{resumo['quantidade_faturas']}"
        )

        print(
            f"Total em aberto:    "
            f"{formatar_moeda(resumo['total_faturas'])}"
        )

        proxima_fatura = resumo["proxima_fatura"]

        if proxima_fatura:

            (
                id_fatura,
                mes_fatura,
                ano_fatura,
                data_fechamento,
                data_vencimento,
                valor_total
            ) = proxima_fatura

            print()
            print("PRÓXIMA FATURA")

            print(
                f"Valor:              "
                f"{formatar_moeda(valor_total)}"
            )

            print(
                f"Fechamento:         "
                f"{formatar_data(data_fechamento)}"
            )

            print(
                f"Vencimento:         "
                f"{formatar_data(data_vencimento)}"
            )

        else:

            print()
            print("PRÓXIMA FATURA")
            print("Nenhuma fatura em aberto.")

        # ==============================
        # GASTOS POR CATEGORIA
        # ==============================

        mostrar_gastos_cartao_categoria(
            cartao_id,
            ano,
            mes
        )


                # ==============================
        # COMPROMISSO DAS FATURAS
        # ==============================

        compromissos = obter_compromisso_faturas_cartao(
            cartao_id
        )

        print()
        print("COMPROMISSO DAS FATURAS")
        print("----------------------------------------")

        if not compromissos:
            print("Nenhuma fatura encontrada.")

        else:
            for fatura in compromissos:

                status_fatura = (
                    "PAGA"
                    if fatura["paga"]
                    else "ABERTA"
                )

                print()
                print(
                    f"{fatura['mes']:02d}/"
                    f"{fatura['ano']}"
                )

                print(
                    f"  Total:       "
                    f"{formatar_moeda(fatura['valor_total'])}"
                )

                print(
                    f"  À vista:     "
                    f"{formatar_moeda(fatura['valor_avista'])}"
                )

                print(
                    f"  Parcelas:    "
                    f"{formatar_moeda(fatura['valor_parcelas'])}"
                )

                print(
                    f"  Vencimento:  "
                    f"{formatar_data(fatura['data_vencimento'])}"
                )

                print(
                    f"  Status:      "
                    f"{status_fatura}"
                )

    print()
    print("========================================")

def mostrar_evolucao_anual():
    print()
    print("========================================")
    print("            EVOLUÇÃO ANUAL")
    print("========================================")

    while True:
        try:
            ano = int(
                input("Ano: ")
            )

            if ano > 0:
                break

            print(
                "Digite um ano válido."
            )

        except ValueError:
            print(
                "Digite um número válido."
            )

    evolucao = obter_evolucao_anual(ano)

    nomes_meses = [
        "Janeiro",
        "Fevereiro",
        "Março",
        "Abril",
        "Maio",
        "Junho",
        "Julho",
        "Agosto",
        "Setembro",
        "Outubro",
        "Novembro",
        "Dezembro"
    ]

    print()
    print(f"ANO: {ano}")

    print("----------------------------------------")

    for item in evolucao:
        mes = item["mes"]
        receitas = item["receitas"]
        despesas = item["despesas"]
        saldo = item["saldo"]

        print()
        print(f"{nomes_meses[mes - 1]}")

        print(
            f"  Receitas: "
            f"{formatar_moeda(receitas)}"
        )

        print(
            f"  Despesas: "
            f"{formatar_moeda(despesas)}"
        )

        print(
            f"  Saldo:    "
            f"{formatar_moeda(saldo)}"
        )

    print()
    print("----------------------------------------")
    print()
    print("GRÁFICO — RECEITAS X DESPESAS")
    print("----------------------------------------")

    maior_valor = max(
        max(item["receitas"], item["despesas"])
        for item in evolucao
    )

    if maior_valor == 0:
        print("Não há movimentação financeira neste ano.")

    else:
        tamanho_maximo = 30

        for item in evolucao:
            mes = item["mes"]
            receitas = item["receitas"]
            despesas = item["despesas"]

            barra_receita = int(
                (receitas / maior_valor)
                * tamanho_maximo
            )

            barra_despesa = int(
                (despesas / maior_valor)
                * tamanho_maximo
            )

            print()
            print(
                f"{nomes_meses[mes - 1]}"
            )

            print(
                f"  Receita  |"
                f"{'█' * barra_receita}"
                f" {formatar_moeda(receitas)}"
            )

            print(
                f"  Despesa  |"
                f"{'█' * barra_despesa}"
                f" {formatar_moeda(despesas)}"
            )

    print()
    print("========================================")

# ============================================================
# RELATÓRIOS
# ============================================================

def mostrar_despesas_por_categoria():
    print()
    print("========================================")
    print("        DESPESAS POR CATEGORIA")
    print("========================================")

    categorias = despesas_por_categoria()

    if not categorias:
        print("Nenhuma despesa cadastrada.")

    else:
        for categoria, total in categorias:
            print(
                f"{categoria}: "
                f"{formatar_moeda(total)}"
            )


def mostrar_despesas_por_categoria_mes():
    print()
    print("========================================")
    print("   DESPESAS POR CATEGORIA NO MÊS")
    print("========================================")

    while True:
        try:
            ano = int(
                input("Ano: ")
            )

            mes = int(
                input("Mês (1-12): ")
            )

            if 1 <= mes <= 12:
                break

            print(
                "O mês deve estar entre 1 e 12."
            )

        except ValueError:
            print(
                "Digite números válidos."
            )

    categorias = despesas_por_categoria_mensal(
        ano,
        mes
    )

    print()
    print(
        f"PERÍODO: {mes:02d}/{ano}"
    )

    print("----------------------------------------")

    if not categorias:
        print("Nenhuma despesa encontrada.")

    else:
        for categoria, total in categorias:
            print(
                f"{categoria}: "
                f"{formatar_moeda(total)}"
            )



def menu_relatorios():
    while True:
        exibir_menu(
            "RELATÓRIOS",
            "Analise suas despesas por categoria e período",
            [
                ("1", "Despesas por categoria"),
                ("2", "Despesas por categoria no mês"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            mostrar_despesas_por_categoria()

        elif opcao == "2":
            mostrar_despesas_por_categoria_mes()

        elif opcao == "0":
            break

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )



# ============================================================
# CATEGORIAS
# ============================================================

def listar_todas_categorias():
    print()
    print("========================================")
    print("             CATEGORIAS")
    print("========================================")

    categorias = listar_categorias()

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        categoria_id, nome, tipo = categoria

        print(
            f"{numero} - "
            f"{nome} ({tipo})"
        )

def criar_nova_categoria():
    print()
    print("========================================")
    print("          NOVA CATEGORIA")
    print("========================================")

    nome = input(
        "Nome da categoria: "
    ).strip()

    while not nome:
        print(
            "O nome da categoria "
            "não pode ficar vazio."
        )

        nome = input(
            "Nome da categoria: "
        ).strip()

    print()
    print("TIPO DA CATEGORIA")
    print("1 - Receita")
    print("2 - Despesa")

    while True:
        tipo_opcao = input(
            "Escolha uma opção: "
        )

        if tipo_opcao == "1":
            tipo = "receita"
            break

        elif tipo_opcao == "2":
            tipo = "despesa"
            break

        else:
            print(
                "Opção inválida. "
                "Escolha 1 ou 2."
            )

    sucesso = adicionar_categoria(
        nome,
        tipo
    )

    print()

    if sucesso:
        print(
            "Categoria criada com sucesso!"
        )

    else:
        print(
            "Essa categoria já existe "
            "para esse tipo."
        )

def editar_categoria():
    print()
    print("========================================")
    print("          EDITAR CATEGORIA")
    print("========================================")

    categorias = listar_categorias()

    if not categorias:
        print("Nenhuma categoria cadastrada.")
        return

    print()

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        id_categoria, nome, tipo = categoria

        print(
            f"{numero} - "
            f"{nome} ({tipo})"
        )

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma categoria: "
                )
            )

            if 1 <= escolha <= len(categorias):
                categoria_selecionada = (
                    categorias[escolha - 1]
                )
                break

            print("Categoria inválida.")

        except ValueError:
            print(
                "Digite um número válido."
            )

    (
        id_categoria,
        nome_atual,
        tipo_atual
    ) = categoria_selecionada

    print()
    print(
        f"Nome atual: {nome_atual}"
    )

    novo_nome = input(
        "Novo nome: "
    ).strip()

    while not novo_nome:
        print(
            "O nome da categoria "
            "não pode ficar vazio."
        )

        novo_nome = input(
            "Novo nome: "
        ).strip()

    print()
    print(
        f"Tipo atual: {tipo_atual}"
    )

    print("1 - Receita")
    print("2 - Despesa")

    while True:
        tipo_opcao = input(
            "Novo tipo: "
        )

        if tipo_opcao == "1":
            novo_tipo = "receita"
            break

        elif tipo_opcao == "2":
            novo_tipo = "despesa"
            break

        else:
            print(
                "Opção inválida. "
                "Escolha 1 ou 2."
            )

    sucesso = atualizar_categoria(
        id_categoria,
        novo_nome,
        novo_tipo
    )

    print()

    if sucesso:
        print(
            "Categoria atualizada "
            "com sucesso!"
        )

    else:
        print(
            "Não foi possível atualizar "
            "a categoria."
        )

def excluir_categoria_menu():
    print()
    print("========================================")
    print("         EXCLUIR CATEGORIA")
    print("========================================")

    categorias = listar_categorias()

    if not categorias:
        print("Nenhuma categoria cadastrada.")
        return

    print()

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        id_categoria, nome, tipo = categoria

        print(
            f"{numero} - "
            f"{nome} ({tipo})"
        )

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma categoria: "
                )
            )

            if 1 <= escolha <= len(categorias):
                id_categoria, nome, tipo = (
                    categorias[escolha - 1]
                )
                break

            print("Categoria inválida.")

        except ValueError:
            print(
                "Digite um número válido."
            )

    print()
    print("CATEGORIA SELECIONADA")
    print("----------------------------------------")
    print(f"Nome: {nome}")
    print(f"Tipo: {tipo}")

    print()
    print("Tem certeza que deseja excluir?")
    print("1 - Sim")
    print("2 - Não")

    confirmacao = input(
        "Escolha uma opção: "
    )

    if confirmacao == "2":
        print()
        print("Exclusão cancelada.")
        return

    if confirmacao != "1":
        print()
        print("Opção inválida.")
        return

    sucesso, quantidade = excluir_categoria(
        id_categoria
    )

    print()

    if sucesso:
        print(
            "Categoria excluída "
            "com sucesso!"
        )

    else:
        print(
            "Não é possível excluir "
            "esta categoria."
        )

        print(
            f"Existem {quantidade} "
            f"lançamento(s) associado(s) a ela."
        )

def nova_recorrencia():
    print()
    print("========================================")
    print("          NOVA RECORRÊNCIA")
    print("========================================")

    descricao = input(
        "Descrição: "
    ).strip()

    while not descricao:
        print(
            "A descrição não pode ficar vazia."
        )

        descricao = input(
            "Descrição: "
        ).strip()

    tipo = ler_tipo()

    print()
    print("CATEGORIAS")

    categorias = listar_categorias(tipo)

    for numero, categoria in enumerate(
        categorias,
        start=1
    ):
        categoria_id, nome = categoria

        print(
            f"{numero} - {nome}"
        )

    while True:
        try:
            escolha = int(
                input(
                    "Escolha uma categoria: "
                )
            )

            if 1 <= escolha <= len(categorias):
                categoria_id = categorias[
                    escolha - 1
                ][0]
                break

            print("Categoria inválida.")

        except ValueError:
            print(
                "Digite um número válido."
            )

    valor = ler_valor()

    print()
    print("FREQUÊNCIA")
    print("1 - Semanal")
    print("2 - Mensal")
    print("3 - Anual")

    while True:
        frequencia_opcao = input(
            "Escolha uma frequência: "
        )

        if frequencia_opcao == "1":
            frequencia = "semanal"
            break

        elif frequencia_opcao == "2":
            frequencia = "mensal"
            break

        elif frequencia_opcao == "3":
            frequencia = "anual"
            break

        else:
            print(
                "Opção inválida. "
                "Escolha 1, 2 ou 3."
            )

    print()
    print("DATA DE INÍCIO")

    data_inicio = ler_data()

    print()
    print("DATA DE TÉRMINO")
    print("1 - Sem término")
    print("2 - Definir término")

    while True:
        termino_opcao = input(
            "Escolha uma opção: "
        )

        if termino_opcao == "1":
            data_fim = None
            break

        elif termino_opcao == "2":
            print()
            print(
                "Digite a data de término."
            )

            data_fim = ler_data()
            break

        else:
            print(
                "Opção inválida. "
                "Escolha 1 ou 2."
            )

    recorrencia_id = adicionar_recorrencia(
        descricao,
        tipo,
        categoria_id,
        valor,
        frequencia,
        data_inicio,
        data_fim
    )

    print()
    print(
        "Recorrência criada com sucesso!"
    )

    print(
        f"ID da recorrência: "
        f"{recorrencia_id}"
    )

    print(
        "A primeira ocorrência foi criada "
        "como NÃO PAGA."
    )


def menu_categorias():
    while True:
        exibir_menu(
            "CATEGORIAS",
            "Organize suas receitas e despesas por categoria",
            [
                ("1", "Listar categorias"),
                ("2", "Criar categoria"),
                ("3", "Editar categoria"),
                ("4", "Excluir categoria"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            listar_todas_categorias()

        elif opcao == "2":
            criar_nova_categoria()

        elif opcao == "3":
            editar_categoria()

        elif opcao == "4":
            excluir_categoria_menu()

        elif opcao == "0":
            break

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


# ============================================================
# MENU PRINCIPAL
# ============================================================


def filtrar_lancamentos():
    while True:
        exibir_menu(
            "FILTRAR LANÇAMENTOS",
            "Consulte suas movimentações por diferentes critérios",
            [
                ("1", "Filtrar por tipo"),
                ("2", "Filtrar por categoria"),
                ("3", "Filtrar por período"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            tipo = ler_tipo()

            lancamentos = listar_lancamentos(
                tipo=tipo
            )

            print()
            print("========================================")
            print(f"      LANÇAMENTOS - {tipo.upper()}")
            print("========================================")

            if not lancamentos:
                print("Nenhum lançamento encontrado.")
            else:
                print()
                for lancamento in lancamentos:
                    mostrar_lancamento(lancamento)

        elif opcao == "2":
            print()
            print("Categorias:")

            categorias = listar_categorias()

            for categoria in categorias:
                id_categoria, nome, tipo_categoria = categoria

                print(
                    f"{id_categoria} - "
                    f"{nome} ({tipo_categoria})"
                )

            print()

            try:
                categoria_id = int(
                    input("ID da categoria: ").strip()
                )
            except ValueError:
                print("ID inválido.")
                continue

            lancamentos = listar_lancamentos(
                categoria_id=categoria_id
            )

            print()
            print("========================================")
            print("      LANÇAMENTOS DA CATEGORIA")
            print("========================================")

            if not lancamentos:
                print("Nenhum lançamento encontrado.")
            else:
                print()
                for lancamento in lancamentos:
                    mostrar_lancamento(lancamento)

        elif opcao == "3":
            print()
            print("Data inicial:")
            data_inicio = ler_data()

            print()
            print("Data final:")
            data_fim = ler_data()

            lancamentos = listar_lancamentos(
                data_inicio=data_inicio,
                data_fim=data_fim
            )

            print()
            print("========================================")
            print("       LANÇAMENTOS DO PERÍODO")
            print("========================================")

            if not lancamentos:
                print("Nenhum lançamento encontrado.")
            else:
                print()
                for lancamento in lancamentos:
                    mostrar_lancamento(lancamento)

        elif opcao == "0":
            return

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )

def menu_lancamentos():
    while True:
        exibir_menu(
            "LANÇAMENTOS",
            "Gerencie suas receitas e despesas",
            [
                ("1", "Novo lançamento"),
                ("2", "Listar lançamentos"),
                ("3", "Filtrar lançamentos"),
                ("4", "Editar lançamento"),
                ("5", "Excluir lançamento"),
                ("6", "Recorrências"),
                ("7", "Parcelamentos"),
                ("0", "Voltar")
            ]
        )

        opcao = input("Escolha uma opção: ").strip()

        if opcao == "1":
            adicionar_novo_lancamento()

        elif opcao == "2":
            mostrar_lancamentos()

        elif opcao == "3":
            filtrar_lancamentos()

        elif opcao == "4":
            editar_lancamento_menu()

        elif opcao == "5":
            excluir_lancamento_menu()

        elif opcao == "6":
            menu_recorrencias()

        elif opcao == "7":
            menu_parcelamentos()

        elif opcao == "0":
            return

        else:
            print()
            print("Opção inválida.")

def novo_cartao():
    print()
    print("========================================")
    print("              NOVO CARTÃO")
    print("========================================")

    print()

    nome = input("Nome do cartão: ").strip()

    if not nome:
        print("O nome do cartão não pode ficar vazio.")
        return

    print()
    limite = ler_valor()

    while True:
        try:
            dia_fechamento = int(
                input("Dia de fechamento (1-31): ").strip()
            )

            if 1 <= dia_fechamento <= 31:
                break

            print("Digite um dia entre 1 e 31.")

        except ValueError:
            print("Digite um número válido.")

    while True:
        try:
            dia_vencimento = int(
                input("Dia de vencimento (1-31): ").strip()
            )

            if 1 <= dia_vencimento <= 31:
                break

            print("Digite um dia entre 1 e 31.")

        except ValueError:
            print("Digite um número válido.")

    adicionar_cartao(
        nome,
        limite,
        dia_fechamento,
        dia_vencimento
    )

    print()
    print("Cartão cadastrado com sucesso!")


def editar_cartao():
    print()
    print("========================================")
    print("             EDITAR CARTÃO")
    print("========================================")

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão cadastrado.")
        return

    print()

    for cartao in cartoes:
        id_cartao, nome, limite, fechamento, vencimento, ativo = cartao

        status = "ATIVO" if ativo else "INATIVO"

        print(
            f"ID: {id_cartao} | {nome} | "
            f"Limite: {formatar_moeda(limite)} | "
            f"Fechamento: {fechamento} | "
            f"Vencimento: {vencimento} | "
            f"{status}"
        )

    print()

    try:
        cartao_id = int(input("ID do cartão que deseja editar: ").strip())
    except ValueError:
        print("ID inválido.")
        return

    cartao_selecionado = next(
        (cartao for cartao in cartoes if cartao[0] == cartao_id),
        None
    )

    if cartao_selecionado is None:
        print("Cartão não encontrado.")
        return

    _, nome_atual, limite_atual, fechamento_atual, vencimento_atual, _ = cartao_selecionado

    print()
    print("Pressione ENTER para manter o valor atual.")

    nome = input(f"Nome [{nome_atual}]: ").strip()
    if not nome:
        nome = nome_atual

    entrada_limite = input(
        f"Limite [{formatar_moeda(limite_atual)}]: "
    ).strip()

    if entrada_limite:
        try:
            limite = float(
                entrada_limite.replace(".", "").replace(",", ".")
                if "," in entrada_limite
                else entrada_limite
            )
        except ValueError:
            print("Limite inválido.")
            return
    else:
        limite = limite_atual

    entrada_fechamento = input(
        f"Dia de fechamento [{fechamento_atual}]: "
    ).strip()

    try:
        fechamento = (
            int(entrada_fechamento)
            if entrada_fechamento
            else fechamento_atual
        )
    except ValueError:
        print("Dia de fechamento inválido.")
        return

    entrada_vencimento = input(
        f"Dia de vencimento [{vencimento_atual}]: "
    ).strip()

    try:
        vencimento = (
            int(entrada_vencimento)
            if entrada_vencimento
            else vencimento_atual
        )
    except ValueError:
        print("Dia de vencimento inválido.")
        return

    print()
    print("RESUMO DAS ALTERAÇÕES")
    print("----------------------------------------")
    print(f"Nome: {nome}")
    print(f"Limite: {formatar_moeda(limite)}")
    print(f"Fechamento: dia {fechamento}")
    print(f"Vencimento: dia {vencimento}")

    confirmar = input("Salvar alterações? (s/n): ").strip().lower()

    if confirmar != "s":
        print("Edição cancelada.")
        return

    sucesso, resultado = atualizar_cartao(
        cartao_id,
        nome,
        limite,
        fechamento,
        vencimento
    )

    if sucesso:
        print("Cartão atualizado com sucesso.")
    else:
        mensagens = {
            "nome_invalido": "O nome não pode ficar vazio.",
            "limite_invalido": "O limite deve ser maior que zero.",
            "fechamento_invalido": "O fechamento deve estar entre 1 e 31.",
            "vencimento_invalido": "O vencimento deve estar entre 1 e 31.",
            "cartao_inexistente": "Cartão não encontrado."
        }

        print(mensagens.get(resultado, "Não foi possível atualizar o cartão."))


def alterar_status_cartao_menu():
    print()
    print("========================================")
    print("       ATIVAR / DESATIVAR CARTÃO")
    print("========================================")

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão cadastrado.")
        return

    for cartao in cartoes:
        id_cartao, nome, limite, fechamento, vencimento, ativo = cartao
        status = "ATIVO" if ativo else "INATIVO"

        print(
            f"ID: {id_cartao} | {nome} | "
            f"Status: {status}"
        )

    print()

    try:
        cartao_id = int(
            input("ID do cartão: ").strip()
        )
    except ValueError:
        print("ID inválido.")
        return

    cartao = next(
        (c for c in cartoes if c[0] == cartao_id),
        None
    )

    if cartao is None:
        print("Cartão não encontrado.")
        return

    status_atual = cartao[5]
    acao = "desativar" if status_atual else "ativar"

    confirmar = input(
        f"Deseja {acao} o cartão {cartao[1]}? (s/n): "
    ).strip().lower()

    if confirmar != "s":
        print("Operação cancelada.")
        return

    sucesso, resultado = alterar_status_cartao(
        cartao_id
    )

    if sucesso:
        novo_status = "ATIVO" if resultado else "INATIVO"
        print(f"Cartão atualizado: {novo_status}.")
    else:
        print("Não foi possível alterar o status do cartão.")


def excluir_cartao_menu():
    print()
    print("========================================")
    print("           EXCLUIR CARTÃO")
    print("========================================")

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão cadastrado.")
        return

    for cartao in cartoes:
        id_cartao, nome, limite, fechamento, vencimento, ativo = cartao
        status = "ATIVO" if ativo else "INATIVO"

        print(
            f"ID: {id_cartao} | {nome} | "
            f"Status: {status}"
        )

    print()

    try:
        cartao_id = int(input("ID do cartão: ").strip())
    except ValueError:
        print("ID inválido.")
        return

    cartao = next(
        (c for c in cartoes if c[0] == cartao_id),
        None
    )

    if cartao is None:
        print("Cartão não encontrado.")
        return

    print()
    print(f"Cartão selecionado: {cartao[1]}")
    print("A exclusão só será permitida se não houver")
    print("compras ou faturas vinculadas.")

    confirmar = input(
        "Deseja tentar excluir este cartão? (s/n): "
    ).strip().lower()

    if confirmar != "s":
        print("Operação cancelada.")
        return

    sucesso, resultado = excluir_cartao(cartao_id)

    if sucesso:
        print("Cartão excluído com sucesso.")
    elif resultado == "cartao_inexistente":
        print("Cartão não encontrado.")
    elif resultado == "cartao_com_compras":
        print("Exclusão bloqueada: existem compras vinculadas.")
    elif resultado == "cartao_com_faturas":
        print("Exclusão bloqueada: existem faturas vinculadas.")
    else:
        print("Não foi possível excluir o cartão.")


def mostrar_cartoes():
    print()
    print("========================================")
    print("              CARTÕES")
    print("========================================")
    print()

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão cadastrado.")
        return

    for cartao in cartoes:
        (
            id_cartao,
            nome,
            limite,
            dia_fechamento,
            dia_vencimento,
            ativo
        ) = cartao

        status = "🟢 ATIVO" if ativo else "⏸️ INATIVO"

        limite_utilizado = calcular_limite_utilizado(
            id_cartao
        )

        limite_disponivel = calcular_limite_disponivel(
            id_cartao
        )

        print("----------------------------------------")
        print(f"ID: {id_cartao}")
        print(f"Cartão: {nome}")
        print(f"Limite total:      {formatar_moeda(limite)}")
        print(
            f"Limite utilizado:  "
            f"{formatar_moeda(limite_utilizado)}"
        )
        print(
            f"Limite disponível: "
            f"{formatar_moeda(limite_disponivel)}"
        )
        print(f"Fechamento: dia {dia_fechamento:02d}")
        print(f"Vencimento: dia {dia_vencimento:02d}")
        print(f"Status: {status}")

    print("----------------------------------------")

def mostrar_faturas(cartao_id=None):
    print()
    print("========================================")
    print("              FATURAS")
    print("========================================")
    print()

    faturas = listar_faturas(cartao_id)

    if not faturas:
        print("Nenhuma fatura encontrada.")
        return

    print(
        "ID | CARTÃO"
        "        | FATURA"
        "       | FECHAMENTO"
        " | VENCIMENTO"
        " | TOTAL"
        "       | STATUS"
    )

    print("-" * 105)

    meses = [
        "",
        "JANEIRO",
        "FEVEREIRO",
        "MARÇO",
        "ABRIL",
        "MAIO",
        "JUNHO",
        "JULHO",
        "AGOSTO",
        "SETEMBRO",
        "OUTUBRO",
        "NOVEMBRO",
        "DEZEMBRO"
    ]

    for fatura in faturas:
        (
            id_fatura,
            id_cartao,
            nome_cartao,
            mes,
            ano,
            data_fechamento,
            data_vencimento,
            valor_total,
            paga
        ) = fatura

        status = "🟢 PAGA" if paga else "🔴 ABERTA"

        print(
            f"{id_fatura:<2} | "
            f"{nome_cartao:<8} | "
            f"{meses[mes]:<10} "
            f"{ano} | "
            f"{formatar_data(data_fechamento)}"
            f" | "
            f"{formatar_data(data_vencimento)}"
            f" | "
            f"{formatar_moeda(valor_total):<13} | "
            f"{status}"
        )

    print("-" * 105)

def mostrar_compras_cartao(fatura_id):
    print()
    print("========================================")
    print("          COMPRAS DA FATURA")
    print("========================================")
    print()

    compras = listar_compras_cartao(fatura_id)

    if not compras:
        print("Nenhuma compra encontrada nesta fatura.")
        return

    print(
        "DATA"
        "        | DESCRIÇÃO"
        "                  | CATEGORIA"
        "          | VALOR"
    )

    print("-" * 85)

    total = 0

    for compra in compras:
        (
            id_compra,
            cartao_id,
            fatura_id,
            nome_cartao,
            categoria_id,
            nome_categoria,
            descricao,
            data_compra,
            valor
        ) = compra

        print(
            f"{formatar_data(data_compra)} | "
            f"{descricao:<25} | "
            f"{nome_categoria:<15} | "
            f"{formatar_moeda(valor)}"
        )

        total += valor

    print("-" * 85)
    print(
        f"{'TOTAL':<66}"
        f"{formatar_moeda(total)}"
    )


def mostrar_erro_compra(resultado):
    codigo = resultado[1]

    if codigo == "cartao_invalido":
        print("Cartão inválido ou inativo.")

    elif codigo == "categoria_invalida":
        print("Categoria inválida. Selecione uma categoria de despesa.")

    elif codigo == "quantidade_invalida":
        print("A compra parcelada precisa ter pelo menos 2 parcelas.")

    elif codigo == "valor_invalido":
        print("O valor da compra deve ser maior que zero.")

    elif codigo == "descricao_invalida":
        print("A descrição da compra não pode ficar vazia.")

    elif codigo == "data_invalida":
        print("A data da compra é inválida.")

    elif codigo == "fatura_paga":
        print("Não é possível adicionar parcelas a uma fatura já paga.")

    elif isinstance(resultado[1], tuple) and resultado[1][0] == "limite_insuficiente":
        limite = resultado[1][1]
        print("Limite disponível insuficiente.")
        print(f"Limite disponível: {formatar_moeda(limite)}")

    else:
        print("Não foi possível registrar a compra.")


def nova_compra_cartao():
    print()
    print("========================================")
    print("        NOVA COMPRA NO CARTÃO")
    print("========================================")

    print()
    print("Cartões disponíveis:")

    cartoes = listar_cartoes()

    if not cartoes:
        print("Nenhum cartão ativo encontrado.")
        return

    for cartao in cartoes:
        print(
            f"{cartao[0]} - {cartao[1]} "
            f"(Limite: {formatar_moeda(cartao[2])})"
        )

    print()

    try:
        cartao_id = int(
            input("ID do cartão: ").strip()
        )
    except ValueError:
        print("ID inválido.")
        return

    print()
    print("Categorias de despesa:")

    categorias = listar_categorias("despesa")

    for categoria in categorias:
        print(
            f"{categoria[0]} - {categoria[1]}"
        )

    print()

    try:
        categoria_id = int(
            input("ID da categoria: ").strip()
        )
    except ValueError:
        print("ID inválido.")
        return

    print()

    descricao = input(
        "Descrição da compra: "
    ).strip()

    if not descricao:
        print("A descrição não pode ficar vazia.")
        return

    print()

    data_compra = ler_data()

    print()

    valor = ler_valor()

    print()
    print("Tipo de compra:")
    print("1 - À vista")
    print("2 - Parcelada")

    tipo_compra = input(
        "Escolha uma opção: "
    ).strip()

    if tipo_compra == "1":

        resultado = adicionar_compra_cartao(
            cartao_id,
            categoria_id,
            descricao,
            data_compra,
            valor
        )

        if resultado[0]:
            print()
            print("Compra registrada com sucesso.")
        else:
             print()
             mostrar_erro_compra(resultado)

    elif tipo_compra == "2":

        try:
            quantidade_parcelas = int(
                input("Quantidade de parcelas: ").strip()
            )
        except ValueError:
            print("Quantidade de parcelas inválida.")
            return

        if quantidade_parcelas <= 1:
            print("Para uma compra à vista, escolha a opção 1.")
            return

        valor_parcela = round(
            valor / quantidade_parcelas,
            2
        )

        print()
        print("----------------------------------------")
        print("RESUMO DA COMPRA")
        print("----------------------------------------")
        print(f"Descrição: {descricao}")
        print(f"Valor total: {formatar_moeda(valor)}")
        print(f"Parcelas: {quantidade_parcelas}x")
        print(
            f"Valor aproximado por parcela: "
            f"{formatar_moeda(valor_parcela)}"
        )
        print("----------------------------------------")

        confirmar = input(
            "Confirmar compra? (s/n): "
        ).strip().lower()

        if confirmar != "s":
            print()
            print("Compra cancelada.")
            return

        resultado = adicionar_compra_parcelada_cartao(
            cartao_id,
            categoria_id,
            descricao,
            data_compra,
            valor,
            quantidade_parcelas
        )

        if resultado[0]:
            print()
            print("Compra parcelada registrada com sucesso.")
            print(
                f"{quantidade_parcelas} parcelas "
                f"criadas."
            )
        else:
             print()
             mostrar_erro_compra(resultado)

    else:
        print()
        print("Opção inválida.")

def pagar_fatura_menu():
    print()
    print("========================================")
    print("             PAGAR FATURA")
    print("========================================")

    mostrar_faturas()

    print()

    try:
        id_fatura = int(
            input("ID da fatura: ").strip()
        )
    except ValueError:
        print("ID inválido.")
        return

    print()

    data_pagamento = ler_data()

    print()

    confirmar = input(
        "Confirmar pagamento da fatura? (s/n): "
    ).strip().lower()

    if confirmar != "s":
        print()
        print("Pagamento cancelado.")
        return

    resultado = pagar_fatura(
        id_fatura,
        data_pagamento
    )

    if resultado[0]:
        valor = resultado[1]

        print()
        print("Fatura paga com sucesso.")
        print(f"Valor pago: {formatar_moeda(valor)}")
        print(
            f"Data do pagamento: "
            f"{formatar_data(data_pagamento)}"
        )

    elif resultado[1] == "fatura_inexistente":
        print()
        print("Fatura não encontrada.")

    elif resultado[1] == "fatura_ja_paga":
        print()
        print("Essa fatura já está paga.")

    else:
        print()
        print("Não foi possível pagar a fatura.")

def menu_faturas():
    while True:
        exibir_menu(
            "FATURAS",
            "Consulte, acompanhe e pague suas faturas",
            [
                ("1", "Listar todas"),
                ("2", "Faturas de um cartão"),
                ("3", "Ver compras de uma fatura"),
                ("4", "Pagar fatura"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()


        if opcao == "1":
            mostrar_faturas()

        elif opcao == "2":
            cartoes = listar_cartoes()

            if not cartoes:
                print()
                print("Nenhum cartão cadastrado.")
                continue

            print()
            print("Cartões:")

            for cartao in cartoes:
                (
                    id_cartao,
                    nome,
                    limite,
                    dia_fechamento,
                    dia_vencimento,
                    ativo
                ) = cartao

                print(
                    f"{id_cartao} - {nome}"
                )

            print()

            try:
                cartao_id = int(
                    input("ID do cartão: ").strip()
                )
            except ValueError:
                print("ID inválido.")
                continue

            mostrar_faturas(cartao_id)

        elif opcao == "3":
            try:
                fatura_id = int(
                    input("ID da fatura: ").strip()
                )
            except ValueError:
                print("ID inválido.")
                continue

            mostrar_compras_cartao(fatura_id)

        elif opcao == "4":
              pagar_fatura_menu()    

        elif opcao == "0":
            return

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


def menu_cartoes():
    while True:
        exibir_menu(
            "CARTÕES",
            "Gerencie seus cartões de crédito, compras e faturas",
            [
                ("1", "Novo cartão"),
                ("2", "Listar cartões"),
                ("3", "Faturas"),
                ("4", "Nova compra"),
                ("5", "Editar cartão"),
                ("6", "Ativar / Desativar cartão"),
                ("7", "Excluir cartão"),
                ("0", "Voltar")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            novo_cartao()

        elif opcao == "2":
            mostrar_cartoes()

        elif opcao == "3":
            menu_faturas()

        elif opcao == "4":
            nova_compra_cartao()

        elif opcao == "5":
            editar_cartao()

        elif opcao == "6":
            alterar_status_cartao_menu()

        elif opcao == "7":
            excluir_cartao_menu()

        elif opcao == "0":
            return

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


def menu_principal():
    while True:
        exibir_menu(
            "FINANCEIRO PESSOAL",
            "Sistema de controle financeiro",
            [
                ("1", "Lançamentos"),
                ("2", "Resumos"),
                ("3", "Relatórios"),
                ("4", "Categorias"),
                ("5", "Cartões"),
                ("0", "Sair")
            ]
        )

        opcao = Prompt.ask(
            "[bold cyan]Escolha uma opção[/bold cyan]"
        ).strip()

        if opcao == "1":
            menu_lancamentos()

        elif opcao == "2":
            menu_resumos()

        elif opcao == "3":
            menu_relatorios()

        elif opcao == "4":
            menu_categorias()

        elif opcao == "5":
            menu_cartoes()

        elif opcao == "0":
            console.print(
                "\n[bold green]"
                "Sistema encerrado. Até logo!"
                "[/bold green]"
            )
            break

        else:
            console.print(
                "[bold red]Opção inválida![/bold red] "
                "Escolha uma opção disponível."
            )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    menu_principal()