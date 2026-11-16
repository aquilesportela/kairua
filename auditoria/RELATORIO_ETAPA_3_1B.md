# Auditoria adversarial da etapa 3.1B

## Atualização após as correções F01–F04

As correções abaixo estão implementadas, **aguardando nova auditoria técnica**.
Não há aprovação para commit. A seção histórica seguinte preserva as evidências
e o veredito da implementação original, anterior às correções.

Validação pós-correção em SQLite temporário com KAIRUA_DB_PATH: 18 testes
adversariais aprovados; 23 testes da migração 3 aprovados; suíte completa com
141 testes, sendo 139 aprovados, dois ignorados por permissão de symlink e
zero falhas. `git diff --check` passou e os arquivos alterados estão em
UTF-8/LF. AGENTS.md e tests/test_parcelamentos.py foram preservados byte a byte.

| Achado | Alteração | Critério atual de regressão |
| --- | --- | --- |
| F01 | PK independente em reversões e `evento_id NOT NULL UNIQUE`. | FK omitida/nula, origem negativa e evento liquidado são rejeitados; nenhuma outra identidade é revertida. |
| F02 | Manifesto das unicidades cobertas e inspeção completa dos índices das nove tabelas protegidas. | Expressões, unicidades adicionais/parciais e collations não cobertas impedem a versão 3 antes de qualquer DDL. Dados e versões anteriores devem ficar intactos. |
| F03 | Domínio positivo dos novos IDs híbridos, checagens posteriores à atribuição e proteção separada de IDs legados. | IDs negativos/zero não entram no fluxo híbrido; IDs automáticos e positivos funcionam; legados negativos são preservados e protegidos. |
| F04 | Validação do proprietário e metadados completos dos índices nomeados. | Nome correto em tabela errada, ordem/expressão/collation/flags incompatíveis são rejeitados sem efeitos parciais. |

Os testes ativos agora são regressões `test_f01_*` a `test_f04_*`: passam
somente ao bloquear os problemas. Os antigos métodos `test_reproduz_*` foram
substituídos. As caracterizações de L01/L02 não continuam como testes positivos
de vulnerabilidade; suas evidências históricas permanecem abaixo e suas
responsabilidades de serviço/compatibilidade não foram alteradas.

O módulo também é descoberto pela suíte normal por
`tests/test_regressao_migracao_3.py`. O inventário atual possui 45 gatilhos,
incluindo oito verificações AFTER INSERT adicionais. A seção de 37 gatilhos
abaixo descreve exclusivamente a versão originalmente auditada.

Índices comuns não únicos adicionais são permitidos. Unicidades redundantes
com a mesma chave global simples ASC/BINARY coberta são permitidas; as demais
são rejeitadas conservadoramente. Novas unicidades após a migração exigem
nova migração aprovada, não DDL avulso.

Não se altera o alocador SQLite nem os IDs históricos: em tabelas de eventos
somente com IDs negativos, uma atribuição automática não positiva é rejeitada
pelo domínio híbrido; um ID positivo explícito permite prosseguir. Os caminhos
legados continuam preservados. Essa limitação está testada e documentada.

## Registro histórico — implementação original, antes das correções

Veredito: **bloqueado para commit**. Nenhum código de produção foi corrigido.
Reproduções em `test_migracao_3_adversarial.py`, fora da descoberta normal de
`tests/`. Os testes `reproduz_*` passam quando a vulnerabilidade é confirmada;
esse resultado não representa aprovação da implementação.

Execução desta auditoria: 12 testes adversariais e 23 testes originais da
migração 3, todos concluídos sem falhas ou skips do runner. Os testes de
caracterização confirmaram quatro achados e duas limitações documentadas.
O processo pai também recebeu KAIRUA_DB_PATH temporário e bytecode desabilitado.
Não foi reexecutada a suíte completa de 123 testes nesta auditoria.

## Achados comprovados

### F01 — alta: reversão validada para um evento e aplicada a outro

- Local: `migracao_3.py:79` e `migracao_3.py:207–214`.
- Pré-condição: evento manual confirmado com ID -1 e saldo líquido zero;
  evento de ID 1 já liquidado. Ambos os IDs são aceitos pelo esquema.
- Ação: inserir reversão omitindo `evento_id` ou passando NULL.
- Resultado: a verificação BEFORE INSERT usa o ID provisório -1; a coluna
  INTEGER PRIMARY KEY recebe depois o ID automático 1. O evento pago é
  revertido sem estornar seus 1.000 centavos liquidados.
- Evidência: `test_reproduz_reversao_null_valida_evento_negativo_mas_reverte_evento_pago`,
  confirmado em oito combinações: FKs e recursive_triggers 0/1, ID omitido/nulo.
- Correção recomendada: a FK de reversão não deve ser um rowid autoatribuído.
  Usar `evento_id INTEGER NOT NULL UNIQUE` com PK independente ou uma tabela
  WITHOUT ROWID, validando o identificador efetivamente fornecido. Acrescentar
  regressões com IDs nulos, omitidos e negativos.

### F02 — alta: UNIQUE adicional contorna proteção contra REPLACE

- Locais: `migracao_3.py:156–175`, `:241–272` e pré-condição `:329–340`.
- Pré-condições: índice UNIQUE adicional preexistente, aceito pela migração;
  foreign_keys=0 e recursive_triggers=0. Não é necessário remover gatilhos,
  mudar o esquema após a migração ou desabilitar CHECKs.
- As verificações reconhecem somente PKs e chaves únicas previstas. Outra
  unicidade pode provocar a exclusão implícita de uma linha protegida.
- Reproduções: UNIQUE(lower(nome)) em categorias; UNIQUE(descricao) em compras
  e lançamentos. INSERT OR REPLACE remove categoria usada; INSERT/UPDATE OR
  REPLACE removem compra referenciada e caixa híbrido conciliado.
- Impacto: vínculos órfãos e perda de registros protegidos, inclusive de caixa.
- Evidências: três métodos `test_reproduz_*replace*` no módulo adversarial.
- Correção mínima: rejeitar esquemas com unicidades adicionais não suportadas
  nas tabelas protegidas antes da versão 3. Documentar que DDL posterior também
  precisa de migração aprovada. Alternativa maior: cobrir genericamente todas
  as unicidades, inclusive expressões, collations e índices parciais.

### F03 — média: ID -1 causa bloqueio espúrio de IDs automáticos

- Local: `migracao_3.py:129–132`.
- Inserir operação com ID -1 é permitido. Depois, uma operação com chave nova
  e ID omitido é rejeitada como `operacao_duplicada` pelo valor provisório do
  rowid no BEFORE INSERT.
- Evidência: `test_reproduz_sentinela_menos_um_bloqueia_operacoes_com_id_automatico`.
- Impacto: indisponibilidade do cadastro automático, sem duplicação real.
- Correção: definir o domínio de IDs e eliminar a dependência do rowid ainda
  não atribuído. Revisar o mesmo padrão nos demais gatilhos BEFORE INSERT.

### F04 — baixa: pré-condição confere colunas do índice, mas não sua tabela

- Local: `migracao_3.py:341–347`.
- Substituir `idx_eventos_competencia` por um índice de mesmo nome e coluna
  em outra tabela ainda permite a aplicação da migração 3.
- Evidência: `test_reproduz_precondicao_aceita_indice_da_etapa_2_na_tabela_errada`.
- Impacto: aceitação de esquema diferente do esperado, sobretudo de desempenho.
- Correção: conferir tabela proprietária, ordem, unicidade, parcialidade e
  demais atributos necessários, não apenas `pragma_index_info`.

## Limitações comprovadas já atribuídas ao serviço

- L01: é possível concluir e confirmar operação de estorno com caixa negativo,
  mas sem linha em estornos_liquidacoes. O banco não garante completude dos
  efeitos, mesmo após o estado concluida. Isso está documentado; o teste de
  guarda futuro apenas modela um serviço, não testa uma implementação real.
- L02: 2^53 e 2^53+1 centavos produzem a mesma projeção REAL. A representação
  inteira permanece correta; a visão legada pode perder centavos. A igualdade
  canônica não é garantia de precisão decimal nem de projeção injetiva.

## Inventário individual dos 37 gatilhos

Revisão estática de cada definição gerada, comparada ao catálogo instalado.
Os controles dinâmicos não equivalem à cobertura de todos os caminhos SQL.

| Gatilho | Resultado da revisão |
| --- | --- |
| tr_operacoes_bi | F03; chave única bloqueada, mas ID provisório pode gerar falso positivo. |
| tr_operacoes_bu | Somente fechamento, sem validar completude; L01. |
| tr_operacoes_bd | Bloqueio incondicional de DELETE. |
| tr_eventos_bi | Aceita ID negativo; participa de F01; valida origem/operação/categoria. |
| tr_eventos_bu | Bloqueio incondicional de UPDATE. |
| tr_eventos_bd | Bloqueio incondicional de DELETE. |
| tr_lancamentos_bi | F02 para UNIQUE adicional; L01/L02. |
| tr_lancamentos_bu | F02 para UPDATE OR REPLACE por UNIQUE adicional; PK conhecida bloqueada. |
| tr_lancamentos_bd | Protege DELETE explícito; não cobre exclusão implícita com RT=0. |
| tr_liquidacoes_bi | Referências, tipo e limites conhecidos verificados; concorrência controlada. |
| tr_liquidacoes_bu | Bloqueio incondicional de UPDATE. |
| tr_liquidacoes_bd | Bloqueio incondicional de DELETE. |
| tr_estornos_bi | Limite acumulado, sinal, referência, natureza e datas verificados nos controles. |
| tr_estornos_bu | Bloqueio incondicional de UPDATE. |
| tr_estornos_bd | Bloqueio incondicional de DELETE. |
| tr_reversoes_bi | F01: identidade validada pode diferir da inserida. |
| tr_reversoes_bu | Bloqueio incondicional de UPDATE. |
| tr_reversoes_bd | Bloqueio incondicional de DELETE. |
| tr_reclassificacoes_bi | Estado, categoria e sequência lógica anterior verificados. |
| tr_reclassificacoes_ai | Rejeita ID inferior ao histórico existente. |
| tr_reclassificacoes_bu | Bloqueio incondicional de UPDATE. |
| tr_reclassificacoes_bd | Bloqueio incondicional de DELETE. |
| tr_compras_origem_bi | F02 comprovado por UNIQUE(descricao). |
| tr_compras_origem_bu | F02 comprovado por UPDATE OR REPLACE. |
| tr_compras_origem_bd | Protege DELETE explícito; não cobre exclusão implícita com RT=0. |
| tr_parcelamentos_origem_bi | Mesma limitação estrutural de F02; não reproduzida separadamente. |
| tr_parcelamentos_origem_bu | Mesma limitação estrutural de F02; não reproduzida separadamente. |
| tr_parcelamentos_origem_bd | Protege DELETE explícito de ID referenciado. |
| tr_parcelas_origem_bi | Protege PK e par conhecido; índices únicos adicionais não examinados. |
| tr_parcelas_origem_bu | Protege PK e par conhecido; índices únicos adicionais não examinados. |
| tr_parcelas_origem_bd | Protege DELETE explícito de ID referenciado. |
| tr_ocorrencias_origem_bi | Protege PK e par conhecido; índices únicos adicionais não examinados. |
| tr_ocorrencias_origem_bu | Protege PK e par conhecido; índices únicos adicionais não examinados. |
| tr_ocorrencias_origem_bd | Protege DELETE explícito de ID referenciado. |
| tr_categorias_bi | F02 comprovado; no-op idêntico é a única exceção de IGNORE declarada. |
| tr_categorias_bu | Colisões por ID/nome conhecidas protegidas; mesma limitação de índices adicionais. |
| tr_categorias_bd | Protege DELETE explícito; não cobre exclusão implícita com RT=0. |

## Autorizador, concorrência e testes

A exceção quick_check exige versão, nome e texto exatos, tabela, schema main
e origem esperada. Não foi encontrado bypass de SQL arbitrário nessa exceção.
Callbacks e execução real confirmaram rejeição de PRAGMAs explícitos e
comandos transacionais, com rollback da versão 3. O bloco BEGIN/END de CREATE
TRIGGER é aceito sem liberar transações arbitrárias.

Controle com duas conexões: segunda escrita recebeu database locked; após
confirmar a primeira liquidação, a tentativa de excesso foi rejeitada. Isso
não substitui testes de um serviço transacional futuro.

Os 23 testes originais não cobrem IDs negativos/provisórios, FKs como PKs
autoatribuídas, UNIQUE adicionais, nem índices com nome certo na tabela errada.
O teste de guarda de serviço levanta sua própria exceção e comprova apenas o
rollback desse modelo. O teste textual dos corpos dos gatilhos não detecta
exclusões implícitas de REPLACE.

Os controles conhecidos de PKs/pares compostos, estornos acumulados e proibição
de comandos do executor continuam válidos. Nenhuma correção de produção foi
aplicada nesta auditoria.
