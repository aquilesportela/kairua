# Auditoria pós-correção da Etapa 3.1B

Data: 2026-11-15. Veredito: **BLOQUEADO PARA COMMIT** por N01.
F01–F04 foram corrigidos nos cenários examinados. Foi comprovada uma falha
adicional de validação de esquema; nenhuma correção de produção foi aplicada.
O relatório anterior permanece intacto como evidência histórica.

## Resultado de F01–F04

| Achado | Resultado | Evidência |
| --- | --- | --- |
| F01 | Corrigido | `migracao_3.py:78`: PK independente positiva e `evento_id NOT NULL UNIQUE`. NULL, omissão, evento legado negativo e evento manual pago são rejeitados nas quatro combinações de FKs/recursividade. PK de reversão 500 vinculada ao evento 17 e PK automática vinculada ao evento 18 preservam a identidade. Duplicação por INSERT/REPLACE rejeitada. |
| F02 | Corrigido | `migracao_3.py:326` e `:386`: todas as unicidades das nove tabelas são examinadas. UNIQUE simples, composto, declarado no DDL, parcial, expressão, collation e ordenação não cobertos são rejeitados antes do DDL. Índices adicionais não únicos são aceitos. Snapshots confirmam preservação de dados/esquema e versões 1/2. Colisões conhecidas por INSERT/UPDATE OR REPLACE continuam bloqueadas com flags ligadas/desligadas. |
| F03 | Corrigido | CHECKs positivos nas entidades novas e guardas AFTER INSERT nas entidades compartilhadas validam o ID definitivo. IDs automáticos/positivos aceitos; zero/negativos e chaves repetidas rejeitados. IDs legados negativos preservados, inclusive -1 referenciado, sem o antigo falso conflito em cadastros normais. |
| F04 | Corrigido | `migracao_3.py:300` e `:408`: conferidos proprietário, nome, origem, unicidade, parcialidade, colunas/ordem, direção e collation via metadados SQLite. Nome certo em tabela errada é rejeitado, assim como variantes incompatíveis. |

Os testes de F01–F04 são `auditoria/test_migracao_3_adversarial.py`; o novo
`auditoria/test_pos_correcao_3.py` acrescenta identidade de reversões, UNIQUE
composto com nome incomum e quatro verificações de sensibilidade.

## N01 — média, comprovada: filtro de gatilhos distingue caixa dos identificadores

Local: `migracao_3.py:381–384`, em `validar_migracao_3()`.

A busca de tabelas usa `COLLATE NOCASE`, mas a consulta de gatilhos usa
`tbl_name IN (...)` com comparação BINARY. SQLite resolve identificadores sem
distinguir maiúsculas/minúsculas; os valores textuais de `sqlite_master` não
seguem automaticamente essa regra. Assim, uma tabela `COMPRAS_CARTAO` pode
passar pela validação das colunas e conservar gatilhos desconhecidos.

Condição: banco legado com a tabela registrada nessa grafia e um gatilho
preexistente associado. Não exige alteração de esquema depois da migração.

Reprodução em fixture temporária da etapa 2:

1. Recriar a tabela de compras com o mesmo DDL/dados, mas nome
   `COMPRAS_CARTAO`; manter o DDL publicado da etapa 2 intacto.
2. Criar `externo AFTER INSERT ON COMPRAS_CARTAO`, cujo corpo insere uma
   despesa de 9 em `lancamentos` com descrição `efeito externo`.
3. Executar o catálogo: resultado observado `[3]`; histórico observado
   `[(1,), (2,), (3,)]`, sem rejeição.
4. Inserir compra comum. Resultado observado em caixa:
   `[('efeito externo', 9.0, None)]` para descrição, valor e operação híbrida.
   O efeito ocorreu também com FKs e gatilhos recursivos desligados.

Impacto: a pré-condição aceita comportamento financeiro externo não auditado,
contrariando a garantia documentada de rejeitar gatilhos desconhecidos.
A migração não cria esse gatilho nem demonstrou bypass dos limites dos eventos
híbridos; ela deixa de recusar um esquema que deveria considerar incompatível.

Teste permanente: `PosCorrecao.test_n01_rejeita_gatilho_desconhecido_com_tabela_em_maiusculas`.
Ele exige rejeição segura e **falha** com `ValueError not raised`; sucesso
futuro exigirá o bloqueio. Não é um teste que passa celebrando o defeito.

Correção mínima recomendada: comparar `tbl_name` segundo as regras de nomes
SQLite, por exemplo `tbl_name COLLATE NOCASE IN (...)`, com regressões de caixa
mista para todas as tabelas protegidas. Alternativamente rejeitar explicitamente
grafias não canônicas antes de qualquer DDL. Preservar rollback e dados.

## Segurança, gatilhos e compatibilidade

Revisadas as definições geradas dos 45 gatilhos: operações (3), eventos (4),
caixa (4), liquidações (4), estornos (3), reversões (3), reclassificações (4),
origens legadas (16) e categorias (4). Os oito AFTER INSERT adicionais tratam
IDs definitivos nas entidades compartilhadas; não produzem ajustes monetários.
O inventário dinâmico confirma nomes/instalação, mas não é cobertura exaustiva
de todos os caminhos SQL de cada gatilho.

Os controles exercitam imutabilidade, categorias, eventos revertidos, liquidação
parcial/integral/excessiva, estornos acumulados, reclassificações e REPLACE,
inclusive com FKs/recursive_triggers 0/1. A inicialização completa, edição e
exclusão legadas elegíveis continuam passando. As migrações 1/2 continuam
compatíveis; reexecução da 3 não modifica dados; falhas em diversos pontos
desfazem DDL e registro da versão 3, preservando versões anteriores.

Autorizador (`banco.py:140`, `:228`): a exceção `quick_check` exige versão/nome,
texto exato de ALTER autorizado, tabela, schema main e origem nula. PRAGMAs
explícitos, controles transacionais, ATTACH/DETACH e adulteração do histórico
continuam rejeitados. Não foi encontrado novo bypass dessa exceção. A falha
N01 é da pré-condição, não uma liberação de SQL pelo autorizador.

## Qualidade das regressões e limites

Quatro mutantes locais em memória removeram separadamente as proteções de
F01–F04. Todos foram detectados pelos contratos de teste. Isso demonstra
sensibilidade às proteções removidas, não equivale a testar um checkout exato
da implementação antiga não versionada. Para F01 a verificação estrutural é
essencial: o fixture negativo atual é legado sem origem manual e a nova
proteção de F03 também ajuda a impedir a reprodução econômica antiga.

Permanece a limitação explícita de IDs automáticos em tabela histórica contendo
somente IDs negativos: se SQLite atribuir zero/negativo, a nova inserção híbrida
é rejeitada; o serviço deverá escolher ID positivo quando necessário.
Permanecem L01 (completude e proibição de COMMIT com operações abertas dependem
do serviço futuro) e L02 (REAL não representa todos os centavos em grandes
valores). Inteiros são a fonte monetária; overflow de SUM falha explicitamente.
Não se adicionou integração financeira nem se tomou o teste simulado de serviço
como prova de uma implementação ainda inexistente.

## Execução e preservação

Todos os processos de teste receberam `KAIRUA_DB_PATH` temporário antes dos
imports; fixtures usam seus próprios diretórios temporários. Nenhum acesso ao
`financeiro.db` real, commit ou push. Produção, testes preexistentes, AGENTS.md
e tests/test_parcelamentos.py permanecem byte a byte iguais aos hashes iniciais.
Somente este relatório e `auditoria/test_pos_correcao_3.py` foram criados.

Resultados finais: adversariais existentes 18/18; adicionais 6/7, com uma falha
comprovando N01. As quatro verificações de sensibilidade passaram. O primeiro
rascunho do teste composto tinha uma coluna de fixture incorreta; foi corrigido
somente no teste e reexecutado. A execução final não apresenta esse erro.

A suíte completa `python -m unittest discover -s tests -v` foi concluída:
141 testes, 139 aprovados, dois ignorados e nenhuma falha/erro. Os dois skips
são testes de links simbólicos por ausência de privilégio Windows (1314).
Os 18 adversariais anteriores já integram esses 141; os sete adicionais são
executados separadamente. Não somar as execuções repetidas como testes distintos.

`git diff --check`: código de saída 0. Há avisos preexistentes de conversão
LF para CRLF pelo Git; nenhum ajuste de configuração foi realizado. Os arquivos
novos estão em UTF-8/LF; produção e demais arquivos examinados não foram
reescritos. O estado do Git mantém as alterações locais anteriores, acrescido
somente dos dois artefatos desta auditoria dentro de `auditoria/`.

## Verificação da correção pontual de N01

Esta seção registra a execução posterior à auditoria acima; as reproduções e o
veredito históricos não foram removidos. N01 foi corrigido acrescentando
`COLLATE NOCASE` ao operando `sqlite_master.tbl_name` da consulta de gatilhos
em `migracao_3.py`. Não foram alterados DDL, gatilhos financeiros, executor,
catálogos das versões 1/2 nem as proteções F01–F04.

Antes da alteração, o teste original foi reexecutado e falhou com
`ValueError not raised`. Após a alteração, a regressão exige rejeição por
`Gatilhos legados desconhecidos` e compara snapshots completos de esquema,
dados e histórico das versões 1/2. Um spy do autorizador confirma que nenhuma
instrução do DDL da versão 3 é iniciada.

Cobertura ampliada: compras_cartao, lancamentos, categorias, parcelamentos,
recorrencias, parcelamento_parcelas e recorrencia_ocorrencias, cada qual com
nome minúsculo, maiúsculo, title case e alternância de caixa (28 cenários).
Quatro cenários legítimos de compras sem gatilhos extras, incluindo
`COMPRAS_CARTAO`, `Compras_Cartao` e `cOmPrAs_cArTaO`, aplicam a migração e a
reexecutam sem alterações, preservando as compras existentes.

Auditoria limitada das demais comparações: buscas de tabela e índice já usam
NOCASE; identidade dos índices usa metadados estruturais; nomes de novos
objetos são comparados com casefold. DDL publicado, nomes de colunas, chaves e
proprietários esperados têm comparações conservadoras que podem rejeitar
grafias não canônicas. Não se identificou outro bypass de aceitação equivalente
a N01. Essas políticas não foram ampliadas ou refatoradas nesta correção.

Validação após a correção: regressões N01 2/2; módulo adicional completo 8/8
(inclui N01 e sensibilidade F01–F04); adversariais anteriores 18/18; migração 3
23/23; suíte completa 141 testes, 139 aprovados, dois ignorados por privilégios
de links simbólicos no Windows, nenhuma falha/erro. Todas as execuções usaram
KAIRUA_DB_PATH temporário definido antes dos imports. `git diff --check`
terminou com código 0; permanecem os avisos preexistentes LF→CRLF do Git.

Os três arquivos alterados nesta correção estão em UTF-8/LF. Comparação de
hashes confirmou a preservação de AGENTS.md, tests/test_parcelamentos.py,
banco.py e dos módulos preexistentes de testes do esquema/migração. Comparação
com o hash inicial de migracao_3.py, retirando apenas o novo COLLATE NOCASE,
confirma que essa foi a única alteração de produção. Nenhum acesso ao banco
real, commit ou push. A correção aguarda autorização e não inicia a Etapa 3.2.
