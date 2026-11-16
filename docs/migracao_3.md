# Etapa 3.1B — contrato estrutural das operações híbridas

A migração 3 (`contrato_operacoes_hibridas`) é exclusivamente aditiva.
O catálogo SQL completo é `migracao_3.SQL_MIGRACAO_3`; cada item é uma única
instrução, incluindo definições completas de gatilhos com `BEGIN ... END`.
As funções auxiliares desse módulo apenas constroem SQL: não são serviços
financeiros e não abrem conexões. A migração não é executada na inicialização
do aplicativo. Não foram alteradas as versões 1 e 2.

## Estruturas e preservação

- `operacoes_hibridas`: chave única, requisição canônica, tipo e transição única
  de `aberta` para `concluida`. A operação identifica uma requisição e pode
  possuir vários efeitos; os índices de operação não são únicos.
- `lancamentos`: referências anuláveis à operação e centavos inteiros assinados.
  Os dois campos permanecem nulos para o histórico e para o cadastro legado.
  O menor inteiro int64 é excluído para manter a negação de estornos inteira.
- `eventos_financeiros`: operação, vencimento e origem explícita anuláveis para
  os registros existentes. Novos eventos nesta etapa precisam ser manuais,
  confirmados e com vencimento próprio.
- `estornos_liquidacoes`: contramovimento vinculado à liquidação original,
  natureza obrigatória (`devolucao_real` ou `correcao_registro`) e motivo.
- `reversoes_eventos`: PK `id` independente e referência obrigatória e única
  `evento_id`. Não há atribuição automática para a FK. Uma reversão integral
  por evento, sem novo caixa e somente após a liquidação líquida chegar a zero.
- `reclassificacoes_eventos`: histórico sequencial de categorias compatíveis,
  sem atualizar o evento original.
- `eventos_classificacao_atual`: categoria corrente calculada pela última
  reclassificação. A categoria inicial e o caixa registrado permanecem intactos.

As visões internas `_hibrido_liquidacoes` e `_hibrido_categorias_em_uso`
centralizam os saldos líquidos e as referências usadas pelos gatilhos.
Nenhum gatilho insere, atualiza ou exclui valores financeiros automaticamente.

## Integridade e gatilhos

Os gatilhos funcionam independentemente de `foreign_keys` e
`recursive_triggers`; as FKs também são declaradas com `ON DELETE RESTRICT`.
O serviço futuro deverá habilitar FKs antes da transação, sem mudar globalmente
as opções das conexões legadas.

| Família | Proteção |
| --- | --- |
| `tr_operacoes_bi/bu/bd` | Colisões de chave/ID, estado inicial, fechamento único e imutabilidade. |
| `tr_eventos_bi/bu/bd` | Origem manual, confirmação, categoria e operação compatíveis; evento imutável. |
| `tr_lancamentos_bi/bu/bd` | Projeção monetária, datas, sinal e tipo da operação; caixa vinculado protegido. |
| `tr_liquidacoes_bi/bu/bd` | Referências válidas, tipos iguais, saldo aberto e limite original do caixa; histórico imutável. |
| `tr_estornos_bi/bu/bd` | Referências, natureza, datas, classificação original e limite estornável; histórico imutável. |
| `tr_reversoes_bi/bu/bd` | Reversão única, categoria corrente, operação aberta e liquidação líquida zero; histórico imutável. |
| `tr_reclassificacoes_bi/ai/bu/bd` | Categoria anterior correta, compatibilidade de tipo e sequência crescente; histórico imutável. |
| `tr_compras_origem_*`, `tr_parcelamentos_origem_*`, `tr_parcelas_origem_*`, `tr_ocorrencias_origem_*` | Protegem IDs referenciados e substituições por chaves únicas, inclusive compostas. |
| `tr_categorias_bi/bu/bd` | Categorias usadas não podem mudar de tipo/ID nem ser removidas/substituídas. |

Colisões de `INSERT OR REPLACE` são interceptadas antes da exclusão implícita,
incluindo as chaves compostas de parcelas e ocorrências. Não se depende de
gatilhos recursivos para preservar a linha original.

Após F01–F04, são 45 gatilhos. As validações adicionais `AFTER INSERT`
verificam o identificador efetivamente atribuído, sem presumir que `NEW.id`
em `BEFORE INSERT` seja o identificador final. Novos registros híbridos exigem
IDs inteiros positivos; operações, estornos, reversões e reclassificações
também possuem CHECK de positividade. IDs nulos/omitidos das PKs solicitam
atribuição automática; `evento_id` de reversão nunca é uma PK autoatribuída.

IDs negativos ou zero preexistentes não são convertidos ou removidos. Os
caminhos legados mantêm seu domínio de IDs. Para PKs legadas com ID protegido
`-1`, a proteção posterior impede REPLACE explícito sem confundir uma inserção
automática com aquela linha. Atualizações usam o ID real, não esse tratamento
de identificador provisório. Em uma tabela de eventos com somente IDs negativos,
o alocador SQLite pode gerar zero ou outro ID não positivo; o fluxo híbrido
rejeita esse ID por domínio, sem reescrever o histórico. Nesse caso, o futuro
serviço deve fornecer um ID positivo sob a transação de escrita. A atribuição
automática volta ao domínio positivo após existir um ID positivo.

O único `RAISE(IGNORE)` reconhece uma categoria utilizada exatamente idêntica
em nome, tipo e ID (ou inserção sem ID explícito). É um no-op necessário para
`criar_categorias()` continuar usando `INSERT OR IGNORE`. Qualquer diferença
na colisão protegida gera `ABORT`; a rejeição não é escondida. Serviços novos
deverão conferir o resultado da inserção.

## Dinheiro e datas

Centavos são a fonte monetária. O valor REAL deve ser exatamente a projeção
`CAST(valor_centavos AS REAL) / 100.0`, sem tolerância ou arredondamento usado
para aceitar divergências. Essa igualdade não torna REAL decimal exato.
O código dos testes gera o espelho por SQL a partir do inteiro, sem usar float
como origem do valor financeiro.

O pagamento/recebimento original é positivo; o estorno é negativo e conserva
tipo econômico, categoria e texto de categoria originais. Devolução real usa
a data efetiva, não anterior ao caixa original. Correção de registro usa a
mesma data do registro incorreto. Renomear uma categoria não impede estorno
do caixa anterior, pois sua classificação registrada é preservada.

O saldo líquido de uma liquidação é seu valor original mais os contramovimentos
negativos associados. O evento não admite excesso de liquidação líquida;
o lançamento original não pode ser realocado após um estorno.
As comparações usam diferenças de inteiros, evitando somar o candidato antes
de conferir o limite. Agregações que excederem int64 falham explicitamente
com `integer overflow`; não há fallback para REAL.

## Pré-condição e executor

Antes do DDL, na mesma conexão e transação da versão 3, valida-se:

- DDL publicado das duas tabelas da etapa 2, conservadoramente, incluindo CHECKs
  e FKs. Formas equivalentes com SQL diferente também podem ser rejeitadas.
- Colunas, tipos, PKs, NOT NULL essenciais, unicidades legadas e composição
  dos índices necessários.
- Todas as unicidades das nove tabelas protegidas, sejam índices explícitos
  ou restrições UNIQUE/PK. Apenas chaves simples globais já cobertas pelos
  gatilhos são aceitas, em ordem conhecida, ASC e BINARY. Expressões, índices
  únicos parciais, collations/ordens não previstas e chaves adicionais são
  rejeitados conservadoramente antes do DDL. Índices não únicos adicionais
  são aceitos, inclusive parciais ou de expressão. Índices únicos redundantes
  com exatamente uma semântica já coberta também são aceitos.
- Identidade dos três índices nomeados da etapa 2: nome, tabela proprietária,
  colunas e ordem, direção, collation, unicidade, origem e parcialidade.
- Ausência de gatilhos desconhecidos nas tabelas protegidas.
- Ausência dos objetos e colunas novos, inclusive colisões de nome por caixa.

Não basta constar a versão 2 no histórico. Incompatibilidades produzem
`ValueError: Esquema incompativel para migracao 3: ...` antes da criação.
Falhas posteriores desfazem tabelas, colunas, índices, visões, gatilhos e o
registro da versão 3. As versões 1 e 2 e os dados existentes permanecem.
Não se permite acrescentar unicidades por DDL fora de uma migração aprovada
após a aplicação: a versão registrada não é revalidada em toda operação.

O SQLite deste ambiente executa internamente `PRAGMA quick_check` ao adicionar
colunas com CHECK. O autorizador permite essa ação apenas durante os ALTERs
exatos e confiáveis da versão 3, para a tabela e schema esperados. Não permite
PRAGMAs explícitos, nem libera BEGIN, COMMIT, ROLLBACK, SAVEPOINT, RELEASE,
ATTACH ou DETACH. O núcleo transacional e a validação do destino permanecem.

## Limitações reservadas ao serviço futuro

O serviço ainda não existe nesta etapa. Ele precisará comparar requisições
canônicas para idempotência, recuperar os efeitos por ID de operação e
conferir sua completude antes do fechamento. Não poderá executar COMMIT com
operações abertas: SQLite não possui aqui uma CHECK diferida de aplicação
para garantir isso. O teste de guarda transacional apenas modela essa obrigação
e comprova o rollback; não representa integração já implementada.

`RAISE(ABORT)` desfaz a instrução que falhou. O serviço deve desfazer a transação
inteira em qualquer falha, sem persistir operações ou contramovimentos órfãos.
Os gatilhos impedem efeitos adicionais em operações concluídas, mas não
atestam a completude semântica de uma requisição.

Não há adoção automática de registros legados, alteração de menus ou relatórios,
nem sincronização financeira por gatilhos. Os testes das etapas 1 e 2 usam seus
catálogos históricos; os testes de `test_migracao_3.py` cobrem o catálogo completo.
