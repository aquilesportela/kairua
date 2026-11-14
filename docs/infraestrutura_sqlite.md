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


## Etapa 2: esquema financeiro híbrido (migração 2)

A versão `2`, `esquema_financeiro_hibrido`, cria exclusivamente as duas tabelas
abaixo e seus índices. Não insere eventos, não converte valores, não modifica
registros nem tabelas legadas e não é chamada automaticamente pelo aplicativo.
A versão 1 permanece sem alterações. Um banco vazio ou incompleto é rejeitado
pela pré-condição da versão 2, sem criar automaticamente o esquema legado.

### Dependências e rejeição

As dependências são extraídas do próprio DDL da migração. Na mesma conexão e
dentro da transação da versão 2, o SQLite interpreta as definições CREATE TABLE
em tabelas TEMP e fornece as FKs por `pragma_foreign_key_list`. Referências
internas entre tabelas novas são separadas das referências legadas. O contrato
dessa extração é o formato `CREATE TABLE nome (...)` usado pelo catálogo;
não se trata de um parser SQL genérico nem de execução de todo o catálogo.

As dependências atuais são `categorias(id)`, `compras_cartao(id)`,
`parcelamentos(id)`, `parcelamento_parcelas(id)`,
`recorrencia_ocorrencias(id)` e `lancamentos(id)`. Todas devem existir como
tabelas no schema main, com as colunas referenciadas. Uma tabela auxiliar vazia
sonda cada chave com `PRAGMA foreign_key_check`: o próprio SQLite valida a
adequação da PK ou UNIQUE, incluindo cardinalidade, índices parciais,
expressões e collations. A sondagem não insere ou corrige registros legados
e funciona mesmo com `foreign_keys` desabilitado.

Todas as estruturas de sondagem são desfeitas por savepoint antes da criação
das tabelas definitivas. Falhas geram `ValueError` com o prefixo
`Esquema legado incompativel para migracao 2`, seguido da dependência ou erro
SQLite. O executor desfaz a versão 2: não permanecem tabelas novas, sondagens
ou registro da versão 2. A versão 1 anteriormente confirmada e os dados legados
permanecem. Após corrigir as dependências em uma base candidata, a reexecução
aplica somente a versão pendente. A pré-condição é um callback confiável,
registrado por versão e nome; o autorizador do SQL das migrações permanece
inalterado. Versões já aplicadas não são revalidadas nem reexecutadas.

`data_competencia` aceita datas de calendário válidas no formato AAAA-MM-DD,
com anos 0001 a 9999. Situação pendente exige data nula; confirmada ou estimada
exige data válida. Valores são centavos positivos armazenados como INTEGER:
o CHECK de `typeof` impede valores fracionários/texto não numérico; a afinidade
SQLite ainda converte entradas numéricas exatas como `100.0` ou `'100'` em
inteiros. Validar os tipos de entrada no serviço será responsabilidade futura.

Origens opcionais são exclusivas por evento e únicas quando preenchidas:
compra de cartão, parcelamento integral (aquisição única), parcela comum
(serviço sucessivo), ocorrência recorrente ou lançamento legado. Um evento
manual novo pode ter todas as referências nulas, identificado por chave própria.
O esquema apenas permite esses vínculos: não confirma ocorrências econômicas e
não reclassifica lançamentos antigos automaticamente. Ainda será necessário
validar no serviço se o mesmo parcelamento representa aquisição ou serviços;
o CHECK por linha não impede criar eventos distintos para o contrato e suas
parcelas. A chave de origem é única e não vazia, sem normalização automática.

Todas as FKs novas referenciam PKs existentes, com `ON DELETE RESTRICT`.
Não foi necessário reconstruir tabelas legadas. As FKs só são efetivas nas
conexões que habilitarem `PRAGMA foreign_keys = ON`; o padrão da aplicação
permanece inalterado. Os testes habilitam a opção antes de iniciar transações
em suas conexões específicas de integridade referencial. A validação estrutural
não substitui essa opção nem verifica todas as relações e registros legados.
Antes da integração será necessário definir conexões apropriadas e
políticas de edição/exclusão que preservem os vínculos históricos.

A unicidade `(evento_id, lancamento_id)` admite vários pagamentos para um
evento e vários eventos para um pagamento. Ela também indexa consultas por
evento; o índice explícito por lançamento cobre a direção inversa. As FKs de
origem possuem os índices únicos gerados por suas restrições. Os outros índices
cobrem competência e categoria/competência.

Limites agregados (soma liquidada por evento, soma conciliada por lançamento),
compatibilidade de categoria/tipo, estornos e confirmação econômica não são
impostos nesta etapa. Exigem validação transacional futura; não há gatilhos que
alterem pagamentos ou relatórios. A migração usa CREATE sem IF NOT EXISTS para
as estruturas novas: um nome já ocupado provoca erro e rollback da versão 2,
sem aceitar silenciosamente um esquema incompatível.

### SQL da migração 2

```sql
CREATE TABLE eventos_financeiros (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
    descricao TEXT NOT NULL CHECK (length(trim(descricao)) > 0),
    categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    valor_centavos INTEGER NOT NULL
        CHECK (typeof(valor_centavos) = 'integer' AND valor_centavos > 0),
    data_competencia TEXT,
    situacao_competencia TEXT NOT NULL
        CHECK (situacao_competencia IN ('confirmada', 'estimada', 'pendente')),
    chave_origem TEXT NOT NULL UNIQUE CHECK (length(trim(chave_origem)) > 0),
    compra_cartao_id INTEGER UNIQUE REFERENCES compras_cartao(id) ON DELETE RESTRICT,
    parcelamento_id INTEGER UNIQUE REFERENCES parcelamentos(id) ON DELETE RESTRICT,
    parcela_comum_id INTEGER UNIQUE REFERENCES parcelamento_parcelas(id) ON DELETE RESTRICT,
    ocorrencia_id INTEGER UNIQUE REFERENCES recorrencia_ocorrencias(id) ON DELETE RESTRICT,
    lancamento_legado_id INTEGER UNIQUE REFERENCES lancamentos(id) ON DELETE RESTRICT,
    CHECK (
        (compra_cartao_id IS NOT NULL) + (parcelamento_id IS NOT NULL)
        + (parcela_comum_id IS NOT NULL) + (ocorrencia_id IS NOT NULL)
        + (lancamento_legado_id IS NOT NULL) <= 1
    ),
    CHECK (
        (situacao_competencia = 'pendente' AND data_competencia IS NULL)
        OR
        (situacao_competencia IN ('confirmada', 'estimada')
         AND data_competencia IS NOT NULL
         AND length(data_competencia) = 10
         AND data_competencia GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
         AND substr(data_competencia, 1, 4) >= '0001'
         AND date(data_competencia, '+0 days') IS NOT NULL
         AND date(data_competencia, '+0 days') = data_competencia)
    )
);

CREATE TABLE liquidacoes_eventos (
    id INTEGER PRIMARY KEY,
    evento_id INTEGER NOT NULL REFERENCES eventos_financeiros(id) ON DELETE RESTRICT,
    lancamento_id INTEGER NOT NULL REFERENCES lancamentos(id) ON DELETE RESTRICT,
    valor_centavos INTEGER NOT NULL
        CHECK (typeof(valor_centavos) = 'integer' AND valor_centavos > 0),
    UNIQUE (evento_id, lancamento_id)
);

CREATE INDEX idx_eventos_competencia ON eventos_financeiros(data_competencia);

CREATE INDEX idx_eventos_categoria_competencia ON eventos_financeiros(categoria_id, data_competencia);

CREATE INDEX idx_liquidacoes_lancamento ON liquidacoes_eventos(lancamento_id);
```
