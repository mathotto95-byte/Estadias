-- Execute depois de criar o role LOGIN estadias_backup no painel Supabase.
-- Este role nao recebe acesso ao schema public nem a outras tabelas.
grant usage on schema estadias to estadias_backup;
grant select, insert, update on estadias.resultado_backups to estadias_backup;

create policy estadias_backup_select on estadias.resultado_backups
    for select to estadias_backup using (true);
create policy estadias_backup_insert on estadias.resultado_backups
    for insert to estadias_backup with check (true);
create policy estadias_backup_update on estadias.resultado_backups
    for update to estadias_backup using (true) with check (true);
