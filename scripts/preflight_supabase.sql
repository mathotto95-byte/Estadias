-- Somente leitura. Execute no SQL Editor do projeto Supabase Control.
-- Nao retorna credenciais nem dados de viagens.
select current_database() as database_name, current_user as sql_user,
       current_setting('server_version') as postgres_version;

select schema_name
from information_schema.schemata
where schema_name in ('public', 'estadias')
order by schema_name;

select table_schema, table_name
from information_schema.tables
where table_schema in ('public', 'estadias')
  and (table_name like 'mod_estadias_%' or table_schema = 'estadias')
order by table_schema, table_name;

select n.nspname as schema_name, pg_get_userbyid(n.nspowner) as owner
from pg_namespace n
where n.nspname = 'estadias';
