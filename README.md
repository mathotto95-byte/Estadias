# Estadias

## Resultados do PerformanceRW

Abra **PerformanceRW → Atualizar resultado** para consultar a análise publicada pelo Performance. A associação usa NF + placa exatas; chaves ambíguas e resultados com chegadas diferentes das atuais ficam Sem correspondência. Nenhuma estadia é modificada e nenhuma regra é recalculada neste sistema. A tela mostra as cinco regras, atendimento geral, motivo e data da análise, com exportação CSV.

O token GitHub atual precisa de Contents: Read no repositório `mathotto95-byte/Performance`. Se necessário, configure separadamente:

```toml
[performance_results]
token = "SEU_TOKEN_COM_LEITURA_DO_PERFORMANCE"
```

O resultado é lido de `backups/performance_latest.json` na branch main. Primeiro publique a análise no Performance. Os backups do Estadias passam a incluir as datas de envio para análise em metadados próprios, sem alterar as tabelas; o Performance usa esses envios para calcular o prazo de 15 dias.

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
admin = "admin"
matheus = "123456"
```

O token do GitHub precisa ter acesso ao repositorio `mathotto95-byte/Estadias` e permissao `Contents: Read and write`.
O app e publicado da branch `main`; os backups ficam na branch `backup-data` para nao reiniciar o Streamlit a cada gravacao. `GITHUB_BRANCH = "main"` antigo pode ser removido dos Secrets.

## Resultados do PerformanceRW

Na tela **Estadias**, clique em **Atualizar PerformanceRW** após publicar a análise no Performance. O painel e os arquivos Excel passam a mostrar **Previsão de Carga**, **Agendamento de Carga**, **Data Limite**, **Agenda GFL** e **Dentro da Regra**. Os mesmos campos ficam disponíveis na consulta **PerformanceRW**. A associação reutiliza NF + placa e verifica se as chegadas continuam iguais às da análise publicada. Sem correspondência segura, os prazos ficam vazios e o status é Sem informação. Quando uma viagem possui várias NFs com valores diferentes, a célula identifica o valor de cada NF; não há recálculo das regras no Estadias.

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
