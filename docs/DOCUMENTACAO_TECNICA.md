# Documentação técnica — ObraCaixa

> Nome original do projeto: *Controle Financeiro do Pedreiro*.

## 1. Visão geral

Sistema local de fluxo de caixa e controle de obras, em Python com Tkinter (apenas
biblioteca padrão). Registra receitas (acordos e pagamentos) e despesas (gastos e
parcelamentos) e mantém o saldo em caixa e os valores a receber e a pagar.

## 2. Arquivos de dados

| Arquivo | Conteúdo |
|---|---|
| `transacoes.json` | Todas as entradas, saídas, ajustes e acordos de obra. |
| `pendencias.json` | Parcelas futuras, em `a_pagar` e `a_receber`. |
| `agenda.json` | Obras agendadas, agrupadas por mês (`AAAA-MM`). |

A pasta é definida por `pasta_dados()` em `app.py` (ver README).

## 3. Lógica de dados (`FinanceiroBase`)

### 3.1 Tipos de transação (`tipo`)

| Tipo | Efeito no saldo | Efeito no "acordado / a receber" |
|---|---|---|
| `entrada` | Aumenta | Soma ao recebido se a categoria for *Serviço* |
| `pagamento_parcial` | Aumenta | Soma ao valor total recebido |
| `saida`, `saida_parcela` | Diminui | Gasto da obra relacionada |
| `agendamento` | Nenhum (valor 0) | Soma o valor acordado |
| `agendamento_cancelado` | Nenhum | Ignorado (retira o acordo do "a receber") |
| `ajuste_positivo` / `ajuste_negativo` | Aumenta / diminui | Nenhum |

`valor_a_receber_obras = max(0, valor_acordado - valor_total_recebido)`.

### 3.2 Parcelamento

1. A primeira parcela é gravada como `saida_parcela` (ou `pagamento_parcial`, na entrada),
   junto com `valor_total_compra` e `parcelas_totais`.
2. `adicionar_pendencia_parcelada` cria as `parcelas_totais - 1` restantes em
   `pendencias.json`, com vencimento a cada 30 dias.
3. Na aba *Gerenciar Parcelas*, quitar uma pendência gera uma nova transação e
   remove a pendência da lista.

### 3.3 Migração

`migrar_dados` preenche campos ausentes (obra, descrição, categoria, tipo, parcelas, id,
origem) em registros antigos, evitando `KeyError`.

## 4. Estabilidade da interface

O erro `_tkinter.TclError: Layout SaidaTFrame not found` foi resolvido em etapas:

| Correção | Versão | Motivo |
|---|---|---|
| Registro antecipado do estilo | 3.1 / 3.2 | `ttk.Style()` configurado antes de qualquer widget. |
| Fim do estilo customizado | 3.3 | Removido o estilo `SaidaTFrame`; uso do `TFrame` padrão. |
| Cor de fundo explícita | 3.0+ | `tk.Label` recebe `bg` explícito, pois não herda o fundo do `ttk.Frame`. |

## 5. Cancelamento de acordo (versão 3.4)

Permite cancelar um acordo de obra sem apagar o histórico.

| Função | Descrição |
|---|---|
| `FinanceiroBase.get_acordos_ativos()` | Lista as transações `agendamento` ainda não canceladas. |
| `FinanceiroBase.cancelar_agendamento(nome, transacao_id=None)` | Troca o tipo para `agendamento_cancelado`, marca a descrição com `[CANCELADO]` e sinaliza a agenda. Com nomes repetidos, cancela o mais recente ou o `transacao_id` informado. Retorna a transação ou `None`. |
| `AppFinanceiro.abrir_dialogo_cancelamento()` | Janela com lista dos acordos ativos e confirmação (botão na aba *Agendamento de Obra*). |
| `AppFinanceiro.processar_cancelamento_agendamento(nome, id)` | Executa o cancelamento e atualiza saldo, relatório e lista de obras. |
| `resumo_financeiro()` | Ignora acordos cancelados em `valor_acordado` e `valor_a_receber_obras`. |
| `atualizar_relatorio()` | Mostra a linha como *Acordo Cancelado* / `ACORDO CANCELADO`. |

Regra importante: os pagamentos já recebidos de uma obra cancelada **permanecem no
saldo**, mas deixam de abater o "a receber" das demais obras. Se a mesma obra for
agendada de novo, o novo acordo volta a contar normalmente.

## 6. Empacotamento (Windows)

- Executável: `scripts/build_windows.bat` (PyInstaller, `--onefile --windowed`).
- Não use `--add-data "dados;dados"`: os dados do usuário ficam em `%APPDATA%\ObraCaixa`.
  Com `--onefile`, a pasta interna do executável é temporária e apagada ao fechar o programa.
- Instalador: pode ser criado com Inno Setup apontando para `dist\ObraCaixa.exe`,
  sem copiar a pasta `dados`.
