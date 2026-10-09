# Migracao para PostgreSQL/Supabase

Status: planejamento; nenhum SQL foi executado no Supabase.

1. Confirmar `DATABASE_URL` do app e acesso administrativo separado. Nunca registrar URLs ou senhas em logs, commits ou tickets.
2. Criar schema `estadias` em homologacao, com tabelas definidas a partir das consultas reais. Nao copiar historico do SQLite.
3. Criar usuario de runtime `estadias_app` com `USAGE` no schema e `SELECT, INSERT, UPDATE, DELETE` apenas nas tabelas necessarias. DDL fica com credencial administrativa.
4. Alterar repositorios gradualmente para o schema novo; remover DDL automatico da inicializacao do runtime.
5. Importar amostra nova de LCTE, GPS e OTS/OTD; conferir contagens, deduplicacao, datas/timezone, permanencias e resultado das cinco regras.
6. Criar view somente leitura para Performance e comparar seus indicadores com o Estadias.
7. Testar inicio, importacao, calculo, exportacao, permissao e recuperacao de backup em homologacao.
8. Publicar cutover somente apos aprovar testes. Desativar fallback SQLite e calculo paralelo no Performance no mesmo corte controlado.
9. Executar inventario de dados e backups antigos antes de qualquer exclusao.

O usuario informou que criou um Supabase novo e fez o link. O ambiente local ainda nao tem `DATABASE_URL`, entao a conexao remota nao foi validada nesta tarefa. O repositorio contem alteracoes locais ainda nao publicadas.

## Preparacao administrativa (sem copiar dados)

O codigo PostgreSQL usa `search_path=estadias`; ele nao cria tabelas na inicializacao do app. Execute `scripts/init_postgres_schema.py` com `ESTADIAS_ADMIN_DATABASE_URL` apenas no ambiente do processo administrativo. O comando cria o schema e as tabelas atuais vazias, sem tocar em `public` nem importar historico. Nao passe a URL como argumento, nao registre o terminal e nao a envie por mensagem.

Somente apos essa etapa configure `DATABASE_URL` para o app com um usuario de runtime que tenha `USAGE` no schema e permissoes de leitura/escrita necessarias, sem DDL. A URL so e usada quando `ESTADIAS_POSTGRES_ENABLED = "SIM"` nos Secrets; antes disso o app continua no SQLite atual. Confirme `current_schema() = 'estadias'`, conte as tabelas e teste uma importacao pequena. O app bloqueia o inicio se o schema/tabelas minimas nao existirem e nao restaura automaticamente backups GitHub no PostgreSQL.

Esta estrutura e uma etapa de compatibilidade com o modelo atual, nao o modelo final de viagens/eventos/resultados. A view Performance, o usuario restrito e o novo backup ainda estao pendentes. Nao executar cutover ou limpeza antes desses itens e dos testes integrados.
