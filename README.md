# Estadias

## OTS e OTD

O Estadias calcula a permanência pelo LCTE e rastreador e lê diretamente `backups/ots_otd_latest.json` do repositório `mathotto95-byte/OTSeOTD`. O código de sete dígitos da Observação/Monitoramento liga o agendamento; NF + placa identificam a viagem e as chegadas GPS. Vínculos duplicados ou ausentes ficam sem classificação e mostram o motivo. Não é necessário usar PerformanceRW.

O mesmo `GITHUB_TOKEN` do Estadias é usado para ler OTS/OTD. Ele precisa ter `Contents: Read` também no repositório `mathotto95-byte/OTSeOTD`; não há segundo token ou seção de Secrets.

Após publicar o backup no OTS/OTD, use **Atualizar OTS/OTD** no Estadias. O backup recebido fica em memória na sessão; uma nova sessão lê novamente o último backup. Os resultados GPS e o banco OTS/OTD permanecem separados.

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
GITHUB_BACKUP_BRANCH = "backup-data"
GITHUB_AUTO_BACKUP = "SIM"
GITHUB_BACKUP_PATH = "backups/estadias_latest.json"
GITHUB_IMPORTS_BACKUP_PATH = "backups/estadias_importacoes_latest.json"

[users]
admin = "defina-uma-senha-forte"
matheus = "defina-outra-senha-forte"
```

O token do GitHub precisa ter acesso ao repositorio `mathotto95-byte/Estadias` e permissao `Contents: Read and write`.
O app e publicado da branch `main`; os backups ficam na branch `backup-data` para nao reiniciar o Streamlit a cada gravacao. `GITHUB_BRANCH = "main"` antigo pode ser removido dos Secrets.

Na tela **Estadias**, os horários OTS/OTD e as regras são calculados a partir do backup recebido e das chegadas GPS atuais. A tela **OTS e OTD** permite consultar e exportar a classificação. A ausência de horário GPS mantém a regra dependente dele como `Sem informação`.

## Arquivos de backup

O backup GitHub grava dois arquivos JSON:

- Resultado do painel: resultados, conclusoes, auditoria e configuracoes.
- Importacoes normalizadas: LCTE e RASTREADOR, para permitir recalcular com regras novas depois.

O backup automatico salva o JSON de resultado para nao travar o app em alteracoes pequenas. O botao manual `Enviar backup para GitHub` salva resultado e importacoes.

Arquivos gravados:

- `backups/estadias_latest.json`: ultima versao valida do banco.
- `backups/estadias_importacoes_latest.json`: ultima versao das bases importadas normalizadas.
- `backups/history/*.json`: historico com data e hora para evitar que um backup ruim substitua o unico backup bom.

Tambem existe download local em JSON, Excel e ZIP na tela `Backup do Banco`. O ZIP contem tanto o backup de resultados quanto o backup das importacoes. Os paineis de resultado exportam uma aba `periodos_estadia` com chegada, inicio da estadia apos franquia, saida e tempo de estadia por veiculo.
