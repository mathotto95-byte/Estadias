-- Execute no SQL Editor do projeto Control. Nao altera tabelas existentes.
create schema if not exists estadias;

create table if not exists estadias.resultado_backups (
    slot text primary key check (slot in ('atual', 'anterior')),
    gerado_em timestamptz not null default now(),
    viagens integer not null check (viagens > 0),
    sha256 char(64) not null,
    conteudo bytea not null
);

alter table estadias.resultado_backups enable row level security;
