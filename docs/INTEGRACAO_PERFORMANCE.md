# Integracao com Performance

Estado atual: Performance importa snapshots LCTE, OTS/OTD e Estadias e recalcula as cinco regras em `performance/rules.py`. O Estadias calcula regras equivalentes em `estadias_app/ots_otd.py`. Ha duplicidade e possibilidade de divergencia.

Destino: resultados persistidos no schema PostgreSQL `estadias`, com view `estadias.vw_performance_indicadores` de leitura somente. Performance consulta essa view filtrada/paginada, sem importar copias operacionais nem gravar no schema Estadias. A view deve usar `viagem_id` estavel, placa, NF, origem, destino, tempos, valor, cinco resultados e data de atualizacao.

Nao criar a view antes de finalizar as tabelas de resultado e a semantica das regras. No cutover, comparar por viagem os indicadores das duas aplicacoes, desativar o calculo antigo e manter permissao `SELECT` para o usuario do Performance. Nenhuma credencial deve ser compartilhada no codigo ou exportada para GitHub.
