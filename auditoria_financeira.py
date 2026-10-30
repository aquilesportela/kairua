import sqlite3

con = sqlite3.connect("financeiro.db")
cur = con.cursor()

print("=== 1. INTEGRIDADE DO BANCO ===")
print(cur.execute("PRAGMA integrity_check").fetchone()[0])

print("\n=== 2. FATURAS ===")
for row in cur.execute("""
    SELECT id, cartao_id, mes, ano, data_fechamento,
           data_vencimento, valor_total, paga
    FROM faturas
    ORDER BY ano, mes, cartao_id
"""):
    print(row)

print("\n=== 3. PARCELAS POR FATURA ===")
for row in cur.execute("""
    SELECT f.id, f.mes, f.ano, f.valor_total,
           COUNT(pc.id), COALESCE(SUM(pc.valor), 0)
    FROM faturas f
    LEFT JOIN parcelas_cartao pc ON pc.fatura_id = f.id
    GROUP BY f.id
    ORDER BY f.ano, f.mes, f.cartao_id
"""):
    print(row)

print("\n=== 4. LIMITE DOS CARTOES ===")
for cartao_id, nome, limite in cur.execute(
    "SELECT id, nome, limite FROM cartoes ORDER BY id"
).fetchall():
    print(f"\nCartao: {cartao_id} - {nome} | Limite total: R$ {limite:.2f}")
    try:
        from banco import calcular_limite_utilizado, calcular_limite_disponivel
        utilizado = calcular_limite_utilizado(cartao_id)
        disponivel = calcular_limite_disponivel(cartao_id)
        print(f"Utilizado: R$ {utilizado:.2f} | Disponivel: R$ {disponivel:.2f}")
    except Exception as e:
        print("Erro ao calcular limite:", e)

con.close()
