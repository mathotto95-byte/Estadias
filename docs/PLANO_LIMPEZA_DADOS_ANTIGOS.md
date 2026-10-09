# Plano de limpeza dos dados antigos

Status: inventario inicial. Nenhuma exclusao autorizada antes do cutover validado.

| Item | Classificacao atual | Condicao para excluir |
| --- | --- | --- |
| `data/database/estadias.sqlite3` e arquivos WAL/SHM | PRECISA CONFIRMACAO | PostgreSQL em producao validado; identificar banco ativo e manter copia de seguranca |
| `backups/estadias_latest.json`, `backups/estadias_previous.json`, `backups/_healthcheck.json` versionados | PRECISA CONFIRMACAO | Inventario da branch e destino; novo backup restauravel |
| Backups remotos GitHub, Supabase e ZIP externos | PRECISA CONFIRMACAO | Identificar proprietario, conteudo e retencao; nao apagar destinos desconhecidos |
| `mod_estadias_*` no schema atual | PRECISA CONFIRMACAO | Schema novo e Performance validados; listar dependencias SQL antes de DROP |
| Configuracoes, locais, parametros, preferencias e credenciais | PRECISA PRESERVAR | Definir substituto ou reconfiguracao segura |
| `__pycache__` e caches temporarios locais | PODE EXCLUIR | Confirmar que nao sao artefatos necessarios ao deploy |
| CSV/XLSX importados e exportacoes locais | PRECISA CONFIRMACAO | Identificar origem e possibilidade de reimportacao |

Antes da limpeza: registrar contagens, paths absolutos, hash e tamanho; conferir se o recurso esta em uso; criar backup privado; testar restauracao; executar exclusoes em lotes pequenos com verificacao posterior.
