# Politica de backup apos migracao

Antes do cutover, manter backups existentes intactos. Depois, PostgreSQL e a fonte oficial; nao usar JSON versionado no GitHub como banco operacional.

- Backup privado do PostgreSQL, com retencao e restauracao testada em ambiente isolado.
- Preservar apenas arquivos de importacao necessarios para auditoria/reprocessamento e configuracoes nao secretas essenciais.
- Nao incluir historico bruto de posicoes se os eventos finais bastarem para as regras; definir separadamente a necessidade dos PDFs.
- Registrar horario, tamanho, integridade e resultado da restauracao de cada copia.
- Manter pelo menos uma copia fora do projeto Supabase. Nao enviar dados operacionais a repositorio publico.

Retencao, frequencia e destino serao definidos apos medir tamanho e taxa de alteracao do novo banco. Nenhum backup remoto antigo deve ser apagado sem inventario e aprovacao do novo fluxo.
