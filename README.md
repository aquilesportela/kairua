# Sistema Financeiro Pessoal

Aplicação de gerenciamento financeiro pessoal desenvolvida em **Python**, com banco de dados **SQLite** e interface de linha de comando aprimorada com a biblioteca **Rich**.

O projeto foi desenvolvido para organizar informações financeiras em um único sistema, permitindo gerenciar lançamentos, categorias, cartões de crédito, faturas, parcelamentos e recorrências.

## Funcionalidades

- Cadastro e gerenciamento de receitas e despesas.
- Organização de lançamentos por categorias.
- Gerenciamento de cartões de crédito.
- Controle de faturas, compras e parcelamentos.
- Cadastro e acompanhamento de despesas e receitas recorrentes.
- Relatórios e resumos financeiros.
- Filtros de lançamentos por período e categoria.
- Ordenação de registros por diferentes critérios.
- Persistência local das preferências de ordenação.

## Tecnologias

| Tecnologia | Utilização |
|---|---|
| Python | Desenvolvimento da aplicação |
| SQLite | Persistência dos dados financeiros |
| Rich | Formatação de menus e tabelas no terminal |
| Git | Controle de versões |

## Como executar

**Pré-requisitos:** Python 3 e pip.

Clone o repositório:

```bash
git clone https://github.com/SEU-USUARIO/sistema-financeiro-pessoal.git
cd sistema-financeiro-pessoal
```

Crie o ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente virtual no Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Inicie o aplicativo:

```bash
python app.py
```

O projeto possui rotinas de criação das tabelas SQLite durante a inicialização. A instalação em um ambiente totalmente novo ainda está em validação.

## Privacidade e armazenamento

Os dados financeiros são armazenados localmente em arquivos SQLite.

O repositório não deve incluir bancos de dados pessoais, backups, arquivos de configuração privada ou ambientes virtuais. Esses arquivos são excluídos do versionamento por meio do `.gitignore`.

## Status do projeto

**Em desenvolvimento ativo.**

A aplicação possui os principais módulos de gerenciamento financeiro implementados. A modernização das listagens, relatórios e resumos está em andamento.

## Melhorias planejadas

- Finalizar a padronização visual das listagens.
- Aprimorar dashboards e indicadores financeiros.
- Expandir os testes automatizados.
- Melhorar a documentação técnica e a experiência de instalação.

## Autor

Projeto pessoal desenvolvido para aplicar conhecimentos de programação, banco de dados e engenharia de software.