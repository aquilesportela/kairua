import sqlite3

con = sqlite3.connect("financeiro.db")
cur = con.cursor()

print("=== COMPOSICAO DAS FATURAS ===")

faturas = cur.execute("""
    SELECT id, cartao_id, mes, ano, valor_total, paga
    FROM faturas
    ORDER BY ano, mes, cartao_id
""").fetchall()

for fid, cartao, mes, ano, total, paga in faturas:
    compras_avista = cur.execute("""
        SELECT COALESCE(SUM(c.valor), 0)
        FROM compras_cartao c
        WHERE c.fatura_id = ?
          AND NOT EXISTS (
              SELECT 1
              FROM parcelas_cartao p
              WHERE p.compra_id = c.id
          )
    """, (fid,)).fetchone()[0]

    parcelas = cur.execute("""
        SELECT COALESCE(SUM(valor), 0)
        FROM parcelas_cartao
        WHERE fatura_id = ?
    """, (fid,)).fetchone()[0]

    esperado = compras_avista + parcelas
    diferenca = round(total - esperado, 2)

    print(
        f"Fatura {fid} | {mes:02}/{ano} | "
        f"Total: R$ {total:.2f} | "
        f"A vista: R$ {compras_avista:.2f} | "
        f"Parcelas: R$ {parcelas:.2f} | "
        f"Esperado: R$ {esperado:.2f} | "
        f"Diferenca: R$ {diferenca:.2f} | "
        f"Paga: {paga}"
    )

con.close()
