import sqlite3

con = sqlite3.connect("financeiro.db")
cur = con.cursor()

print("=== PARCELAS POR COMPRA ===")
for row in cur.execute("""
    SELECT
        cc.id,
        cc.descricao,
        cc.valor,
        COUNT(pc.id),
        COALESCE(SUM(pc.valor), 0),
        COALESCE(SUM(
            CASE WHEN f.paga = 0 THEN pc.valor ELSE 0 END
        ), 0)
    FROM compras_cartao cc
    JOIN parcelas_cartao pc ON pc.compra_id = cc.id
    JOIN faturas f ON f.id = pc.fatura_id
    GROUP BY cc.id, cc.descricao, cc.valor
    ORDER BY cc.id
"""):
    print(row)

print("\n=== COMPRAS PARCELADAS E FATURA ORIGINAL ===")
for row in cur.execute("""
    SELECT
        cc.id,
        cc.descricao,
        cc.valor,
        f.mes,
        f.ano,
        f.paga
    FROM compras_cartao cc
    JOIN faturas f ON f.id = cc.fatura_id
    WHERE EXISTS (
        SELECT 1
        FROM parcelas_cartao pc
        WHERE pc.compra_id = cc.id
    )
    ORDER BY cc.id
"""):
    print(row)

con.close()
