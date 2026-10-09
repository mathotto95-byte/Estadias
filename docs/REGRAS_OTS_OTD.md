# Regras OTS/OTD atuais

Fonte oficial no Estadias: `estadias_app/ots_otd_rules.py`. `estadias_app/ots_otd.py` recebe o snapshot externo e vincula cada viagem antes de chamar as regras. O arquivo `performance/rules.py` contem outra implementacao, com diagnosticos e validacoes manuais adicionais. As duas nao devem ser unificadas por simples substituicao: comparar casos reais e testes antes do cutover.

| Regra | Calculo atual no Estadias |
| --- | --- |
| OTS 2 | Agendamento de Carga <= Previsao de Carga |
| OTS 3 | Chegada GPS na origem <= Agendamento de Carga; usa Previsao quando agendamento falta |
| OTD 1 | Dia do registro OTS/OTD = dia da Emissao NF |
| OTD 2 | Agenda GFL <= Data Limite; chegada GPS dentro do limite pode justificar excecao; domingo exige chegada no proprio dia |
| OTD 3 | Chegada GPS no destino no dia da Data Limite |

Falta de data/horario retorna `Sem informacao` quando a regra nao permite comparacao. A regra agregada retorna `Nao` se alguma falha, `Sim` se todas passam e `Sem informacao` nos demais casos. Vinculo usa monitoramento de sete digitos, NF e placa; vinculos ambiguos nao sao classificados.

Pendente: consolidar o diagnostico e a fila de validacao manual do Performance sem criar segunda regra, depois persistir resultados por viagem no PostgreSQL.
