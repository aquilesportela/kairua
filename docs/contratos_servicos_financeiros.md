# Etapa 3.2A — contratos dos serviços financeiros

Status atual: 3.2A encerrada documentalmente; D01–D07 APROVADAS pelo usuário.
Fase 3.2B concluída e aprovada, com validação final APTO para encerramento técnico.
Versionamento da 3.2B ainda pendente. Cronograma executado e validação: seções 12–13.
Referências estruturais: commits f51a7d4, 9d03521 e fe7bb69.

Registro histórico: a especificação original da 3.2A foi produzida por inspeção
estática, sem execução de serviços ou migrações e sem alterações em menus ou
relatórios. Esse registro não representa o estado atual da implementação da 3.2B.

## 1. Resumo executivo

Os seis serviços foram implementados sobre o esquema aprovado, sem migração
4. Cada chamada representa uma operação simples e completa. O modelo
aceita múltiplos efeitos por operação e conciliação muitos-para-muitos; a primeira
API desta fase cria um evento por cadastro e um caixa por liquidação/estorno.
Rateios em lote e associação de caixa preexistente ficam para outra etapa.

O banco protege identidades, referências, sinais, limites e imutabilidade. Não
garante sozinho a completude dos efeitos, a equivalência de requisições
idempotentes, a confirmação de datas divergentes ou a ausência de operações
abertas no commit. Essas são obrigações explícitas do serviço.

As sete decisões da seção 11 estão aprovadas. Suas alternativas e justificativas
anteriores foram preservadas como histórico, sem efeito normativo. Na 3.2A,
a aprovação das regras não autorizava implementar código: ver o registro histórico
do [plano da 3.2B.1](plano_3_2B_1.md). As etapas da 3.2B foram autorizadas
separadamente e estão concluídas; integrações posteriores continuam fora do escopo.
Não se altera a interpretação do legado.

## 2. Base efetivamente implementada

### 2.1 Mapa e evidências

| Estrutura | Contrato existente e localização |
| --- | --- |
| `esquema_migracoes` | Versões/nome como prefixo do catálogo; execução explícita, por versão e `BEGIN IMMEDIATE` (`banco.py:243`). Não há migração na abertura da conexão. |
| `operacoes_hibridas` | ID positivo, chave única não vazia, tipo enumerado, requisição canônica não vazia, estado `aberta`→`concluida`; campos imutáveis e sem DELETE (`migracao_3.py:41`, `:130`). Não há verificação semântica do JSON. |
| `eventos_financeiros` | Competência, tipo próprio receita/despesa, valor inteiro positivo, chave de origem única e origens legadas opcionais/exclusivas (`banco.py:35`). Novas inserções após a versão 3 são exclusivamente manuais confirmadas, com operação e vencimento (`migracao_3.py:61`, `:143`). |
| `lancamentos` | Caixa legado REAL, acrescido de operação e centavos assinados, ambos nulos no legado (`migracao_3.py:52`). Híbridos usam data válida, categoria/tipo compatíveis e projeção REAL canônica; ficam imutáveis (`:164`). |
| `liquidacoes_eventos` | Valor inteiro positivo, referências e par evento/caixa único. Muitos-para-muitos; limites agregados por evento e caixa (`banco.py`, catálogo 2; `migracao_3.py:183`). Não possui coluna de operação própria. |
| `estornos_liquidacoes` | Liga liquidação a caixa negativo único, com natureza e motivo; múltiplos estornos parciais possíveis. Não possui coluna de valor nem operação: usa os dados do caixa vinculado (`migracao_3.py:71`, `:200`). |
| `reversoes_eventos` | PK independente, evento obrigatório/único, operação, data de competência da reversão, categoria e motivo. Apenas integral e com liquidação líquida zero (`migracao_3.py:78`, `:217`). Não possui valor: usa o valor integral do evento. |
| `reclassificacoes_eventos` | ID AUTOINCREMENT positivo, evento, operação, categoria anterior/nova, motivo, par operação/evento único e sequência crescente. Não atualiza o evento (`migracao_3.py:86`, `:227`). |
| `eventos_classificacao_atual` | Evento e categoria da última reclassificação por ID, preservando categoria original. Inclui eventos revertidos: consultar reversões separadamente (`migracao_3.py:113`). |
| `_hibrido_liquidacoes` | Valor líquido de cada liquidação: original mais caixas negativos vinculados por estornos (`migracao_3.py:118`). |
| `_hibrido_categorias_em_uso` | União de referências para proteger categorias, inclusive legado (`migracao_3.py:123`). |

Há 45 gatilhos, incluindo validação AFTER INSERT do ID definitivo. Não fazem
ajustes monetários automáticos. F01–F04 e N01 estão corrigidos no commit de
referência: PK da reversão independente, rejeição de unicidades não cobertas,
domínio positivo e identidade completa de índices; gatilhos desconhecidos são
detectados com `tbl_name COLLATE NOCASE`. A versão registrada não constitui
auditoria permanente contra alterações posteriores de esquema.

Fontes adicionais: `docs/migracao_3.md`, `docs/infraestrutura_sqlite.md`,
`tests/test_esquema_hibrido.py`, `tests/test_migracao_3.py`,
`auditoria/RELATORIO_ETAPA_3_1B.md`, `auditoria/RELATORIO_POS_CORRECAO_3.md`.
Os vereditos históricos desses relatórios devem ser lidos com suas atualizações.

### 2.2 Banco versus serviço

| Garantia | Banco atual | Obrigação adicional do serviço |
| --- | --- | --- |
| Idempotência | Colisão de chave aborta; operação imutável | Comparar tipo/payload, recuperar recibo anterior; nunca usar REPLACE |
| Competência manual | Confirmada, categoria compatível, vencimento válido | Exigir confirmação econômica explícita na entrada |
| Datas diferentes | Datas ISO válidas; regras específicas de estorno | Exigir confirmação explícita de diferença entre caixa e competência |
| Liquidação | Soma líquida por evento ≤ valor; alocação original por caixa ≤ caixa | Criar caixa exatamente conciliado; impedir alvo legado/revertido |
| Estorno | Caixa negativo único, tipo/categoria originais, limite acumulado e natureza/data | Criar contramovimento e vínculo juntos; comparar requisições repetidas |
| Reversão | Única, integral, líquido zero, categoria corrente | Tratar efeito econômico sem criar caixa; validar política de data D03 |
| Reclassificação | Categorias do mesmo tipo, anterior corrente, sequência crescente | Confirmar intenção e política para nenhuma mudança D04 |
| Fechamento | Transição única e proibição de novos efeitos fechados | Conferir quantidade, vínculos e valores de todos os efeitos antes de fechar |
| Falha | `RAISE(ABORT)` desfaz a instrução | Rollback de toda a transação, incluindo operação e efeitos anteriores |

## 3. Tipos, resultados e erros comuns

Módulo implementado: `servicos_financeiros.py`, independente de Rich e de `app.py`.
Não chamar funções legadas que abrem conexões ou fazem commit internamente.
Auxiliares privados recebem a mesma conexão e nunca confirmam a transação.

As assinaturas abaixo registram os contratos aprovados e implementados. Os parâmetros são
nomeados. `TipoEconomico = Literal['receita', 'despesa']`;
`NaturezaEstorno = Literal['devolucao_real', 'correcao_registro']`.
`int` de domínio exclui `bool`; referências são inteiros int64. IDs de novos
registros híbridos são positivos e internos; IDs de categorias legadas podem
ser não positivos se existentes e compatíveis. A API não recebe PKs novos.

`ResultadoOperacao` implementado, imutável:

- `operacao_id: int`, `chave: str`, `tipo_operacao: str`;
- tuplas ordenadas de `evento_ids`, `lancamento_ids`, `liquidacao_ids`,
  `estorno_ids`, `reversao_ids`, `reclassificacao_ids`, vazias quando não aplicáveis;
- `versao_contrato: int = 1`.

Não retornar saldo atual como se fosse o resultado original: pode mudar entre
repetições. IDs, valores e datas dos efeitos persistidos permitem reconstrução;
consultas de saldo atual são separadas. Um indicador de replay, se necessário,
pertence ao envelope de transporte e não altera o recibo financeiro.

Erros de domínio implementados: `ParametroInvalido`, `ValorInvalido`, `DataInvalida`,
`ConfirmacaoNecessaria`, `CategoriaInexistente`, `CategoriaIncompativel`,
`EventoInexistente`, `EventoNaoElegivel`, `EventoRevertido`,
`LiquidacaoInexistente`, `SaldoInsuficiente`, `EstornoExcessivo`,
`EventoJaRevertido`, `EventoAindaLiquidado`, `ReclassificacaoSemAlteracao`,
`ConflitoIdempotencia`, `ConflitoEstado`, `OperacaoIncompleta`, `EsquemaIncompativel`,
`IdentificadoresEsgotados`, `BancoOcupado`, `FalhaPersistencia`.

Erros de validação não escrevem dados. Erros depois de BEGIN sempre provocam
rollback. Traduzir somente restrições conhecidas para erros específicos;
não classificar todo IntegrityError como duplicidade, nem todo OperationalError
como concorrência. Manter a causa técnica, sem expor SQL como mensagem de UI.

## 4. Política monetária aprovada

1. Serviços recebem exclusivamente `valor_centavos: int`, positivo, no intervalo
   `1..M`, com `M = 2**63 - 1 = 9223372036854775807`. Estorno também recebe
   magnitude positiva; somente o serviço escreve seu negativo no caixa.
2. Adaptador decimal futuro aceita `str` decimal sem separadores de milhares
   ou `Decimal` finito. Rejeitar float, bool, NaN, Infinity e sinais/formatos
   inválidos. Nunca usar `Decimal(float)` ou `Decimal(str(float))` como reparo.
   Convenção de vírgula brasileira pertence ao adaptador de entrada explícito;
   não aceitar formatos ambíguos por substituições indiscriminadas.
3. Converter com Decimal em contexto local de precisão suficiente (mínimo 40
   dígitos, validando tamanho antes da conversão). Quantizar a 0,01 e comparar
   com a entrada: rejeitar se houver fração de centavo, sem alteração
   silenciosa. `1.000` equivale a `1.00`; `1.001` exige rejeição. A política
   aprovada D01 não permite arredondamento silencioso nem aceita fração de centavo.
4. Obter inteiro por multiplicação decimal exata por 100, verificar intervalo e
   só então converter para int. Não fazer contas de domínio com REAL/float.
5. Projeção de caixa na própria instrução parametrizada:
   `valor = CAST(:valor_centavos AS REAL) / 100.0`. O gatilho exige essa igualdade,
   mas ela não garante precisão decimal/injetividade em valores grandes.
6. Caixa híbrido admite `[-M, -1] ∪ [1, M]`. `-2**63` está expressamente excluído
   para permitir negação inteira segura. Eventos e liquidações são positivos.
   Afinidade SQLite pode aceitar `100.0` ou `'100'` como INTEGER: o serviço é
   mais estrito e rejeita tipos errados antes do binding.
7. Somar inteiros em Python quando houver risco de overflow global; nunca
   substituir SUM por TOTAL ou CAST REAL. SUM SQLite pode exceder int64 mesmo
   com cada linha válida. Falhar e fazer rollback se isso ocorrer em uma
   invariante. Agregações futuras multieventos devem prever soma Python exata.

O teste estrutural `test_limites_int64_nao_usam_soma_float` comprova limite por
evento e erro explícito de overflow; não prova precisão dos relatórios REAL.
L02 da auditoria comprova colisão de projeção para `2**53` e `2**53+1` centavos.
D02 aprova o limite técnico int64, sem teto comercial nesta etapa; centavos
inteiros continuam sendo a fonte financeira autoritativa.

## 5. Datas e confirmações

Entradas públicas usam `datetime.date` puro (rejeitar datetime) e persistem ISO
`YYYY-MM-DD`, calendário válido, anos 0001..9999. Um adaptador textual deve
exigir formato estrito e validar o calendário, incluindo 29/02. Não usar
timestamp, fuso ou hora corrente como substituto de data financeira.

| Data | Origem e significado |
| --- | --- |
| Competência | Evento econômico confirmado; `eventos_financeiros.data_competencia` |
| Vencimento | Prazo próprio do compromisso; `data_vencimento`, obrigatório nesta API, sem inferência |
| Liquidação | Entrada/saída real; `lancamentos.data` do caixa positivo |
| Estorno | `lancamentos.data` do contramovimento negativo |
| Reversão | Entrada `data_reversao`, persistida em `reversoes_eventos.data_competencia`; sem novo caixa |
| Registro técnico | `operacoes_hibridas.registrada_em`; não substitui nenhuma data acima |

`confirmar_ocorrencia` deve ser exatamente True no cadastro; o serviço grava
sempre `situacao_competencia='confirmada'` e `origem_tipo='manual'`.
`confirmar_datas_divergentes` é bool obrigatório: se data de caixa ou estorno
for diferente da competência do evento, exigir True. False é permitido quando
iguais; registrar o valor recebido na requisição canônica. A confirmação não
relaxa os limites, as datas de estorno ou as regras de categoria.

Vencimento não implica ocorrência nem liquidação. O esquema não ordena
vencimento/competência e permite caixa anterior à competência mediante confirmação.
Datas retroativas e futuras são permitidas por D03; não adicionar limites de
período. Estorno `devolucao_real` exige data >= caixa original;
`correcao_registro` exige exatamente a data original, conforme gatilho existente.
Reversão utiliza a data explicitamente informada, conforme D03.

## 6. Idempotência, recuperação e concorrência

Chave aprovada D05: `kairua:v1:<uuid-em-minusculas>`, gerada pelo chamador uma vez
por intenção e mantida nos retries. Unicidade global na base, não só por função.
Não derivar chave apenas de valor/data: operações legítimas podem coincidir.
O banco apenas exige texto não vazio; validar o formato aprovado no serviço.

Requisição canônica: JSON UTF-8 com `sort_keys=True`, separadores compactos,
`ensure_ascii=False`, sem floats, incluindo versão do contrato, nome do serviço,
todos os parâmetros financeiros, motivo, descrição e confirmações. Datas ISO,
valores/IDs inteiros e opcionais explícitos como null. Normalizar texto em NFC
e remover espaços nas extremidades antes da validação; não alterar conteúdo
interno nem caixa. Chave pode ser externa ao payload, pois identifica a linha;
tipo de operação e versão permanecem no envelope canônico.

Não incluir valores dinâmicos resolvidos do banco (nome atual da categoria,
saldo, hora, categoria anterior descoberta) no payload comparado. Esses dados
podem mudar entre retries. Se um campo for opcional, seu default deve ser
determinístico e aplicado antes da serialização. APIs abaixo não usam defaults
de data/valor baseados no relógio ou saldo corrente.

Após BEGIN IMMEDIATE, buscar `operacoes_hibridas WHERE chave=?`:

- Mesmos tipo e payload, estado concluida: reconstruir os efeitos, conferir
  sua completude e retornar o recibo original, sem escrita ou revalidação do
  estado financeiro atual. Uma reversão/reclassificação posterior não invalida
  um replay legítimo da criação/liquidação anterior.
- Mesma chave e tipo/payload distintos: `ConflitoIdempotencia`, sem efeitos.
- Estado aberta persistido: `OperacaoIncompleta`; não completar, apagar ou
  reutilizar automaticamente. O esquema permite essa corrupção por SQL externo;
  o serviço deve detectá-la. Sua recuperação exige procedimento próprio aprovado.
- Chave ausente: validar estado dinâmico, criar operação aberta e executar.

Recuperação de IDs, filtrando sempre pela operação original:

| Efeito | Consulta/associação |
| --- | --- |
| Evento/caixa | Sua coluna `operacao_hibrida_id` |
| Liquidação | JOIN com seu caixa positivo e operação do caixa; não pela operação criadora do evento |
| Estorno | JOIN com `lancamento_estorno_id` e operação do caixa negativo |
| Reversão/reclassificação | Sua própria coluna `operacao_hibrida_id` |

Como não há resposta serializada nem snapshots de saldo, o recibo deve conter
somente identificadores estáveis/efeitos imutáveis. Parâmetros persistidos na
requisição canônica guardam confirmações que não têm coluna dedicada.

BEGIN IMMEDIATE serializa escritores antes da consulta de saldo/idempotência.
Dois clientes com a mesma chave: o segundo aguarda, depois retorna replay ou
conflito. Com chaves distintas sobre o mesmo saldo: o segundo recalcula após
o primeiro commit. Timeout de lock gera BancoOcupado; retry integral e limitado
com a mesma chave, nunca somente o último INSERT. Em perda de resposta após
commit, reabrir e consultar a mesma chave. Falha de commit com estado incerto
não autoriza gerar outra chave; consultar de novo antes de repetir a intenção.

## 7. Unidade transacional comum

1. Validar tipos, formatos, magnitude, datas e canonicalizar, sem abrir banco.
2. Abrir conexão própria usando `banco.abrir_conexao()` e KAIRUA_DB_PATH; não
   mudar o comportamento global da função. Configurar FKs ON antes da transação
   e verificar o PRAGMA. Configurar recursive_triggers ON na conexão do serviço
   para defesa adicional, sem depender dele para as proteções já implementadas.
3. Exigir esquema aprovado 1/2/3, tabelas/visões/gatilhos necessários; falhar
   fechado se indisponível. Não executar migração ou inicialização financeira.
   Definir verificação estrutural de instalação separada de cada chamada; não
   fazer scans globais de dados históricos nem repará-los automaticamente.
4. Executar BEGIN IMMEDIATE, depois consulta idempotente da seção 6. Revalidar
   sob lock os alvos, categorias e saldos de chamadas novas.
5. INSERT simples da operação aberta com tipo exato do catálogo. Capturar ID
   real por lastrowid/RETURNING, nunca por consulta de último ID global.
6. Criar efeitos na ordem abaixo; SQL parametrizado e listas fechadas de colunas.
   Nunca INSERT OR REPLACE, UPDATE OR REPLACE, OR IGNORE ou executescript.
7. Conferir todos os efeitos da operação, referências, sinais, valores e
   cardinalidades esperadas; não exigir estado atual intacto de efeitos antigos
   em um replay. Falhar se houver efeito faltante ou extra.
8. UPDATE somente `estado='concluida'` da operação aberta; exigir rowcount=1.
   Conferir que nenhuma operação criada nesta transação permanece aberta.
   Operações abertas preexistentes são diagnóstico separado, nunca fechar em lote.
9. Commit, depois retornar recibo. Em qualquer exceção após BEGIN, rollback
   integral; fechar conexão em finally, inclusive em replay, timeout e commit
   mal sucedido. A conexão não pode ser compartilhada entre chamadas/threads.

Não usar apenas `with connection` como garantia de fechamento. Não capturar
ABORT para continuar e confirmar efeitos anteriores. O executor de migrações
e seu autorizador não são o executor dos serviços e não precisam mudar.

IDs: preferir atribuição nativa positiva e capturar o resultado definitivo.
Para eventos/liquidações compartilhados, quando MAX(id) <= 0, atribuir
explicitamente 1 sob o lock para evitar o alocador não positivo documentado.
Verificar capacidade antes de inserir; não contornar saturação com IDs negativos
ou reutilização manual. Tabelas AUTOINCREMENT mantêm sua sequência nativa.
Tratar esgotamento/SQLITE_FULL de forma explícita; testar históricos somente
negativos, zero e limites, sem reescrever IDs existentes.

### 7.1 Completude esperada por operação

| Tipo do catálogo | Efeitos novos exatos |
| --- | --- |
| registrar_evento | 1 evento, nenhum caixa/conciliação/histórico |
| registrar_imediata | 1 evento, 1 caixa positivo e 1 liquidação pelo valor integral |
| liquidar_evento | Nenhum evento novo; 1 caixa positivo e 1 liquidação do mesmo valor |
| estornar_liquidacao | 1 caixa negativo e 1 estorno ligando-o à liquidação indicada |
| reverter_evento | 1 reversão e nenhum caixa/evento/liquidação novo |
| reclassificar_evento | 1 reclassificação e nenhum caixa/evento/liquidação novo |

O serviço deve conferir também ausência de outros tipos de efeito para aquela
operação. O banco admite mais de um efeito por desenho, não deve ganhar índices
únicos que inviabilizem lotes futuros. Um lote futuro precisará de outro contrato
de completude/resultado; esta API não o admite implicitamente.

## 8. Contratos dos seis serviços

Todos herdam tipos, erros, idempotência, rollback e conexão das seções anteriores.
Descrições/motivos obrigatórios são texto normalizado não vazio. Categorias são
existentes e compatíveis com o tipo próprio do evento, não definem seu tipo.
Alvos devem ser eventos manuais confirmados já pertencentes ao fluxo híbrido;
histórico pendente/estimado ou sem origem manual não é adotado automaticamente.

### 8.1 registrar_evento_manual

```python
registrar_evento_manual(*, chave: str, tipo: TipoEconomico, descricao: str,
    categoria_id: int, valor_centavos: int, data_competencia: date,
    data_vencimento: date, confirmar_ocorrencia: bool) -> ResultadoOperacao
```

- Todos obrigatórios; não recebe status, origem externa ou caixa opcional.
- Pré-condições: confirmação True; categoria existente com mesmo tipo; valor e
  datas válidos. Vencimento é explícito mesmo se igual à competência.
- Consulta operações/categorias; escreve operações/eventos.
- SQL após lookup: INSERT operação `registrar_evento`; INSERT evento manual
  confirmado, referências legadas nulas, `chave_origem='manual:' + chave + ':evento:0'`,
  operação, vencimento e dados econômicos; conferir um evento; fechar operação.
- Resultado: IDs da operação e do evento; demais tuplas vazias. Não há despesa
  ou receita em caixa, nem lançamento pendente em `lancamentos`.
- Erros específicos: confirmação ausente, categoria inválida/incompatível,
  origem duplicada externa, identificador não positivo/esgotado. Colisão de
  origem com operação ausente é inconsistência, não replay presumido.
- Gatilhos: tr_operacoes_bi/bu, tr_eventos_bi/ai; datas/valor pelos CHECKs.
- Extremos: ocorrência confirmada futura conforme D03; histórico negativo
  exige alocação positiva; chamadas repetidas retornam o evento já criado,
  inclusive se posteriormente reclassificado, liquidado ou revertido.

### 8.2 registrar_operacao_imediata

```python
registrar_operacao_imediata(*, chave: str, tipo: TipoEconomico, descricao: str,
    categoria_id: int, valor_centavos: int, data_competencia: date,
    data_vencimento: date, data_liquidacao: date, confirmar_ocorrencia: bool,
    confirmar_datas_divergentes: bool) -> ResultadoOperacao
```

- Todos obrigatórios. Imediata significa liquidação integral na mesma chamada;
  não exige igualdade de datas, mas exige confirmação se divergentes.
- Consulta operações/categorias; escreve operação, evento, caixa e liquidação.
- SQL: INSERT operação `registrar_imediata`; INSERT evento como 8.1; INSERT
  caixa positivo com mesma operação/tipo/categoria e descrição, data de caixa,
  `categoria` textual capturada do cadastro e REAL projetado no SQLite;
  INSERT liquidação pelo valor integral; conferir as três linhas; concluir.
- Resultado: um ID em cada tupla de evento, caixa e liquidação. O pagamento
  não cria outro evento e a competência não cria outro lançamento de caixa.
- Erros específicos: os de 8.1, DataInvalida/ConfirmacaoNecessaria e falhas de
  conciliação. Rejeitar liquidação parcial: usar 8.1 e depois 8.3.
- Gatilhos: os de 8.1 mais tr_lancamentos_bi/ai e tr_liquidacoes_bi/ai.
- Extremos: 1 centavo/M, diferença de mês/ano, receita ou despesa, falha entre
  evento/caixa/liquidação. Nada pode persistir parcialmente.

### 8.3 liquidar_evento

```python
liquidar_evento(*, chave: str, evento_id: int, valor_centavos: int,
    data_liquidacao: date, confirmar_datas_divergentes: bool,
    descricao_caixa: str | None = None) -> ResultadoOperacao
```

- Único opcional: descrição do caixa; null significa copiar a descrição
  imutável do evento. Não recebe caixa existente, categoria ou tipo arbitrário.
- Pré-condições: evento manual confirmado não revertido; valor positivo <=
  saldo aberto; confirmação se caixa difere da competência. Categoria de caixa
  aprovada: corrente no instante da liquidação (D06), do mesmo tipo do evento.
- Consulta operações, eventos_classificacao_atual, reversões, categorias e
  _hibrido_liquidacoes. `L(e)=Σ valor_liquido`, `aberto=valor_evento-L(e)`.
- SQL: validar sob lock; INSERT operação `liquidar_evento`; INSERT caixa
  positivo com tipo do evento e classificação capturada; INSERT liquidação
  `(evento_id, lancamento_id, valor_centavos)`; conferir 1 caixa/1 vínculo e
  soma conciliada igual ao caixa; concluir. Não atualizar o evento.
- Resultado: evento alvo, novo caixa e nova liquidação. Distinguir no recibo
  evento alvo de evento criado: este contrato cria zero eventos.
- Erros: EventoInexistente/NaoElegivel/Revertido, SaldoInsuficiente,
  ConfirmacaoNecessaria; nenhum caixa órfão em rejeição.
- Gatilhos verificam tipo, saldo líquido do evento e capacidade original do
  caixa. Caixa de operação já concluída não admite nova conciliação.
- Extremos: pagamentos parciais em chamadas distintas, saldo zero, pagamento
  após estorno parcial, corridas concorrentes. Nova chave é nova intenção;
  não deduzir duplicidade só porque valor/data coincidem. Exigir que o chamador
  preserve a chave para impedir repetição acidental da mesma intenção.

### 8.4 estornar_liquidacao

```python
estornar_liquidacao(*, chave: str, liquidacao_id: int, valor_centavos: int,
    natureza: NaturezaEstorno, motivo: str, data_estorno: date,
    confirmar_datas_divergentes: bool) -> ResultadoOperacao
```

- Todos obrigatórios; recebe magnitude positiva. Não recebe tipo/categoria
  substitutos; descrição de caixa padronizada a partir do ID da liquidação,
  natureza e motivo, com regra determinística e versionada no contrato.
- Regra de descrição v1 APROVADA: `Estorno L#{liquidacao_id} [{natureza}]: {motivo_normalizado}`.
  Usar o ID positivo da liquidação, natureza canônica e motivo em NFC/trim,
  preservando seu conteúdo interno. Não incluir relógio ou IDs aleatórios.
  Conferir o mesmo texto persistido na recuperação do recibo; não regenerar
  com dados financeiros correntes. Exemplo: `Estorno L#42 [devolucao_real]: Produto devolvido pelo cliente`.
- Pré-condições: liquidação existente de evento manual não revertido; caixa
  original positivo; magnitude <= valor líquido restante da liquidação.
  Devolução real e correção seguem datas diferentes da seção 5.
- Consulta operações, liquidação, evento/competência, reversões, caixa original,
  categorias e _hibrido_liquidacoes; escreve operação, caixa negativo e estorno.
- SQL: INSERT operação `estornar_liquidacao`; INSERT contramovimento
  `valor_centavos=-magnitude`, preservando tipo, categoria_id e texto de categoria
  do caixa original; projetar REAL negativo; INSERT estorno com liquidação,
  caixa negativo, natureza/motivo; conferir vínculo único e magnitude; concluir.
- Resultado: evento alvo, liquidação alvo, novo caixa e estorno. Não cria nova
  liquidação nem altera a original. IDs alvo versus novos são papéis definidos
  pela operação, não somente pela presença nas tuplas.
- Erros: LiquidacaoInexistente, EventoNaoElegivel/Revertido, EstornoExcessivo,
  DataInvalida, ConfirmacaoNecessaria. Mesmo motivo não substitui chave.
- Gatilhos exigem classificação registrada original, natureza válida, líquido
  não negativo e unicidade do caixa de estorno; não usar categoria corrente.
- Extremos: vários estornos parciais acumulados; integral seguido de novo
  estorno rejeitado; renomeação/reclassificação posterior não muda o caixa
  original. Devolução de despesa permanece despesa negativa; de receita,
  receita negativa. Isso evita receitas/despesas artificiais.

### 8.5 reverter_evento

```python
reverter_evento(*, chave: str, evento_id: int, data_reversao: date,
    motivo: str) -> ResultadoOperacao
```

- Todos obrigatórios. Sem valor parcial; data de reversão é explícita, não
  inferida da data de caixa, vencimento ou relógio.
- Pré-condições: evento manual confirmado, não revertido, liquidação líquida
  exatamente zero; categoria corrente do mesmo tipo. Um evento originalmente
  pago pode ser revertido após estorno integral, preservando todas as linhas.
- Consulta operações, eventos_classificacao_atual, categorias, reversões e
  _hibrido_liquidacoes; escreve operação e reversão.
- SQL: INSERT operação `reverter_evento`; INSERT reversão com evento_id explícito,
  categoria corrente, operação, `data_competencia=data_reversao` e motivo;
  conferir uma reversão/nenhum caixa; concluir.
- Resultado: evento alvo e reversão; sem novo evento/caixa. O significado
  econômico é compensação integral do evento na data informada; implementação
  futura de relatório deverá subtrair esse valor, sem apagar o original.
- Erros: EventoJaRevertido, EventoAindaLiquidado, EventoNaoElegivel,
  CategoriaIncompativel. Mesma chave retorna replay; outra chave para o mesmo
  evento revertido é erro, não nova reversão.
- Gatilhos: tr_reversoes_bi, CHECKs e UNIQUE(evento_id). Não fechar a operação
  antes de inserir a reversão. F01 impede FK nula/omitida autoatribuída.
- Extremos: estorno parcial não basta; evento nunca pago; evento histórico
  negativo sem origem manual é inelegível, não convertido automaticamente.

### 8.6 reclassificar_evento

```python
reclassificar_evento(*, chave: str, evento_id: int, categoria_nova_id: int,
    motivo: str, categoria_anterior_esperada_id: int | None = None
    ) -> ResultadoOperacao
```

- Opcional funciona como controle de concorrência de intenção: quando presente,
  deve coincidir com categoria corrente sob o lock; divergência é conflito de
  estado, não aplicar mudança sobre classificação inesperada.
- Pré-condições: evento manual confirmado não revertido; categoria nova
  existente, diferente da corrente e com mesmo tipo econômico. Pode estar
  parcial/integralmente liquidado: caixa permanece com classificação registrada.
- Consulta operações, eventos_classificacao_atual, categorias, reversões e
  histórico de reclassificações; escreve operação e histórico de reclassificação.
- SQL: obter categoria corrente; INSERT operação `reclassificar_evento`;
  INSERT histórico com anterior efetivamente lida e nova, motivo e operação,
  ID sequencial automático; conferir a nova linha e categoria corrente; concluir.
  Nunca UPDATE na categoria/tipo do evento ou no caixa.
- Resultado: evento alvo e reclassificação. Categoria anterior/nova podem ser
  recuperadas da linha imutável, não da visão corrente depois de outro histórico.
- Erros: EventoRevertido/NaoElegivel, CategoriaInexistente/Incompativel,
  ConflitoEstado, ReclassificacaoSemAlteracao
  conforme D04 aprovada. A mesma categoria deve ser rejeitada antes de criar
  operação ou histórico. Replay é resolvido antes dessas validações dinâmicas.
- Gatilhos exigem categoria anterior corrente, nova do mesmo tipo, operação
  aberta, sequência crescente e histórico imutável. Mudança do tipo econômico
  não é reclassificação permitida; exigiria outra intenção/contrato aprovado.

## 9. Compatibilidade com o legado e relatórios

`adicionar_lancamento` (`banco.py:448`) insere exclusivamente caixa REAL por
SELECT da categoria, sem validações equivalentes às novas operações. Mantém
novos campos nulos. Não se deve chamá-lo de dentro do serviço híbrido, pois
abre e confirma outra conexão. Não reinterpretar seu histórico como competência.

`atualizar_lancamento` (`banco.py:826`) e `excluir_lancamento` (`:885`) continuam
disponíveis somente para linhas elegíveis: sem operação híbrida e sem vínculo
como caixa de liquidação, estorno ou origem `lancamento_legado_id`. Os gatilhos
já bloqueiam as demais, inclusive SQL direto e REPLACE nas chaves cobertas.
Uma pré-checagem futura de UI melhora a mensagem, mas não substitui a proteção
transacional. Eventos, liquidações e históricos são imutáveis: corrigir por
estorno/reversão/reclassificação, sem DELETE/UPDATE financeiro.

Categorias usadas não podem mudar de tipo/ID ou ser excluídas. Reclassificar
eventos para outra categoria existente do mesmo tipo não libera a categoria
antiga, pois o histórico continua referenciando-a. Renomear é permitido; o
texto de caixa registrado fica intacto, embora algumas consultas legadas usem
JOIN com o nome atual. Troca de tipo de categoria usada não é oferecida pelos
seis serviços; criar outra categoria/reclassificar requer fluxo próprio.

Identificação: caixa com `operacao_hibrida_id IS NULL AND valor_centavos IS NULL`
pertence ao legado, mas pode estar protegido por referências. Evento com
`origem_tipo IS NULL` é histórico não adotado; não basta ser confirmado para
se tornar manual. Não converter REAL histórico para centavos automaticamente.

Pontos de entrada futuros: `app.py:417` cadastro, `:666` edição, `:884` exclusão,
`:4873` menu de lançamentos; `utils.py:58` lê valor com float e não serve para
alimentar os novos serviços. `app.py:216` e seguintes executam inicialização
no import: testes de serviço não devem importar app. Não há habilitação dos
serviços nem migrações automáticas nesta especificação.

Riscos preexistentes observados estaticamente: `buscar_lancamento` retorna sete
campos (`banco.py:796`), mas o menu de exclusão desempacota seis (`app.py:920`
aproximadamente); edição/exclusão não traduzem explicitamente os ABORTs híbridos
e funções antigas não garantem close em exceções. Esses pontos exigem tarefa
separada antes da exposição de híbridos pela UI; não foram corrigidos aqui.

Dashboard (`banco.py:3376`), resumos mensais (`:689`, `:3534`), categorias
(`:732`, `:756`) e evolução anual (`:3663`) leem `lancamentos.valor`, por tipo
e data de caixa. Continuam executando sem consultar eventos; positivo de
despesa reduz saldo, estorno negativo de despesa reduz despesa líquida e
aumenta saldo. Receita negativa faz o inverso. Competência sem caixa,
reversão e reclassificação não mudam esses totais. Não somar eventos aos
lançamentos no mesmo total: isso duplicaria operações imediatas.

Continuar executando não equivale a relatório híbrido correto: REAL perde
precisão, descrições/formatação podem não explicar negativos, grupos legados
de categoria não refletem necessariamente a classificação corrente do evento,
e correções na data original mudam a leitura de caixa daquele mês. Relatórios
de competência/compromissos e UI para essas distinções ficam para integração
posterior, com política aprovada. Nenhum relatório foi modificado nesta etapa.

## 10. Matriz de testes da fase 3.2B

Matriz originalmente definida na 3.2A e exercitada pelas implementações e pela
consolidação da 3.2B. O resultado final está registrado na seção 13.

Todo teste futuro usa SQLite temporário e KAIRUA_DB_PATH antes de imports;
nenhum importa app ou executa migração na base real. Não usar mocks como prova
de invariantes que dependem do SQLite. As quantidades históricas de testes
nos relatórios não substituem os novos testes dos serviços.

| Camada | Cenários e critérios |
| --- | --- |
| Unitária: moeda | Centavos int; rejeitar bool/float/texto no núcleo; Decimal finito/exato; fração de centavo; 0/-1/M/M+1; projeção não usada no domínio; contexto decimal e formato brasileiro explícitos |
| Unitária: datas/texto | ISO/calendário; 29/02 inválido; date versus datetime; NFC/espaços; motivo vazio; confirmações True/False e bool estrito |
| Unitária: canonicalização | Ordem de kwargs, Decimal convertido antes do núcleo, opcionais null e datas; alterações reais de valor/data/tipo/motivo/confirmação divergem; versão de contrato |
| Integração: cadastro | Receita/despesa confirmada sem caixa; imediata com evento/caixa/liquidação integrais; chaves de origem; nenhum histórico adotado |
| Integração: liquidação | Parcial, integral, excesso, zero, pós-estorno; tipo/categoria; data diferente com/sem confirmação; saldo recalculado; nenhum caixa órfão |
| Integração: estorno | Parcial/integral/acumulado; magnitude negativa rejeitada; duas naturezas e datas; mesma classificação registrada após renomeação/reclassificação; estorno duplicado por replay e excesso por outra chave |
| Integração: reversão | Sem pagamento e pós-estorno integral; pagamento/estorno parcial impedem; repetição com mesma chave recupera, outra chave rejeita; data de reversão e sem caixa |
| Integração: reclassificação | Sequência A→B→A; caixa imutável; anterior esperada divergente; tipo diferente; revertido; mesma categoria conforme D04; replays após novas reclassificações |
| Integração: idempotência | Mesma chave/payload retorna mesmos IDs após efeitos posteriores; mesma chave/outro método/payload rejeita; operação aberta persistida detectada; efeitos faltantes/extras detectados no replay |
| Integração: concorrência | Duas conexões reais, mesma chave igual/diferente; saldo disputado; estornos simultâneos; anterior esperada; lock timeout; perda de resposta após commit sem duplicação |
| Integração: rollback | Injetar falha após cada INSERT, antes/depois de fechar e antes de commit; nenhum efeito/operação persiste; conexão fecha; erro de commit preserva capacidade de recuperar pela chave |
| Integração: IDs/limites | Histórico somente negativo/zero, alocação positiva; lastrowid de cada conexão; saturação AUTOINCREMENT/int64; SUM overflow explícito; não usar fallback float |
| Integração: legado | Cadastro/edição/exclusão elegíveis e funções de inicialização; histórico byte a byte; relatórios de caixa recebem exatamente um movimento por liquidação e um negativo por estorno |
| Adversarial: integridade | SQL direto para efeitos após conclusão, NULLs, tipo/categoria, excesso, UPDATE/DELETE/REPLACE de protegidos; FKs e recursive_triggers nas quatro combinações |
| Adversarial: instalação | Ausência/adulteração de objetos; gatilhos desconhecidos com caixa variada; índices únicos não cobertos e proprietário errado; não chamar migração automaticamente |
| Adversarial: completude | Tentar concluir operação vazia, caixa sem conciliação, estorno sem vínculo, vínculo errado ou efeitos extras: serviço recusa e reverte; SQL externo pode persistir e deve gerar OperacaoIncompleta ao recuperar |

Registro histórico da 3.2A: a orientação abaixo descrevia a cobertura ainda
planejada, não o estado atual. Os testes próprios da 3.2B foram concluídos.

Manter as regressões F01–F04/N01. O teste atual de guarda de operação aberta
é um modelo de teste; a implementação real precisa de testes de falha e commit
próprios. Sucesso de testes com mock não certifica essa garantia.

## 11. Decisões aprovadas e histórico das alternativas

As decisões abaixo são normativas e foram explicitamente aprovadas pelo usuário
no encerramento da 3.2A. Não há decisão D01–D07 pendente.

| Decisão | Status | Regra aprovada |
| --- | --- | --- |
| D01 Precisão monetária | APROVADA | Rejeitar fração de centavo; converter entrada com Decimal; não arredondar silenciosamente. |
| D02 Limite monetário | APROVADA | Magnitudes positivas de 1 a 9223372036854775807 centavos (int64); nenhum teto comercial nesta etapa; centavos inteiros são a fonte autoritativa. |
| D03 Datas | APROVADA | Permitir retroativas e futuras; confirmação explícita quando caixa e competência divergirem; vencimento próprio; reversão na data explicitamente informada; preservar datas/naturezas de estorno existentes. |
| D04 Reclassificação sem mudança | APROVADA | Retornar ReclassificacaoSemAlteracao sem criar operação ou histórico fictício; preservar replay idempotente de alteração já concluída. |
| D05 Idempotência | APROVADA | Chave `kairua:v1:<uuid-em-minusculas>`; textos NFC com espaços das extremidades removidos, preservando conteúdo interno e diferenças significativas; mesma chave para tentativas da mesma intenção; payload diferente gera conflito. |
| D06 Categoria do caixa posterior | APROVADA | Categoria corrente na liquidação; classificação registrada no caixa é preservada; estorno reproduz classificação do caixa original; reclassificações posteriores não alteram caixa histórico. |
| D07 Escopo inicial | APROVADA | Uma liquidação e um caixa novo por chamada que liquide; sem lotes, rateios ou associação a caixa preexistente; preservar capacidade muitos-para-muitos do esquema. |

### Histórico anterior à aprovação

A tabela seguinte preserva alternativas, impactos e recomendações originais;
expressões como "aprovar" ou "decidir" nela descrevem o planejamento anterior,
não reabrem decisões. Em caso de divergência, prevalece a tabela aprovada acima.

| Decisão | Alternativas e impacto | Recomendação e relação com regras aprovadas |
| --- | --- | --- |
| D01 Fração de centavo | Rejeitar; ou arredondar explicitamente HALF_EVEN/HALF_UP. Arredondar altera valor econômico e precisa política/apresentação. | Rejeitar por padrão; conversão exata com Decimal. Se houver arredondamento, exigir contrato explícito antes de codificar. |
| D02 Teto de produto | Usar M técnico; ou teto menor que preserve faixa monetária desejada no legado. Ambos exigem testes de limites. | Manter M como limite técnico documentado; decidir teto comercial antes de expor na UI, sem prometer precisão dos relatórios REAL. |
| D03 Datas econômicas | Permitir futuras/retroativas, ou limites de período; reversão na data original ou data escolhida. Correção de registro afeta caixa do período original por regra existente. | Datas explícitas, confirmação para divergência e sem restrição adicional não aprovada; confirmar política para reconhecimento futuro e período da reversão antes da exposição. Não confundir vencimento com competência. |
| D04 Reclassificação sem mudança | Erro; ou operação concluída sem efeitos. Segunda opção altera o contrato de completude e recibo. | Erro ReclassificacaoSemAlteracao; não criar histórico fictício. Repetição idempotente da mudança anterior continua válida. |
| D05 Chave/formato e texto | UUID com namespace/versionamento e NFC/trim; ou chave opaca/texto literal. Afeta equivalência/retries, não valores. | Aprovar formato e normalização propostos; nunca gerar nova chave dentro de retry. |
| D06 Categoria do caixa posterior | Corrente na liquidação ou inicial do evento. Gatilho exige mesmo tipo, não igualdade com a categoria corrente. | Capturar corrente na liquidação e preservá-la para sempre no caixa; estorno copia original. Alinha classificação corrente da competência e classificação registrada do caixa. |
| D07 Escopo inicial | Uma liquidação por chamada criando caixa; ou rateios/lotes/caixa existente. Segundo exige novos contratos de alocação/recuperação, não necessariamente esquema. | Aprovar escopo simples dos seis serviços; manter capacidade muitos-para-muitos do banco, sem oferecer rateio implícito. |

Confirmação de datas fica registrada no JSON da operação, não como identidade
de pessoa. Se for exigida autoria/identidade externa, justificativa estruturada,
anexos, contas bancárias, período fechado ou autorização para datas retroativas,
o esquema atual não oferece esses campos: especificar outra etapa, sem fingir
que `registrada_em` ou `motivo` atendem requisitos não aprovados.

## 12. Cronograma executado e histórico do planejamento

### Cronograma efetivamente executado

| Etapa | Entrega | Estado atual |
| --- | --- | --- |
| 3.2B.1 | Infraestrutura dos serviços | Concluída e aprovada |
| 3.2B.2 | `registrar_evento_manual` | Concluída e aprovada |
| 3.2B.3A | `registrar_operacao_imediata` | Concluída e aprovada |
| 3.2B.3B | `liquidar_evento` | Concluída e aprovada |
| 3.2B.4 | `estornar_liquidacao` | Concluída e aprovada |
| 3.2B.5 | `reverter_evento` | Concluída e aprovada |
| 3.2B.6 | `reclassificar_evento` | Concluída e aprovada |
| 3.2B.7 | Consolidação integrada | Concluída e aprovada |
| Validação final da 3.2B | Encerramento técnico | APTO |

### Divisão originalmente recomendada — registro histórico

A sequência abaixo foi registrada na 3.2A. O agrupamento de reversão e
reclassificação na 3.2B.5 e a previsão de auditoria na 3.2B.6 pertencem ao
planejamento original, não ao cronograma atual. As autorizações de implementação
ocorreram em tarefas posteriores; o estado concluído é o da tabela acima.

1. **3.2B.1 — infraestrutura do serviço:** aplicar D01–D07 já aprovadas; tipos/erros, Decimal,
   canonicalização, conexão e unidade transacional. Aceitação: rollback/close,
   replay/conflito/concorrência e operação incompleta testados em SQLite real
   temporário, sem tocar funções legadas.
2. **3.2B.2 — competência manual:** registrar_evento_manual e recuperação de
   resultado. Aceitação: confirmado/vencimento/origem, sem caixa e idempotente.
3. **3.2B.3 — caixa e conciliação:** registrar_operacao_imediata e liquidar_evento
   compartilhando auxiliares internos da mesma transação. Aceitação: nenhum
   órfão, datas confirmadas, parcial/integral e concorrência sem excesso.
4. **3.2B.4 — estornos:** duas naturezas e pagamentos parciais. Aceitação:
   negativos do mesmo tipo, limites acumulados, nenhuma receita artificial,
   classificação original e rollback entre caixa/vínculo.
5. **3.2B.5 — reversão/reclassificação:** históricos sem UPDATE financeiro.
   Aceitação: líquido zero, unicidade, sequência, replays após mudanças e
   categoria original/caixa preservados.
6. **3.2B.6 — auditoria do conjunto:** suíte completa e testes adversariais dos
   serviços. Aprovação separada antes de menus/relatórios/adoção de qualquer base.

Não migrar automaticamente ao instalar serviços; a implantação sobre uma base
real é tarefa independente, sem mecanismo de autorização ao banco real nesta
etapa. Nenhuma dessas implementações está autorizada por este documento.

### Revisão de consistência no encerramento da 3.2A — registro histórico

As seis assinaturas continuam compatíveis: valores em centavos, vencimento
obrigatório nos cadastros, confirmações explícitas, data própria de reversão
e categoria posterior resolvida sob lock. Não se alterou assinatura nem regra
financeira. D07 se aplica às chamadas que liquidam; registrar somente competência,
reverter e reclassificar continuam sem criar caixa.

Foram resolvidas as referências desatualizadas a aprovação futura de D01–D07
nas políticas e contratos normativos. As restrições da migração 3 não conflitam
com as regras aprovadas; confirmação de datas, NFC, replay e fração de centavo
são obrigações do serviço, pois o banco não as garante integralmente.

Esclarecimentos técnicos para evitar contradições na implementação:

- D04 exige buscar replay antes de validar a categoria corrente. Só chamadas
  novas sem mudança geram erro, antes do INSERT da operação.
- Recibos podem conter IDs de alvos existentes, mas a contagem de completude
  da seção 7.1 considera apenas efeitos novos daquela operação. As duas
  verificações não podem usar simplesmente o tamanho das mesmas tuplas.
- Replay confere efeitos imutáveis originais; não recalcula saldo líquido nem
  exige categoria corrente antiga. Uma alteração posterior não invalida recibo.
- A pré-condição da migração 3 exige ausência dos objetos que ela cria; não
  pode ser reutilizada para validar a instalação já migrada. A 3.2B.1 usará
  um verificador de leitura próprio, sem chamar o executor de migrações.
- A compatibilidade exige validar a instalação sob a transação antes de
  qualquer escrita; uma verificação preliminar ou cache não substitui essa
  checagem. BEGIN IMMEDIATE precede lookup, validações dinâmicas e efeitos.
- Permitir datas futuras não dispensa confirmar a ocorrência econômica;
  confirmar_ocorrencia continua obrigatório e separado da confirmação de datas.

Tipos/erros, matriz de testes e compatibilidade legada permanecem válidos.
O [plano 3.2B.1](plano_3_2B_1.md) delimita componentes internos de infraestrutura
e seus testes; nenhum dos seis serviços completos pertence a essa etapa.

## 13. Encerramento e validação da 3.2B

- Seis serviços públicos implementados e aprovados, conforme seção 8.
- Testes de integração e concorrência concluídos na consolidação 3.2B.7.
- Validação final: **APTO para encerramento técnico**.
- Última suíte completa: **330 aprovados, 2 ignorados, 0 falhas** (332 testes).
- Testes ignorados: `test_link_em_diretorio_rejeitado` e
  `test_link_simbolico_rejeitado_sem_resolver_alvo`, de `TestInfraestruturaSQLite`.
  Ambos dependem de privilégio de criação de links simbólicos no Windows;
  indisponíveis neste ambiente por **WinError 1314**. Não são testes aprovados.
- Nenhum defeito bloqueante ou importante conhecido.
- Integração com menus, dashboards e relatórios permanece fora do escopo.
- Versionamento da 3.2B ainda pendente; esta atualização documental não inclui
  staging, commit ou push.

### Validação da entrega documental original da 3.2A — registro histórico

O relato abaixo se refere somente à entrega documental original, não à
implementação e à suíte concluídas na 3.2B.

Somente documentação foi criada ou atualizada. Não foram executados testes ou migrações:
nesta entrega os serviços são especificação e não há mudança executável para
validar. A matriz acima define os testes da futura implementação. Realizar
checagem textual de UTF-8/LF, links locais e `git diff --check`; preservar
integralmente AGENTS.md, tests/test_parcelamentos.py e código existente.
