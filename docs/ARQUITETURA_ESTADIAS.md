# Arquitetura do Estadias

Status: inventario da etapa 0. Nenhum dado ou backup foi removido.

## Estado atual

- `app.py`: autentica, seleciona telas, agenda e prepara backups.
- `src/modules/estadias/page.py`: importa, recalcula, filtra e exporta; ainda coordena persistencia e backup.
- `src/modules/estadias/service.py`: calcula permanencias e cruzamento LCTE/GPS.
- `src/modules/estadias/repository.py`: le e grava LCTE, rastreador, posicoes resumidas e resultados.
- `src/database/connection.py`: usa `DATABASE_URL` PostgreSQL quando presente; caso contrario usa SQLite local.
- `src/database/migrations.py`: cria tabelas legadas `mod_estadias_*` no schema padrao.
- `estadias_app/ots_otd.py`: recebe snapshot OTS/OTD do GitHub e calcula cinco regras durante a leitura da tela.
- `estadias_app/github_backup.py`: gera dois snapshots de resultados/importacoes e marcacoes de analise.
- Projeto `performance/rules.py`: recalcula as mesmas cinco regras e relaciona bases proprias. Este codigo NAO e a fonte oficial futura.

## Fonte oficial pretendida

LCTE + GPS + OTS/OTD -> servico Estadias -> schema PostgreSQL `estadias` -> view somente leitura -> Performance.

O banco PostgreSQL guarda viagens, eventos e resultados calculados. O Performance nao importa copias de viagens nem recalcula regras. Arquivos JSON externos sao apenas entrada temporaria ou backup, nunca a fonte oficial dos resultados.

## Fronteiras de dados

| Classe | Dados atuais | Destino pretendido |
| --- | --- | --- |
| Operacionais | LCTE, rastreador bruto, posicoes resumidas, cruzamento | PostgreSQL; bruto temporario com retencao definida |
| Configuracao | parametros, locais operacionais, preferencias | PostgreSQL; preservar ate confirmar substituto |
| Resultados | estadias, analises, conclusoes, OTS/OTD | PostgreSQL; publicados em view |
| Credenciais | `DATABASE_URL`, token GitHub, usuarios | Secrets; nunca no repositorio |

## Criterios para cutover

Conexao administrativa isolada para DDL; credencial `estadias_app` sem DDL; schema criado e testado em homologacao; importacao LCTE/GPS validada; cinco regras comparadas com casos conhecidos; view lida pelo Performance; backup privado testado com restauracao; app inicia sem SQLite. Somente depois disso inventariar e excluir dados antigos.
