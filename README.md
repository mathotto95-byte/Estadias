# Estadias

Aplicacao independente do modulo Estadias, com banco proprio e backup enxuto direto em arquivo JSON no GitHub.

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
GITHUB_IMPORTS_BACKUP_PATH = "backups/estadias_importacoes_latest.json"

[users]
admin = "admin"
matheus = "123456"
```

O token do GitHub precisa ter acesso ao repositorio `mathotto95-byte/Estadias` e permissao `Contents: Read and write`.

## Backup

O backup GitHub grava dois arquivos JSON:

- Resultado do painel: resultados, conclusoes, auditoria e configuracoes.
- Importacoes normalizadas: LCTE, CONTROL e RASTREADOR, para permitir recalcular com regras novas depois.

O backup automatico salva o JSON de resultado para nao travar o app em alteracoes pequenas. O botao manual `Enviar backup para GitHub` salva resultado e importacoes.

Arquivos gravados:

- `backups/estadias_latest.json`: ultima versao valida do banco.
- `backups/estadias_importacoes_latest.json`: ultima versao das bases importadas normalizadas.
- `backups/history/*.json`: historico com data e hora para evitar que um backup ruim substitua o unico backup bom.

Tambem existe download local em JSON, Excel e ZIP na tela `Backup do Banco`. O ZIP contem tanto o backup de resultados quanto o backup das importacoes. Os paineis de resultado exportam uma aba `periodos_estadia` com chegada, inicio da estadia apos franquia, saida e tempo de estadia por veiculo.
