from datetime import datetime
import unicodedata
import json
from pathlib import Path


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

def ordenar_registros(
    registros,
    campo,
    indice_campos,
    direcao="asc",
    tipos_campos=None
):
    """
    Ordena registros em memória sem modificar a lista original.
    """

    if campo not in indice_campos:
        raise ValueError(
            f"Campo de ordenação inválido: {campo}"
        )

    if direcao not in ("asc", "desc"):
        raise ValueError(
            "Direção deve ser 'asc' ou 'desc'."
        )

    tipos_campos = tipos_campos or {}
    tipo_campo = tipos_campos.get(campo, "texto")
    indice = indice_campos[campo]

    def normalizar_texto(valor):
        texto = str(valor).casefold()
        texto = unicodedata.normalize("NFKD", texto)

        return "".join(
            caractere
            for caractere in texto
            if not unicodedata.combining(caractere)
        )

   
    def chave_ordenacao(registro):
        valor = registro[indice]

        if valor is None:
            return (1, "" if tipo_campo == "texto" else 0)

        if tipo_campo == "numero":
            return (0, float(valor))

        if tipo_campo == "data":
            if isinstance(valor, datetime):
                return (0, valor)

            return (
                0,
                datetime.strptime(
                    str(valor),
                    "%Y-%m-%d"
                )
            )

        return (0, normalizar_texto(valor))

    registros_validos = [
        registro
        for registro in registros
        if registro[indice] is not None
    ]

    registros_vazios = [
        registro
        for registro in registros
        if registro[indice] is None
    ]

    registros_ordenados = sorted(
        registros_validos,
        key=chave_ordenacao,
        reverse=(direcao == "desc")
    )

    return registros_ordenados + registros_vazios


ARQUIVO_PREFERENCIAS = (
    Path(__file__).resolve().parent / "preferencias.json"
)


def carregar_preferencias():
    if not ARQUIVO_PREFERENCIAS.exists():
        return {}

    try:
        with ARQUIVO_PREFERENCIAS.open(
            "r", encoding="utf-8"
        ) as arquivo:
            dados = json.load(arquivo)

        return dados if isinstance(dados, dict) else {}

    except (OSError, json.JSONDecodeError):
        return {}


def carregar_preferencia_ordenacao(
    modulo,
    campo_padrao,
    direcao_padrao="desc"
):
    preferencias = carregar_preferencias()

    ordenacao = preferencias.get(modulo, {})

    if not isinstance(ordenacao, dict):
        return campo_padrao, direcao_padrao

    campo = ordenacao.get("campo", campo_padrao)
    direcao = ordenacao.get("direcao", direcao_padrao)

    if not isinstance(campo, str):
        campo = campo_padrao

    if direcao not in ("asc", "desc"):
        direcao = direcao_padrao

    return campo, direcao


def salvar_preferencia_ordenacao(modulo, campo, direcao):
    if direcao not in ("asc", "desc"):
        raise ValueError("Direção de ordenação inválida.")

    preferencias = carregar_preferencias()

    preferencias[modulo] = {
        "campo": campo,
        "direcao": direcao
    }

    arquivo_temporario = ARQUIVO_PREFERENCIAS.with_suffix(
        ".json.tmp"
    )

    try:
        with arquivo_temporario.open(
            "w", encoding="utf-8"
        ) as arquivo:
            json.dump(
                preferencias,
                arquivo,
                ensure_ascii=False,
                indent=4
            )

        arquivo_temporario.replace(ARQUIVO_PREFERENCIAS)

    finally:
        arquivo_temporario.unlink(missing_ok=True)
