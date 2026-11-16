# Etapa 3.2B.1 — plano técnico da infraestrutura dos serviços

Status atual: infraestrutura da 3.2B.1 concluída e aprovada. Fase 3.2B concluída
e aprovada, com validação final APTO para encerramento técnico; versionamento pendente.
D01–D07 estão APROVADAS em [contratos_servicos_financeiros.md](contratos_servicos_financeiros.md#11-decisões-aprovadas-e-histórico-das-alternativas).
Referência estrutural: commits f51a7d4, 9d03521 e fe7bb69. Nenhum código ou
migração é implementado por este documento.

## 0. Encerramento da fase 3.2B

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

Os seis serviços públicos estão implementados e aprovados. Os testes de integração
e concorrência foram concluídos. Última suíte completa: **330 aprovados, 2 ignorados,
0 falhas** (332 testes). Os dois testes ignorados dependem de privilégio de links
simbólicos no Windows, indisponível neste ambiente por **WinError 1314**; nomes e
contexto estão na seção 13 de [contratos_servicos_financeiros.md](contratos_servicos_financeiros.md#13-encerramento-e-validação-da-32b).

Nenhum defeito bloqueante ou importante conhecido. Integração com menus, dashboards
e relatórios permanece fora do escopo. Versionamento da 3.2B ainda pendente.

As seções 1–13 preservam o plano original da 3.2B.1 como **registro histórico**.
Expressões como "futuros serviços", "após autorização" e "nenhum serviço completo"
descrevem o escopo daquela etapa quando planejada, não o estado atual da 3.2B.
O cronograma atual é exclusivamente o desta seção e o da seção 12 dos contratos.

## 1. Objetivo e limites

Preparar componentes internos pequenos, testáveis e reutilizáveis para as seis
operações futuras, sem implementar qualquer serviço financeiro completo.
A infraestrutura deve validar entradas, tratar idempotência, controlar conexão
e transação, conferir instalação/efeitos e reconstruir recibos imutáveis.

| Na 3.2B.1, após autorização | Na 3.2B.2 ou posterior |
| --- | --- |
| Tipos, dataclasses imutáveis e catálogo de exceções | registrar_evento_manual completo na 3.2B.2 |
| Validadores puros de centavos, Decimal, datas, textos e chaves | Imediata/liquidação na 3.2B.3 |
| Canonicalização v1 por lista fechada de parâmetros de cada contrato | Estornos na 3.2B.4 |
| Conexão própria, BEGIN IMMEDIATE, rollback/close e controle de operação | Reversão/reclassificação na 3.2B.5 |
| Lookup idempotente, leitura dos efeitos e validadores de completude | Regras dinâmicas e INSERTs financeiros de cada serviço |
| Recuperação de recibos para os seis formatos, em leitura | Menus, adaptador de entrada Rich/locale e apresentação de erros |
| Testes com fixtures sintéticas e produtores de efeitos exclusivos dos testes | Relatórios híbridos, rateios, lotes e adoção de base real |

Não modificar banco.py, migrações 1/2/3, menus, relatórios ou funções legadas
para acomodar a infraestrutura. Não criar novas tabelas ou restrições.
Não fornecer API pública que aceite callbacks arbitrários, SQL, conexão externa
ou caminhos escolhidos por parâmetros financeiros.

## 2. Estrutura proposta de servicos_financeiros.py

Manter um módulo inicial, independente de Rich e de app, com blocos internos:

1. Constantes e tipos: limite M, versão do contrato, tipos econômicos/naturezas
   e mapeamento fechado entre nomes de serviço e tipos do catálogo.
2. Dataclasses de requisição normalizada, operação persistida, efeitos e recibo.
3. Exceções de domínio e tradução limitada de erros SQLite conhecidos.
4. Validação/canonicalização puras, sem abrir conexão no import.
5. Verificação de instalação, lookup da operação e leitura dos efeitos.
6. Validação de completude e reconstrução de recibo.
7. Controle privado da unidade transacional e ciclo de vida da operação.

Auxiliares privados recebem a mesma conexão, sem commit/rollback/close próprios.
O controlador é o único responsável por esses atos. Os futuros serviços
orquestrarão auxiliares internos; não chamarão funções financeiras legadas que
abrem outra conexão. Não criar um framework de plugins/handlers públicos.

Arquivos futuros previstos, somente após autorização: servicos_financeiros.py,
tests/test_infraestrutura_servicos.py e, se a divisão melhorar a leitura,
tests/test_concorrencia_servicos.py. Revisar a necessidade de divisão antes de
adicionar arquivos; não alterar testes preexistentes para mascarar regressões.

## 3. Tipos, dataclasses e exceções

| Tipo proposto | Conteúdo e responsabilidade |
| --- | --- |
| TipoEconomico / NaturezaEstorno / TipoOperacao | Literals/enums fechados conforme esquema, sem criar novos estados persistidos |
| RequisicaoNormalizada | Versão, nome do serviço, tipo do catálogo, chave validada, JSON canônico. frozen; não guardar dict mutável como fonte autoritativa |
| OperacaoPersistida | ID, chave, tipo, requisição canônica e estado lidos do banco; não permite mutação implícita |
| EfeitosOperacao | Tuplas de linhas imutáveis, agrupadas por entidade; separa linhas pertencentes à operação de alvos referenciados |
| ResultadoOperacao | Mesmo contrato da 3.2A: operação/chave/tipo/versão e tuplas ordenadas dos IDs relevantes |

Usar dataclasses frozen, tuplas e valores escalares imutáveis. Não retornar
sqlite3.Row mutável ou conexão. Não colocar saldo atual, categoria corrente ou
indicador de replay no recibo financeiro original. O ID da operação identifica
o recibo sem necessidade de caixa, inclusive em registro só de competência.

Implementar exceção base de domínio e os nomes previstos na seção 3 do contrato.
Os erros de casos financeiros futuros podem existir como tipos sem que sua
regra/operação esteja implementada. ParametroInvalido cobre tipos/formato;
ConflitoIdempotencia cobre mesma chave/outro tipo ou payload;
OperacaoIncompleta cobre operação aberta persistida ou efeitos incompatíveis;
EsquemaIncompativel cobre instalação não suportada.
BancoOcupado deve usar códigos SQLITE_BUSY/SQLITE_LOCKED quando disponíveis,
sem traduzir qualquer OperationalError como lock. FalhaPersistencia conserva
a causa original; não esconder corrupções ou CHECKs desconhecidos.

## 4. Valores e datas

Implementar auxiliares puros, com testes sem SQLite:

- Validação de magnitude: type(valor) is int, excluindo bool; 1..M, com
  M=9223372036854775807. Sem teto comercial. Negativo é representação interna
  de contramovimento, não entrada de magnitude de estorno.
- Conversão Decimal: aceitar Decimal finito ou string decimal de formato
  explícito, sem float, agrupamento de milhares ou interpretação ambígua de
  vírgula. Locale brasileiro ficará no adaptador de UI, fora desta etapa.
- Detectar fração de centavo exatamente; nunca arredondar para tornar uma
  entrada aceitável. 1.000 é exato, 1.001 não é. Validar faixa antes do binding;
  usar contexto decimal local suficiente ou inspeção exata de coeficiente e
  expoente para que truncamento do contexto não faça a comparação passar.
- Limitar esforço de parsing de entradas patológicas com erro de formato
  explícito, sem reduzir o intervalo financeiro aprovado. Nenhum número
  representável válido pode ser rejeitado apenas por um teto comercial oculto.
- Rejeitar NaN/Infinity, bool e float; o adaptador não deve converter float
  para Decimal como reparo. Uma vez recebido Decimal, sua proveniência não é
  recuperável: não alegar que o tipo sozinho detecta essa origem.
- Datas do núcleo: type(data) is date; rejeitar datetime. Adaptador ISO estrito
  valida calendário e anos 0001..9999; nunca usar hoje como default financeiro.
- Permitir datas futuras/retroativas. Vencimento e reversão permanecem campos
  próprios; os auxiliares não inventam ordem competência/vencimento.
- Normalizar textos com NFC e strip das extremidades; preservar espaços
  internos, caixa e diferenças significativas. Confirmar bools com tipo estrito.

A checagem de confirmação entre datas conhecidas é auxiliar puro reutilizável;
quando a competência vier do banco, será chamada sob a transação pelos serviços
futuros. Regras de natureza/data de estorno continuam no banco e no contrato,
sem produzir contramovimentos nesta etapa. REAL não entra nas contas de domínio.

## 5. Canonicalização determinística v1

Manter descritor fechado dos campos dos seis contratos da seção 8 da 3.2A,
incluindo opcionais explícitos; rejeitar campos desconhecidos, obrigatórios
ausentes e enumerações inválidas. Isso não executa as seis operações.
Mapear registrar_evento_manual para tipo persistido registrar_evento e
registrar_operacao_imediata para registrar_imediata; demais nomes coincidem.

Envelope JSON: versao_contrato, servico, tipo_operacao e parametros. Chave fica
na coluna dedicada, validada separadamente. JSON com sort_keys=True,
separadores compactos e ensure_ascii=False, sem NaN ou floats. Datas ISO,
centavos/IDs inteiros, confirmações bool e opcionais ausentes materializados
como null antes da serialização. Textos normalizados primeiro.

Não incluir saldo, categoria corrente/nomes resolvidos, IDs novos ou relógio.
descricao_caixa=None continua null na requisição; copiar a descrição do evento
é efeito futuro, não normalização dinâmica. Categoria anterior esperada=None
também permanece null, não é substituída pela categoria encontrada no banco.

Criar exemplos dourados de JSON, incluindo acentos, forma Unicode decomposta,
espaços, kwargs em outra ordem e diferenças reais de intenção. Não alterar o
algoritmo v1 depois de publicado sem plano de compatibilidade/versionamento.

## 6. Chaves e recuperação idempotente

Chave válida: prefixo exato kairua:v1: e UUID textual canônico com hífens e
letras minúsculas. Validar por parsing e comparação com a representação
canônica, sem converter maiúsculas ou variantes para esconder chave inválida.
A chave é identificador, não texto descritivo; NFC/strip aplica-se aos textos
de domínio, sem reparo silencioso do formato da chave. Não impor versão UUID
específica além da regra aprovada; chamador gera a chave, serviço não regenera.

Após lock, buscar chave e comparar tipo e JSON canônico exatos:

| Situação | Resultado do componente interno |
| --- | --- |
| Ausente | Sinalizar operação nova; ainda sem criar efeito financeiro |
| Mesmo tipo/payload, concluida | Ler e validar os efeitos; reconstruir recibo |
| Chave com outro tipo/payload | ConflitoIdempotencia; nenhuma escrita |
| Mesma intenção com operação aberta persistida | OperacaoIncompleta; não retomar nem corrigir automaticamente |
| Concluida sem efeitos esperados ou com efeitos extras | OperacaoIncompleta; não retornar sucesso |

Replay precede qualquer validação financeira dinâmica: evento pago/revertido ou
reclassificado depois não invalida a operação original. D04 só gera erro para
uma intenção nova sem mudança, antes de inserir operação. Comparar a identidade
do payload antes de julgar a elegibilidade corrente.

## 7. Conexão e unidade transacional

Abrir conexão própria via banco.abrir_conexao(), respeitando KAIRUA_DB_PATH.
Não alterar a função central ou os PRAGMAs das conexões legadas. Nenhuma conexão
ou escrita no import. Habilitar/confirmar foreign_keys e recursive_triggers
antes de BEGIN, na conexão própria. Preservar timeout padrão nesta primeira
infraestrutura, com erro BancoOcupado; não introduzir retry automático ilimitado.
Testes podem reduzir timeout via fábrica privada substituída, sem API pública.

Fluxo privado previsto:

1. Validar/canonicalizar antes de abrir conexão.
2. Abrir/configurar, BEGIN IMMEDIATE e verificar instalação na mesma conexão.
3. Resolver idempotência. Em replay, não inserir nada e liberar a transação de
   leitura sob lock, fechando conexão; retornar somente após liberação bem-sucedida.
4. Para intenção nova, o futuro serviço valida alvos sob lock; só então o
   componente interno insere operacao_hibrida aberta com INSERT simples.
5. O futuro serviço produz efeitos usando a mesma conexão e IDs definitivos.
   Na 3.2B.1 não existe produtor financeiro de produção; fixtures de teste
   exercitam o controlador privado sem se tornar API financeira pública.
6. Conferir efeitos exatos, fechar operação com UPDATE aberta→concluida e
   rowcount=1; conferir que não há operação criada nesta unidade ainda aberta.
7. Construir recibo interno validado, commit e só depois entregá-lo ao chamador.
8. Em qualquer falha, rollback integral se transação ainda ativa e close em
   finally. Fechar também se configuração, BEGIN, lookup, replay ou commit falhar.

Nenhum auxiliar faz commit. Não expor contexto que permita sair normalmente
deixando operação aberta: o controlador não confirma se a guarda não passar.
Não criar operação fictícia concluída para testar o caminho feliz. Usar efeitos
reais sintéticos em testes, escritos diretamente pelo fixture apropriado.
Operações abertas preexistentes não são concluídas/apagadas em lote.

Commit com resultado incerto exige recuperação pela mesma chave em outra
chamada, sem gerar nova intenção. Um erro de rollback/close não deve ocultar
a exceção original; registrar causas técnicas e não informar sucesso prematuro.
Não prometer rollback de commit que já foi efetivado.

## 8. Compatibilidade do esquema instalado

Verificador somente de leitura, sob BEGIN IMMEDIATE, antes do primeiro INSERT.
Exigir histórico suportado 1/2/3 e nomes do catálogo; rejeitar ausência,
divergência ou versão futura ainda não suportada. Conferir tabelas, colunas,
PKs, FKs, CHECKs, índices e os 45 gatilhos/visões aprovados.

Não chamar aplicar_migracoes nem validar_migracao_3: a pré-condição de migração
exige ausência dos objetos novos, oposta à situação operacional. Também não
chamar inicializadores legados ou executar DDL de sondagem na instalação.

Usar manifesto confiável do esquema aprovado, metadados PRAGMA de leitura e
DDL confiável para validar CHECKs/corpos de gatilho, sem parser SQL improvisado.
Preparar o manifesto a partir dos objetos aprovados e conferi-lo em fixture
temporária; não aprender a expectativa a partir da própria base inspecionada.
Comparações conservadoras de DDL devem documentar rejeição de equivalentes,
sem usar normalização que altere strings/literais SQL. Resolução de nomes deve
respeitar NOCASE do SQLite, mantendo proprietário e atributos estruturais.

Conservar a política F02/F04/N01: índices adicionais não únicos são permitidos;
unicidades só se cobertas; desconhecidos em gatilhos de tabelas protegidas são
incompatíveis. O manifesto deve reconhecer gatilhos instalados aprovados e
recusar extras, não rejeitar todos os gatilhos como fazia a pré-condição.

Uma tabela de versões isolada não prova integridade. Não fazer scan global
para converter/limpar histórico nem ativar foreign_key_check global como
reparo implícito. Validar dados relacionados à operação quando necessário.
Não manter cache global que dispense a verificação após mudança de banco ou
esquema; otimização futura exige chave e invalidação explícitas.

## 9. Completude dos efeitos

Implementar leitores e validadores internos de leitura dos seis perfis, sem
escritas financeiras. Usar contagens e somas inteiras exatas e a requisição
original, não apenas IDs fornecidos por um callback.

| Perfil | Pertencimento e validação estrutural mínima |
| --- | --- |
| registrar_evento | Um evento dessa operação com origem/manual/confirmação, campos da requisição e chave de origem esperada; nenhum outro efeito |
| registrar_imediata | Um evento/um caixa positivo dessa operação; exatamente uma liquidação entre ambos pelo valor integral; datas/valores/tipo conforme requisição |
| liquidar_evento | Zero eventos novos; um caixa positivo/uma liquidação ligada ao evento alvo e ao valor recebido; nenhuma outra conciliação ou histórico da operação |
| estornar_liquidacao | Um caixa negativo/um estorno ligado à liquidação alvo; magnitude, natureza, motivo e data compatíveis; classificação igual ao caixa original |
| reverter_evento | Uma reversão ligada ao evento alvo, data e motivo recebidos; nenhum caixa/competência novos |
| reclassificar_evento | Uma linha de histórico ligada ao alvo, nova categoria/motivo e anterior persistida compatíveis com a operação; nenhum caixa/competência novos |

Ler evento/caixa pela coluna de operação; liquidações pela operação do caixa
positivo; estornos pela operação do caixa negativo; reversões/reclassificações
pela própria operação. Consultar todas as famílias para rejeitar efeitos extras.
Vínculos em direção inversa também precisam ser conferidos: nenhum caixa desta
operação pode estar sem a conciliação exata que o perfil exige.

Separar dois momentos: antes do commit novo, serviço futuro valida saldo atual,
categoria corrente e elegibilidade e o controlador confere efeitos. Em replay,
conferir somente invariantes originais imutáveis, sem recalcular liquidação
líquida atual ou comparar categoria com a visão corrente. Estornos/liquidações
posteriores, reversões e novas reclassificações são efeitos de outras operações.
Reversão original usa o valor imutável do evento; não exigir que seu histórico
de pagamentos/estornos esteja vazio se o líquido era zero no momento válido.

O banco não atesta sozinho essas cardinalidades; nenhuma operação vazia pode
ser concluída pelo controlador. Perfil desconhecido falha fechado. Novos lotes
exigirão contrato novo, não restrições únicas adicionais no esquema existente.

## 10. Recibos imutáveis

ResultadoOperacao preserva as seis tuplas do contrato 3.2A. Seus papéis:

| Operação | IDs relevantes no recibo |
| --- | --- |
| Registro sem caixa | evento criado |
| Imediata | evento, caixa e liquidação criados |
| Liquidação | evento alvo; caixa e liquidação criados |
| Estorno | evento/liquidação alvos; caixa e estorno criados |
| Reversão | evento alvo; reversão criada |
| Reclassificação | evento alvo; reclassificação criada |

As outras tuplas são vazias. Ordenar IDs para recuperação determinística; alvo
referenciado não conta como efeito novo. Recibo original e replay devem ser
iguais, inclusive depois de alterações posteriores permitidas. Não retornar
nomes correntes, saldos ou dados de joins mutáveis como snapshot histórico.
Não adicionar tabela de respostas: os dados necessários já estão nas linhas
imutáveis e na requisição canônica. Encontrar um recibo incompleto é erro,
não ocasião para reconstruir efeitos escrevendo dados faltantes.

## 11. Plano original de testes da 3.2B.1 — registro histórico

| Camada | Escopo 3.2B.1 e evidência |
| --- | --- |
| Unitária | Todos os tipos/formatos; Decimal exato e extremos int64; contexto pequeno não pode arredondar entrada para aceitável; Unicode NFC/trim e conteúdo interno; datas futuras/retroativas/bissextas; chave inválida; bool versus int; exemplos dourados JSON |
| Integração: instalação | Criar catálogo aprovado somente em temp; instalado aceito; versão ausente/futura, objeto removido, CHECK/trigger adulterado e unicidade extra recusados; grafias e proprietário; índice não único extra aceito |
| Integração: ciclo de vida | Abrir/configurar/BEGIN/guardar/concluir/commit/close; replay sem escrita; falhas em cada etapa, incluindo guardas e commit; nenhum aberto/efeito parcial persiste |
| Integração: recibos | Fixtures diretas para seis perfis; recuperação sem serviço completo; efeitos faltantes/extras/vínculo errado rejeitados; replay após mudança posterior mantém mesmo recibo |
| Integração: legado | Fotos das linhas sintéticas antes/depois da infraestrutura; nenhuma inicialização/conversão de legado; abrir conexão não migra; import não abre banco |
| Concorrência | Duas conexões independentes ao mesmo arquivo temporário, sincronizadas com eventos/barreiras; mesmo payload/chave retorna mesmo recibo; payload diferente conflita; segunda escrita espera ou dá BancoOcupado; timeout limitado sem sleep como prova |
| Adversarial | Operação aberta persistida; operação concluída vazia; callbacks de teste tentam efeitos incompletos/extras; FK/recursive_triggers nas quatro combinações para as proteções existentes; produção confirma ON em sua conexão própria |

Fixtures podem executar migrações exclusivamente em diretórios temporários com
KAIRUA_DB_PATH definido antes dos imports. Nenhuma leitura/import de app,
nenhuma migração na base real. Testes de concorrência nesta etapa usam produtores
de fixture, não anunciam cobertura de regras de saldo dos serviços ainda ausentes.
Testes específicos de saldo, estorno, D04 e D06 operacionais ficam com os serviços
correspondentes; os auxiliares de validação já cobrem suas entradas nesta etapa.

Não tornar o teste de rollback uma exceção que ele próprio lança antes da
guarda: exercitar a guarda real da infraestrutura. Mocks só para injeção
controlada de falhas; transações, PRAGMAs, gatilhos e locks com SQLite real
temporário. Rodar testes direcionados e suíte completa, preservando F01–F04/N01.

## 12. Critérios originais de aceitação da 3.2B.1 — registro histórico

1. Nenhum dos seis serviços completos existe, nenhum menu o chama e nenhum
   import inicializa/migra o banco. Arquivos fora do escopo e protegido intactos.
2. Centavos int64 exatos, Decimal sem fração de centavo e datas válidas passam;
   float/bool monetário, overflow e frações são rejeitados antes de escrita.
3. Canonicalização reproduz exemplos fixos; mesma intenção normalizada é igual,
   diferenças significativas geram payload diferente. Chave segue D05 exatamente.
4. Instalação aprovada é aceita; versões/objetos incompatíveis são rejeitados
   antes de INSERT, sem executar migrações ou reparar dados.
5. Toda tentativa começa com BEGIN IMMEDIATE na conexão própria e termina em
   commit completo ou rollback integral; close comprovado em todas as saídas.
6. Nenhum aberto ou conjunto incompleto de efeitos produzido pelo controlador
   pode persistir; falhas em cada fronteira de escrita deixam snapshots intactos.
7. Seis perfis de fixtures recuperam recibos idênticos após replay; operações
   abertas, vazias, conflitantes ou mal vinculadas geram erros explícitos.
8. Concorrência real prova serialização e idempotência, com timeout finito;
   nunca gerar outra chave nem repetir apenas o último INSERT.
9. Testes direcionados e suíte completa terminam sem falhas; skips têm motivo
   registrado. Testes não disponíveis por ambiente não são declarados aprovados.
10. git diff --check limpo; UTF-8/LF; AGENTS.md e tests/test_parcelamentos.py
    preservados; entrega de arquivos/testes/riscos sem commit ou push não autorizado.

## 13. Riscos preservados e histórico da sequência de execução

Limitações mantidas: REAL legado não é preciso para toda a faixa aprovada;
SUM SQLite pode estourar agregações globais; SQL externo pode persistir operação
aberta/incompleta; manifesto conservador pode recusar DDL equivalente. Nenhum
serviço pode prometer proteção contra remoção deliberada dos gatilhos por DDL
externo concorrente fora do contrato operacional.

No planejamento original, a 3.2B.1 dependia somente do esquema aprovado e das decisões
registradas. A sequência prevista, hoje concluída, era: implementar
em pequenas mudanças: tipos/validadores e testes; canonicalização; verificador
de instalação/leitores; guardas/recibos; controlador transacional e concorrência.
Revisar cada parte sem integrar app. Essa ordem não autoriza encerrar com uma
infraestrutura que confirme operações vazias.

O planejamento original previa o primeiro produtor financeiro real na 3.2B.2 e
agrupava os demais nas etapas 3.2B.3–5. A execução concluída desdobrou imediata e
liquidação em 3.2B.3A/3.2B.3B, reversão em 3.2B.5 e reclassificação em 3.2B.6,
seguidas da consolidação 3.2B.7, conforme seção 0. A infraestrutura e seus testes
foram reaproveitados, e as regras dinâmicas receberam testes específicos nos serviços.
A integração de UI deve corrigir
em tarefa autorizada as limitações legadas relatadas na 3.2A. Adoção de qualquer
base real, relatórios e políticas adicionais continuam tarefas separadas.

Registro histórico da entrega documental original: não executar testes, código financeiro ou migrações;
verificar somente texto, UTF-8/LF, hashes dos protegidos e git diff --check.
Naquela entrega, a implementação da 3.2B.1 ainda aguardava autorização explícita
do usuário. Hoje está concluída e aprovada, conforme o status da seção 0.
