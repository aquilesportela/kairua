# Infraestrutura SQLite

`banco.abrir_conexao()` resolve `KAIRUA_DB_PATH` a cada chamada e preserva
as opções padrão de conexão. O chamador continua responsável por transações
e fechamento. Não há migração automática ao abrir conexões ou importar `banco`.

## Migrações versionadas

`banco.aplicar_migracoes(destino)` exige um caminho explícito e executa o
catálogo `MIGRACOES`, ordenado por
versões inteiras positivas únicas, e retorna as versões aplicadas na chamada.
Cada versão e seu registro em `esquema_migracoes` usam a mesma transação
`BEGIN IMMEDIATE`. Uma falha desfaz DDL, DML e o registro da versão corrente;
versões anteriores já confirmadas permanecem. A reexecução pula versões
registradas. O histórico deve formar um prefixo exato do catálogo, incluindo
nomes: lacunas, versões desconhecidas e nomes divergentes são rejeitados antes
de executar uma versão pendente.

O executor não usa `KAIRUA_DB_PATH` como destino implícito. A variável continua
orientando normalmente `abrir_conexao()` e as operações financeiras. O destino
das migrações é validado antes de qualquer conexão: nomes `financeiro.db`
(inclusive variações de caixa), links simbólicos, reparse points/junctions,
arquivos com múltiplos hardlinks e caminhos ambíguos são rejeitados. Não se
consulta a existência ou identidade do banco real nem se segue um link para
compará-lo com ele. Essa política rejeita também aliases de arquivos seguros.
URIs, caminhos UNC, streams, nomes com `~` (incluindo aliases 8.3), espaços ou
pontos finais são rejeitados. O diretório pai deve existir e ser acessível;
falhas na verificação impedem a migração. Não há autorização para migrar a base
real. Use uma cópia em diretório local confiável, sem alterações concorrentes
do sistema de arquivos: a validação de caminho não oferece proteção contra
um agente que substitua arquivos/diretórios entre validação e abertura.

A versão 1 cria somente o controle de versões, pelo bootstrap transacional
do executor; seu catálogo não precisa repetir esse DDL. **Não é um baseline do esquema
financeiro.** As funções antigas de criação e migração continuam independentes,
sem mudanças e sem serem marcadas como aplicadas. Em banco novo, a sequência
de inicialização existente ainda cria as tabelas financeiras; o executor pode
ser chamado explicitamente antes ou depois dela. Em banco legado, a versão 1
não verifica nem transforma tabelas financeiras e não normaliza dados.

Novas versões devem ser aditivas e imutáveis após publicação. Cada instrução
do catálogo deve conter um único comando DDL/DML transacional. Não usar
`executescript`, controle explícito de transação, `VACUUM`, alterações de
PRAGMA ou efeitos externos nas migrações. Durante a execução do SQL do catálogo,
um autorizador nativo do SQLite bloqueia transações, savepoints, ATTACH, DETACH,
PRAGMAs e alterações diretas do controle de versões. O próprio SQLite interpreta
comentários e diferenças de caixa, sem parser textual próprio. O autorizador
é removido em `finally`, antes do registro de versão, commit ou rollback.
Essa proteção cobre SQL executado nessa conexão; não é um sandbox para código
Python arbitrário, extensões ou efeitos externos. Migrações futuras que dependam do
legado devem verificar expressamente suas pré-condições estruturais e de dados.
O controle atual compara versão e nome; não calcula checksum do SQL.

Esta etapa não conecta o executor à inicialização de `app.py`. A execução
de migrações e a adoção de uma base candidata exigem planejamento próprio;
o arquivo real `financeiro.db` deve permanecer intocado conforme `AGENTS.md`.

## Chaves estrangeiras: habilitação adiada

Não se habilita `PRAGMA foreign_keys = ON` nesta etapa. Antes disso:

- Investigar vínculos órfãos em uma base sintética ou cópia autorizada.
- Revisar exclusões de lançamentos vinculados a ocorrências e parcelas:
  operações hoje aceitas podem passar a falhar por integridade referencial.
- Revisar a ordem das operações de criação, exclusão e migração.
- Considerar que `categoria_id`, `recorrencia_id` e `parcelamento_id`
  adicionados a `lancamentos` pelas migrações antigas não declaram FKs;
  habilitar o PRAGMA não cria essas restrições.
- Testar todas as conexões e os contratos de erro antes de ativar a opção.

## Testes

Usar exclusivamente bancos temporários com `KAIRUA_DB_PATH`. A suíte não deve
importar `app.py`, cuja inicialização executa operações no banco. Para defesa
adicional, definir a variável também no processo que executa a descoberta,
apontando para outro banco dentro de diretório temporário.
