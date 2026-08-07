# Estadias

Aplicacao independente do modulo Estadias, com banco proprio e backup direto em arquivo JSON no GitHub.

## Deploy no Streamlit

- Repository: `mathotto95-byte/Estadias`
- Branch: `main`
- Main file path: `app.py`

## Secrets

Configure no Streamlit em `Advanced settings > Secrets`:

```toml
GITHUB_TOKEN = "seu_token_novo"
GITHUB_REPOSITORY = "mathotto95-byte/Estadias"
GITHUB_BRANCH = "main"
GITHUB_AUTO_BACKUP = "SIM"
GITHUB_BACKUP_PATH = "backups/estadias_latest.json"

[users]
admin = "admin"
matheus = "123456"
```

O token do GitHub precisa ter acesso ao repositorio `mathotto95-byte/Estadias` e permissao `Contents: Read and write`.

## Backup

O backup GitHub grava:

- `backups/estadias_latest.json`: ultima versao valida do banco.
- `backups/history/*.json`: historico com data e hora para evitar que um backup ruim substitua o unico backup bom.

Tambem existe download local em JSON, Excel e ZIP na tela `Backup do Banco`.
