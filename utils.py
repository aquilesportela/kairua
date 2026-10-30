from datetime import datetime


def ler_data():
    while True:
        data = input("Data (DDMMAAAA): ").strip()

        if len(data) == 8 and data.isdigit():
            data_formatada = (
                f"{data[:2]}/"
                f"{data[2:4]}/"
                f"{data[4:]}"
            )

            try:
                data_objeto = datetime.strptime(
                    data_formatada,
                    "%d/%m/%Y"
                )

                return data_objeto.strftime("%Y-%m-%d")

            except ValueError:
                print("Data inválida.")

        else:
            print("Digite a data com 8 números.")
            print("Exemplo: 26092026")


def formatar_data(data):
    data_objeto = datetime.strptime(
        data,
        "%Y-%m-%d"
    )

    return data_objeto.strftime("%d/%m/%Y")


def ler_tipo():
    while True:
        tipo = input(
            "Tipo (receita/despesa): "
        ).strip().lower()

        if tipo in ["receita", "despesa"]:
            return tipo

        print(
            "Tipo inválido. "
            "Digite receita ou despesa."
        )


def ler_valor():
    while True:
        entrada = input("Valor: ").strip()

        try:
            if "," in entrada:
                entrada = entrada.replace(".", "")
                entrada = entrada.replace(",", ".")

            valor = float(entrada)

            if valor <= 0:
                print("O valor deve ser maior que zero.")
                continue

            return valor

        except ValueError:
            print(
                "Valor inválido. "
                "Exemplo: 150,50"
            )


def formatar_moeda(valor):
    valor_formatado = f"{valor:,.2f}"

    valor_formatado = (
        valor_formatado
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )

    return f"R$ {valor_formatado}"