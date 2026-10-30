import sqlite3
import calendar
from datetime import datetime

conexao = sqlite3.connect("financeiro.db")
cursor = conexao.cursor()

try:
    cursor.execute("BEGIN")

    faturas = cursor.execute("""
        SELECT f.id, f.data_fechamento, f.data_vencimento,
               c.dia_vencimento
        FROM faturas f
        JOIN cartoes c ON c.id = f.cartao_id
        WHERE f.paga = 0
        ORDER BY f.ano, f.mes
    """).fetchall()

    alteradas = 0

    for fatura_id, fechamento, vencimento_antigo, dia_vencimento in faturas:
        data = datetime.strptime(fechamento, "%Y-%m-%d")
        ano = data.year
        mes = data.month + 1

        if mes == 13:
            mes = 1
            ano += 1

        dia = min(dia_vencimento, calendar.monthrange(ano, mes)[1])
        novo_vencimento = f"{ano:04d}-{mes:02d}-{dia:02d}"

        if vencimento_antigo != novo_vencimento:
            cursor.execute(
                "UPDATE faturas SET data_vencimento = ? WHERE id = ? AND paga = 0",
                (novo_vencimento, fatura_id)
            )
            print(
                f"Fatura {fatura_id}: {vencimento_antigo} -> {novo_vencimento}"
            )
            alteradas += 1

    conexao.commit()
    print(f"\nCorreção concluída. Faturas atualizadas: {alteradas}")

except Exception:
    conexao.rollback()
    raise

finally:
    conexao.close()
