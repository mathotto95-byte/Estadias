-- Execute uma vez no SQL Editor do projeto Control. Preserva todas as copias existentes.
begin;

alter table estadias.resultado_backups
    drop constraint if exists resultado_backups_slot_check;

alter table estadias.resultado_backups
    add constraint resultado_backups_slot_check
    check (slot in ('atual', 'anterior', 'manual'));

commit;
