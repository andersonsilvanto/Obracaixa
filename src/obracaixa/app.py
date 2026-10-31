import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import json
import math 
import platform 

# --- Utilitários ---
def pasta_dados():
    """Pasta onde os JSON ficam gravados.

    - OBRACAIXA_DADOS: caminho personalizado (útil em testes e backups).
    - Executável PyInstaller: %APPDATA%/ObraCaixa (persiste entre execuções;
      a pasta temporária do --onefile é apagada ao fechar o programa).
    - Execução pelo código-fonte: pasta 'dados/' na raiz do projeto.
    """
    personalizada = os.environ.get("OBRACAIXA_DADOS")
    if personalizada:
        return personalizada
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ObraCaixa")
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(raiz, "dados")


PASTA_DADOS = pasta_dados()
ARQ_TRANSACOES = os.path.join(PASTA_DADOS, "transacoes.json")
ARQ_PENDENCIAS = os.path.join(PASTA_DADOS, "pendencias.json")
ARQ_AGENDA = os.path.join(PASTA_DADOS, "agenda.json")

def carregar_json(caminho, padrao):
    # Função para carregar dados JSON, lidando com erros e inicialização
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # Em caso de corrupção, reseta o arquivo e avisa
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(padrao, f, indent=4, ensure_ascii=False)
            messagebox.showwarning("Aviso", f"Arquivo {os.path.basename(caminho)} corrompido e reiniciado. Dados perdidos.")
            return padrao
    else:
        # Se o arquivo não existir, cria com o padrão
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return padrao

def salvar_json(caminho, dados):
    # Função para salvar dados JSON
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

def formata_brl(valor):
    # Formata um valor float para a moeda brasileira (R$ X.XXX,XX)
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def valida_data(data_str):
    # Tenta validar a data nos formatos dd/mm/aaaa, dd-mm-yyyy ou yyyy-mm-dd
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_str, fmt)
        except:
            continue
    return None

def criar_label_entry(frame, texto, linha, tipo="entry", valor_inicial=None, cor_fundo="#E6F7EF", **kwargs):
    # CORREÇÃO: Passa a cor de fundo para a Label tk.Label para evitar conflitos de cor.
    tk.Label(frame, text=texto, font=("Arial", 10), bg=cor_fundo).grid(row=linha, column=0, sticky='w', padx=5, pady=2)
    
    if tipo == "entry":
        widget = tk.Entry(frame, width=50, **kwargs)
        widget.grid(row=linha, column=1, padx=5, pady=2, sticky='ew')
    elif tipo == "text":
        widget = tk.Text(frame, width=50, height=3, **kwargs)
        widget.grid(row=linha, column=1, padx=5, pady=2, sticky='ew')
        
    if valor_inicial:
        widget.insert('end' if tipo == 'entry' else '1.0', valor_inicial)
    
    return widget

# --- Lógica de Dados ---
class FinanceiroBase:
    def __init__(self):
        # Transações são carregadas primeiro
        self.transacoes = carregar_json(ARQ_TRANSACOES, [])
        # Migra os dados antigos antes de qualquer processamento
        self.transacoes = self.migrar_dados(self.transacoes)
        
        self.agenda = carregar_json(ARQ_AGENDA, {})
        # Novo dicionário para armazenar dívidas e créditos parcelados futuros
        self.pendencias = carregar_json(ARQ_PENDENCIAS, {'a_pagar': [], 'a_receber': []}) 

    def migrar_dados(self, transacoes):
        """Atualiza a estrutura de transações antigas para o formato atual, 
        garantindo que todas as chaves existam para evitar KeyErrors."""
        transacoes_migradas = []
        for t in transacoes:
            t['obra'] = t.get('obra', '') 
            t['descricao'] = t.get('descricao', 'Transação antiga sem descrição.')
            t['categoria'] = t.get('categoria', 'Desconhecida')
            t['tipo'] = t.get('tipo', 'saida') 
            
            # Garante que chaves ausentes tenham valores padrão
            t['sub_categoria'] = t.get('sub_categoria', '')
            t['parcelas_totais'] = t.get('parcelas_totais', 1)
            t['parcela_atual'] = t.get('parcela_atual', 1)
            t['valor'] = t.get('valor', 0.0)
            
            # Garante que o valor total de compra exista
            t['valor_total_compra'] = t.get('valor_total_compra', t['valor'])
            # Cria ID para itens antigos se não tiverem um
            t['id'] = t.get('id', datetime.now().strftime("%Y%m%d%H%M%S") + str(hash(json.dumps(t)))) 
            t['origem'] = t.get('origem', 'manual')

            # Correção de tipo para itens antigos que podem ter sido salvos com tipo errado
            if t['tipo'] == 'entrada' and t['origem'] == 'manual' and t['parcelas_totais'] > 1:
                 t['tipo'] = 'pagamento_parcial'
                 
            transacoes_migradas.append(t)
        return transacoes_migradas

    def get_lista_obras(self):
        """Retorna uma lista única de todas as obras registradas."""
        obras = {"N/A - Gasto não relacionado à Obra"}
        
        for t in self.transacoes:
            if t['obra']:
                obras.add(t['obra'])
        
        for mes, lista in self.agenda.items():
            for agendamento in lista:
                 if agendamento['nome']:
                      obras.add(agendamento['nome'])
                      
        return sorted(list(obras))

    def get_resumo_obras(self):
        """Calcula o total de Acordado, Recebido e Gasto por obra."""
        resumo = {}

        for t in self.transacoes:
            obra_nome = t['obra'] if t['obra'] else "N/A - Gasto não relacionado à Obra"
            
            if obra_nome not in resumo:
                resumo[obra_nome] = {
                    'acordado': 0.0,
                    'recebido': 0.0,
                    'gasto': 0.0,
                    'lucro_bruto': 0.0
                }

            if t['tipo'] == "agendamento":
                resumo[obra_nome]['acordado'] += t.get("valor_total_compra", t["valor"])
            elif t['tipo'] in ["entrada", "pagamento_parcial", "ajuste_positivo"]:
                resumo[obra_nome]['recebido'] += t["valor"]
            elif t['tipo'] in ["saida", "saida_parcela", "ajuste_negativo"]:
                resumo[obra_nome]['gasto'] += t["valor"]

        for obra_nome, dados in resumo.items():
             if "N/A" not in obra_nome:
                  dados['lucro_bruto'] = dados['recebido'] - dados['gasto']
             else:
                  dados['lucro_bruto'] = -dados['gasto']
                  
        return resumo


    def salvar(self):
        salvar_json(ARQ_TRANSACOES, self.transacoes)
        salvar_json(ARQ_AGENDA, self.agenda)
        salvar_json(ARQ_PENDENCIAS, self.pendencias)

    def adicionar_transacao(self, transacao):
        # Adiciona uma transação com valores padrão
        transacao_padrao = {
            "obra": transacao.get("obra", ""),
            "data": transacao.get("data", datetime.now().strftime("%Y-%m-%d")),
            "tipo": transacao.get("tipo", "entrada"), 
            "valor": transacao.get("valor", 0.0),
            "descricao": transacao.get("descricao", ""),
            "categoria": transacao.get("categoria", "Outro"),
            "sub_categoria": transacao.get("sub_categoria", ""),
            "parcelas_totais": transacao.get("parcelas_totais", 1),
            "parcela_atual": transacao.get("parcela_atual", 1),
            "valor_total_compra": transacao.get("valor_total_compra", transacao.get("valor", 0.0)),
            "origem": transacao.get("origem", "manual"),
            "id": datetime.now().strftime("%Y%m%d%H%M%S") + str(len(self.transacoes)) # ID simples
        }
        self.transacoes.append(transacao_padrao)
        self.salvar()

    def adicionar_agendamento(self, agendamento):
        data_inicio = valida_data(agendamento["data_inicio"])
        mes = data_inicio.strftime("%Y-%m")
        
        if mes not in self.agenda:
            self.agenda[mes] = []
            
        self.agenda[mes].append(agendamento)
        self.salvar()
        
        # Registra o acordo como uma transação (tipo: agendamento)
        self.adicionar_transacao({
            "obra": agendamento["nome"],
            "data": data_inicio.strftime("%Y-%m-%d"),
            "tipo": "agendamento",
            "valor": 0.0, 
            "descricao": f"Obra agendada - Acordo: {formata_brl(agendamento['valor_acordado'])}",
            "categoria": "Serviço",
            "sub_categoria": "Acordo",
            "valor_total_compra": agendamento['valor_acordado'], 
            "origem": "agendamento"
        })

    def get_acordos_ativos(self):
        """Transações de acordo (agendamento) que ainda não foram canceladas."""
        return [t for t in self.transacoes if t["tipo"] == "agendamento"]

    def cancelar_agendamento(self, nome, transacao_id=None):
        """Cancela um acordo de obra sem apagar o histórico.

        O acordo deixa de entrar em "Acordado" e "A Receber"; os pagamentos já
        recebidos continuam no caixa. Se houver mais de um acordo ativo com o
        mesmo nome, cancela o mais recente (ou o de ``transacao_id``).
        Retorna a transação cancelada, ou None se não houver acordo ativo.
        """
        nome = (nome or "").strip()
        candidatos = [
            t for t in self.get_acordos_ativos()
            if t["obra"] == nome and (transacao_id is None or t["id"] == transacao_id)
        ]
        if not candidatos:
            return None

        alvo = candidatos[-1]
        alvo["tipo"] = "agendamento_cancelado"
        if not alvo["descricao"].startswith("[CANCELADO]"):
            alvo["descricao"] = f"[CANCELADO] {alvo['descricao']}"

        for lista in self.agenda.values():
            for item in lista:
                if (
                    item.get("nome") == nome
                    and not item.get("cancelado")
                    and item.get("valor_acordado") == alvo.get("valor_total_compra")
                ):
                    item["cancelado"] = True
                    break
            else:
                continue
            break

        self.salvar()
        return alvo

    def adicionar_pendencia_parcelada(self, tipo, transacao_base):
        """Adiciona as parcelas restantes como pendências futuras."""
        if transacao_base["parcelas_totais"] <= 1:
            return

        valor_parcela = transacao_base["valor"]
        parcelas_restantes = transacao_base["parcelas_totais"] - 1
        
        data_base = valida_data(transacao_base["data"])
        if not data_base: data_base = datetime.now()

        lista = self.pendencias['a_pagar'] if tipo == 'saida' else self.pendencias['a_receber']
        
        for i in range(1, parcelas_restantes + 1):
            data_vencimento = (data_base + timedelta(days=30 * i)).strftime("%Y-%m-%d")
            
            pendencia = {
                "id": transacao_base["id"], # Referência ao ID da primeira transação
                "data_vencimento": data_vencimento,
                "parcela": transacao_base["parcela_atual"] + i,
                "valor": valor_parcela,
                "descricao": f'Parc. {transacao_base["parcela_atual"] + i}/{transacao_base["parcelas_totais"]} de {transacao_base["sub_categoria"]}',
                "detalhes": transacao_base
            }
            lista.append(pendencia)
        
        self.salvar()


    def resumo_financeiro(self):
        saldo = 0
        valor_acordado = 0
        valor_total_recebido = 0 
        recebido_de_obras_canceladas = 0

        obras_ativas = {t["obra"] for t in self.transacoes if t["tipo"] == "agendamento"}
        obras_canceladas = {
            t["obra"] for t in self.transacoes if t["tipo"] == "agendamento_cancelado"
        } - obras_ativas

        for t in self.transacoes:
            valor = t["valor"]
            
            # --- Cálculo do Saldo (Caixa) ---
            if t["tipo"] in ["entrada", "pagamento_parcial", "ajuste_positivo"]:
                saldo += valor
            elif t["tipo"] in ["saida", "saida_parcela", "ajuste_negativo"]:
                saldo -= valor
                
            # --- Cálculo de Acordado e Recebido (Controle de Obras) ---
            if t["tipo"] == "agendamento":
                # Utiliza valor_total_compra para obter o valor acordado total
                valor_acordado += t.get("valor_total_compra", t["valor"]) 
            elif t["tipo"] == "pagamento_parcial" or t["categoria"] == "Serviço":
                valor_total_recebido += valor
                if t["obra"] and t["obra"] in obras_canceladas:
                    recebido_de_obras_canceladas += valor

        valor_a_receber_parcelado = sum(p["valor"] for p in self.pendencias['a_receber'])
        valor_a_pagar_parcelado = sum(p["valor"] for p in self.pendencias['a_pagar'])

        # Acordos cancelados saem da conta; o que já foi pago por eles não abate outras obras.
        valor_a_receber_obras = max(
            0, valor_acordado - (valor_total_recebido - recebido_de_obras_canceladas)
        )

        return {
            "saldo": saldo,
            "valor_acordado": valor_acordado,
            "valor_total_recebido": valor_total_recebido,
            "valor_a_receber_obras": valor_a_receber_obras,
            "a_receber_parcelas": valor_a_receber_parcelado,
            "a_pagar_parcelas": valor_a_pagar_parcelado
        }
        
# --- GUI do Aplicativo ---
class AppFinanceiro(tk.Tk):
    # Cores de fundo padronizadas
    COR_FUNDO_PADRAO = '#E6F7EF' # Verde claro (Light Mint)
    COR_FUNDO_TOPO = '#D4EDDA'   # Verde um pouco mais escuro

    def __init__(self):
        super().__init__()
        self.title("ObraCaixa — Controle Financeiro para Obras")
        self.geometry("1400x900")
        self.configure(bg=self.COR_FUNDO_PADRAO) # Define o fundo da janela principal
        
        # CORREÇÃO CRÍTICA: Registro de Estilos TTK antecipado no __init__ (Antes de create_widgets)
        style = ttk.Style()
        style.configure('TFrame', background=self.COR_FUNDO_PADRAO)
        # REMOVIDO o estilo 'SaidaTFrame' customizado, pois é a fonte do erro.
        # style.configure('SaidaTFrame', background=self.COR_FUNDO_PADRAO) 
        style.configure('TLabelFrame', background=self.COR_FUNDO_PADRAO, foreground='#333333')
        style.configure('TLabel', background=self.COR_FUNDO_PADRAO)
        
        # Forçar o Tcl a processar a atualização de estilos
        try:
             self.update() 
        except:
             pass 
        
        self.financeiro = FinanceiroBase()
        
        self.saldo_var = tk.StringVar()
        self.valor_a_receber_var = tk.StringVar() 
        self.valor_a_pagar_var = tk.StringVar() 
        
        self.entry_vars = {}
        
        self.create_widgets()
        self.atualizar_saldo()
        
    def on_closing(self):
        if messagebox.askyesno("Sair", "Tem certeza que deseja fechar o aplicativo? Todos os dados são salvos automaticamente."):
            self.destroy()

    def create_widgets(self):
        
        top_frame = tk.Frame(self, bg=self.COR_FUNDO_TOPO)
        top_frame.pack(fill="x", pady=5)
        
        tk.Label(top_frame, textvariable=self.saldo_var, font=("Arial", 16, "bold"), bg=self.COR_FUNDO_TOPO).pack(side="left", padx=15)
        tk.Label(top_frame, textvariable=self.valor_a_receber_var, font=("Arial", 16), fg='green', bg=self.COR_FUNDO_TOPO).pack(side="left", padx=15)
        tk.Label(top_frame, textvariable=self.valor_a_pagar_var, font=("Arial", 16), fg='red', bg=self.COR_FUNDO_TOPO).pack(side="left", padx=15)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # Abas principais (usando o estilo TFrame)
        self.aba_agendamento = ttk.Frame(self.notebook, style='TFrame')
        self.aba_entrada = ttk.Frame(self.notebook, style='TFrame')
        self.aba_saida = ttk.Frame(self.notebook, style='TFrame') 
        self.aba_parcelas = ttk.Frame(self.notebook, style='TFrame') 
        self.aba_ajuste = ttk.Frame(self.notebook, style='TFrame')
        self.aba_relatorio = ttk.Frame(self.notebook, style='TFrame')

        self.notebook.add(self.aba_agendamento, text="Agendamento de Obra")
        self.notebook.add(self.aba_entrada, text="Entrada de Recebimento")
        self.notebook.add(self.aba_saida, text="Saída (Despesas)")
        self.notebook.add(self.aba_parcelas, text="Gerenciar Parcelas")
        self.notebook.add(self.aba_ajuste, text="Ajuste de Saldo") 
        self.notebook.add(self.aba_relatorio, text="Relatório e Filtro")

        self.criar_aba_agendamento()
        self.criar_aba_entrada()
        self.criar_aba_saida_principal()
        self.criar_aba_parcelas()
        self.criar_aba_ajuste() 
        self.criar_aba_relatorio() 
        
        tk.Button(self, text="Sair", command=self.on_closing, bg='red', fg='white').pack(pady=10)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

    def on_tab_change(self, event):
        tab_name = self.notebook.tab(self.notebook.select(), "text")
        if tab_name == "Relatório e Filtro":
            self.atualizar_relatorio()
            # self.atualizar_relatorio_lucratividade() 
        elif tab_name == "Gerenciar Parcelas":
            self.atualizar_aba_parcelas()
        elif tab_name == "Ajuste de Saldo":
            self.atualizar_aba_ajuste()

    def atualizar_saldo(self):
        resumo = self.financeiro.resumo_financeiro()
        
        total_a_receber = resumo['valor_a_receber_obras'] + resumo['a_receber_parcelas']
        
        self.saldo_var.set(f"Saldo Total: {formata_brl(resumo['saldo'])}")
        self.valor_a_receber_var.set(f"A Receber (Obra + Parc.): {formata_brl(total_a_receber)}")
        self.valor_a_pagar_var.set(f"A Pagar (Parcelas): {formata_brl(resumo['a_pagar_parcelas'])}")
        
        self.lista_obras = self.financeiro.get_lista_obras()
        
        # Atualiza a Combobox de Obra nas telas de Saída
        if hasattr(self, 'entry_vars'):
             for key in [k for k in self.entry_vars.keys() if k.endswith('_obra')]:
                 combo = self.entry_vars.get(key)
                 if isinstance(combo, ttk.Combobox):
                     combo['values'] = self.lista_obras
                     # Tenta manter a seleção, ou volta para a primeira opção
                     if combo.get() not in self.lista_obras:
                          combo.set(self.lista_obras[0]) 

        if self.notebook.tab(self.notebook.select(), "text") == "Relatório e Filtro":
             self.atualizar_relatorio()
        if self.notebook.tab(self.notebook.select(), "text") == "Gerenciar Parcelas":
             self.atualizar_aba_parcelas()
        if self.notebook.tab(self.notebook.select(), "text") == "Ajuste de Saldo":
             self.atualizar_aba_ajuste()
             
    # --- ABA AGENDAMENTO ---
    def criar_aba_agendamento(self):
        frame = self.aba_agendamento
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        # Passa a cor de fundo
        self.entry_vars['agenda_nome'] = criar_label_entry(frame, "Nome da Obra:", 0, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['agenda_end_contratante'] = criar_label_entry(frame, "Endereço Contratante:", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['agenda_end_obra'] = criar_label_entry(frame, "Endereço da Obra:", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        
        self.entry_vars['agenda_data_inicio'] = criar_label_entry(frame, "Data de Início (dd/mm/aaaa):", 3, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['agenda_data_fim'] = criar_label_entry(frame, "Data Prev. Fim (dd/mm/aaaa):", 4, cor_fundo=self.COR_FUNDO_PADRAO)
        
        self.entry_vars['agenda_valor_acordado'] = criar_label_entry(frame, "Valor Acordado (R$):", 5, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['agenda_tempo_estimado'] = criar_label_entry(frame, "Tempo Estimado (dias/semanas):", 6, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Observações:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=7, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['agenda_descricao'] = criar_label_entry(frame, "", 7, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_agendar = tk.Button(frame, text="Agendar e Registrar Valor Acordado", command=self.registrar_agendamento, bg='blue', fg='white')
        btn_agendar.grid(row=8, column=1, sticky='e', padx=5, pady=10)

        btn_cancelar = tk.Button(frame, text="Cancelar Acordo de Obra", command=self.abrir_dialogo_cancelamento, bg='#B22222', fg='white')
        btn_cancelar.grid(row=9, column=1, sticky='e', padx=5, pady=5)

    def abrir_dialogo_cancelamento(self):
        ativos = self.financeiro.get_acordos_ativos()
        if not ativos:
            messagebox.showinfo("Cancelar Acordo", "Não há acordos de obra ativos para cancelar.")
            return

        janela = tk.Toplevel(self)
        janela.title("Cancelar Acordo de Obra")
        janela.configure(bg=self.COR_FUNDO_PADRAO)
        janela.transient(self)
        janela.grab_set()

        tk.Label(janela, text="Selecione o acordo que será cancelado:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).pack(padx=15, pady=(15, 5))
        opcoes = [
            f"{t['obra']} - {formata_brl(t.get('valor_total_compra', 0.0))} (início {t['data']})"
            for t in ativos
        ]
        combo = ttk.Combobox(janela, values=opcoes, state="readonly", width=60)
        combo.current(0)
        combo.pack(padx=15, pady=5)

        def confirmar():
            alvo = ativos[combo.current()]
            if messagebox.askyesno(
                "Confirmar cancelamento",
                f"Cancelar o acordo da obra '{alvo['obra']}'?\n\n"
                "O valor sai do 'A Receber'. Pagamentos já recebidos continuam no caixa "
                "e o histórico é mantido.",
                parent=janela,
            ):
                janela.destroy()
                self.processar_cancelamento_agendamento(alvo["obra"], alvo["id"])

        botoes = tk.Frame(janela, bg=self.COR_FUNDO_PADRAO)
        botoes.pack(pady=15)
        tk.Button(botoes, text="Cancelar acordo", command=confirmar, bg='#B22222', fg='white').pack(side="left", padx=5)
        tk.Button(botoes, text="Voltar", command=janela.destroy).pack(side="left", padx=5)

    def processar_cancelamento_agendamento(self, nome, transacao_id=None):
        cancelada = self.financeiro.cancelar_agendamento(nome, transacao_id)
        if cancelada is None:
            messagebox.showwarning("Cancelar Acordo", f"Nenhum acordo ativo encontrado para '{nome}'.")
            return
        self.lista_obras = self.financeiro.get_lista_obras()
        self.atualizar_saldo()
        self.atualizar_relatorio()
        messagebox.showinfo("Acordo cancelado", f"O acordo da obra '{nome}' foi cancelado e removido do 'A Receber'.")

    def registrar_agendamento(self):
        nome = self.entry_vars['agenda_nome'].get().strip()
        data_str_inicio = self.entry_vars['agenda_data_inicio'].get().strip()
        valor_str = self.entry_vars['agenda_valor_acordado'].get().replace(',', '.').strip()
        
        if not all([nome, data_str_inicio, valor_str]):
            messagebox.showerror("Erro", "Preencha Nome da Obra, Data de Início e Valor Acordado.")
            return

        data_inicio = valida_data(data_str_inicio)
        if not data_inicio:
            messagebox.showerror("Erro", "Data de Início inválida. Use dd/mm/aaaa.")
            return

        try:
            valor = float(valor_str)
            if valor <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor Acordado inválido.")
            return
        
        data_fim_obj = valida_data(self.entry_vars['agenda_data_fim'].get().strip())
        data_fim_str = data_fim_obj.strftime("%Y-%m-%d") if data_fim_obj else ""

        agendamento = {
            "nome": nome,
            "endereco_contratante": self.entry_vars['agenda_end_contratante'].get().strip(),
            "endereco_obra": self.entry_vars['agenda_end_obra'].get().strip(),
            "data_inicio": data_inicio.strftime("%Y-%m-%d"),
            "data_fim": data_fim_str,
            "valor_acordado": valor,
            "tempo_estimado": self.entry_vars['agenda_tempo_estimado'].get().strip(),
            "descricao": self.entry_vars['agenda_descricao'].get("1.0", "end").strip()
        }

        self.financeiro.adicionar_agendamento(agendamento)
        
        messagebox.showinfo("Sucesso", f"Obra '{nome}' agendada e valor acordado registrado.")
        
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        for key in ['agenda_nome', 'agenda_end_contratante', 'agenda_end_obra', 
                    'agenda_data_fim', 'agenda_valor_acordado', 'agenda_tempo_estimado']:
            self.entry_vars[key].delete(0, 'end')
        self.entry_vars['agenda_data_inicio'].delete(0, 'end')
        self.entry_vars['agenda_data_inicio'].insert(0, data_hoje)
        self.entry_vars['agenda_descricao'].delete("1.0", "end")
        
        self.atualizar_saldo()

    # --- ABA ENTRADA ---
    def criar_aba_entrada(self):
        frame = self.aba_entrada
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['entrada_obra'] = criar_label_entry(frame, "Obra/Cliente (opcional):", 0, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['entrada_valor'] = criar_label_entry(frame, "Valor Recebido (R$):", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['entrada_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 2, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Categoria:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=3, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['entrada_categoria'] = ttk.Combobox(frame, values=["Serviço - Dias Normais", "Serviço - Extras/Abono", "Vendas (Material/Item)", "Adiantamento/Outros"], state="readonly", width=47)
        self.entry_vars['entrada_categoria'].grid(row=3, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['entrada_categoria'].current(0)
        
        tk.Label(frame, text="Forma de Pagamento:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=4, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['entrada_forma_pagamento'] = ttk.Combobox(frame, values=["Total/À Vista", "Pagamento Parcial (Obra)", "Parcelado (Cria Crédito Futuro)"], state="readonly", width=47)
        self.entry_vars['entrada_forma_pagamento'].grid(row=4, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['entrada_forma_pagamento'].current(0)
        
        self.entry_vars['entrada_parcelas'] = criar_label_entry(frame, "Nº de Parcelas:", 5, valor_inicial="1", cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=6, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['entrada_descricao'] = criar_label_entry(frame, "", 6, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_entrada = tk.Button(frame, text="Registrar Entrada", command=self.registrar_entrada, bg='green', fg='white')
        btn_entrada.grid(row=7, column=1, sticky='e', padx=5, pady=10)

    def registrar_entrada(self):
        obra = self.entry_vars['entrada_obra'].get().strip()
        valor_str = self.entry_vars['entrada_valor'].get().replace(',', '.').strip()
        data_str = self.entry_vars['entrada_data'].get().strip()
        categoria_sub = self.entry_vars['entrada_categoria'].get()
        forma_pagamento = self.entry_vars['entrada_forma_pagamento'].get()
        parcelas_str = self.entry_vars['entrada_parcelas'].get().strip()
        descricao = self.entry_vars['entrada_descricao'].get("1.0", "end").strip()

        if not valor_str or not data_str:
            messagebox.showerror("Erro", "Valor e Data são obrigatórios.")
            return

        data_obj = valida_data(data_str)
        if not data_obj:
            messagebox.showerror("Erro", "Data inválida. Use dd/mm/aaaa.")
            return

        try:
            valor_total = float(valor_str)
            parcelas_totais = int(parcelas_str)
            if valor_total <= 0 or parcelas_totais <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor ou Nº de Parcelas inválidos.")
            return

        tipo_transacao = "entrada"
        valor_a_registrar = valor_total

        if "Parcelado" in forma_pagamento:
            valor_a_registrar = round(valor_total / parcelas_totais, 2)
            tipo_transacao = "pagamento_parcial" 
            messagebox.showinfo("Parcelamento", f"Será registrado {formata_brl(valor_a_registrar)} na entrada. O restante será adicionado como crédito futuro.")
        
        elif "Pagamento Parcial" in forma_pagamento:
            tipo_transacao = "pagamento_parcial"
            parcelas_totais = 1 
        
        transacao = {
            "obra": obra,
            "data": data_obj.strftime("%Y-%m-%d"),
            "tipo": tipo_transacao,
            "valor": valor_a_registrar, 
            "descricao": descricao,
            "categoria": "Recebimento",
            "sub_categoria": categoria_sub,
            "origem": "manual",
            "parcelas_totais": parcelas_totais,
            "parcela_atual": 1,
            "valor_total_compra": valor_total
        }

        self.financeiro.adicionar_transacao(transacao)
        
        if "Parcelado" in forma_pagamento and parcelas_totais > 1:
            self.financeiro.adicionar_pendencia_parcelada('entrada', transacao)
            
        messagebox.showinfo("Sucesso", "Entrada registrada com sucesso.")
        
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        for key in ['entrada_obra', 'entrada_valor']:
            self.entry_vars[key].delete(0, 'end')
        self.entry_vars['entrada_descricao'].delete("1.0", "end")
        self.entry_vars['entrada_parcelas'].delete(0, 'end')
        self.entry_vars['entrada_parcelas'].insert(0, "1")
        self.entry_vars['entrada_data'].delete(0, 'end')
        self.entry_vars['entrada_data'].insert(0, data_hoje)
        
        self.atualizar_saldo()

    # --- ABA SAÍDA (NOTEBOOK PRINCIPAL) ---
    def criar_aba_saida_principal(self):
        self.notebook_saida = ttk.Notebook(self.aba_saida)
        self.notebook_saida.pack(fill="both", expand=True, padx=10, pady=10)

        # CORRIGIDO: Usando o estilo universal 'TFrame' em vez de 'SaidaTFrame' para máxima estabilidade
        self.aba_saida_combustivel = ttk.Frame(self.notebook_saida, style='TFrame')
        self.aba_saida_alimentacao = ttk.Frame(self.notebook_saida, style='TFrame')
        self.aba_saida_almoco_janta = ttk.Frame(self.notebook_saida, style='TFrame')
        self.aba_saida_funcionario = ttk.Frame(self.notebook_saida, style='TFrame')
        self.aba_saida_ferramentas = ttk.Frame(self.notebook_saida, style='TFrame')
        self.aba_saida_outros = ttk.Frame(self.notebook_saida, style='TFrame')

        self.notebook_saida.add(self.aba_saida_combustivel, text="Combustível")
        self.notebook_saida.add(self.aba_saida_alimentacao, text="Supermercado/Açougue")
        self.notebook_saida.add(self.aba_saida_almoco_janta, text="Almoço/Janta")
        self.notebook_saida.add(self.aba_saida_funcionario, text="Funcionário")
        self.notebook_saida.add(self.aba_saida_ferramentas, text="Ferramentas (Parcelado)")
        self.notebook_saida.add(self.aba_saida_outros, text="Outros Gastos")

        self.lista_obras = self.financeiro.get_lista_obras() # Garante a lista de obras
        
        self.criar_saida_combustivel()
        self.criar_saida_alimentacao()
        self.criar_saida_almoco_janta()
        self.criar_saida_funcionario()
        self.criar_saida_ferramentas()
        self.criar_saida_outros()

    # --- SUB-ABAS DE SAÍDA ---
    
    def adicionar_campo_obra_sub_aba(self, frame, linha):
        """Adiciona o campo de seleção de obra a uma sub-aba de Saída."""
        # Garante que a Label tenha a cor do frame
        tk.Label(frame, text="Obra Relacionada:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=linha, column=0, sticky='w', padx=5, pady=2)
        
        # Cria a Combobox com a lista de obras
        combobox = ttk.Combobox(frame, values=self.lista_obras, state="readonly", width=47)
        combobox.grid(row=linha, column=1, padx=5, pady=2, sticky='ew')
        
        try:
             combobox.current(0)
        except:
             combobox.set("N/A - Gasto não relacionado à Obra")
             
        # Armazenamos na lista de entry_vars para atualizações dinâmicas
        return combobox

    def registrar_saida_generica(self, categoria, prefixo):
        
        valor_key = f'{prefixo}_valor_gasto' if prefixo in ['comb', 'alimen', 'refeicao'] else f'{prefixo}_valor'
        
        # CORREÇÃO: Pega a obra do entry_vars, que foi definido em criar_saida_combustivel/etc.
        obra_relacionada = self.entry_vars.get(f'{prefixo}_obra', ttk.Combobox()).get().strip() 
        valor_str = self.entry_vars[valor_key].get().replace(',', '.').strip()
        data_str = self.entry_vars[f'{prefixo}_data'].get().strip()
        descricao = self.entry_vars[f'{prefixo}_descricao'].get("1.0", "end").strip()
        
        if not valor_str or not data_str:
            messagebox.showerror("Erro", "Valor e Data são obrigatórios.")
            return

        data_obj = valida_data(data_str)
        if not data_obj:
            messagebox.showerror("Erro", "Data inválida. Use dd/mm/aaaa.")
            return

        try:
            valor = float(valor_str)
            if valor <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor Gasto inválido.")
            return

        obra_para_salvar = "" if "N/A" in obra_relacionada else obra_relacionada
        
        transacao = {
            "obra": obra_para_salvar,
            "data": data_obj.strftime("%Y-%m-%d"),
            "tipo": "saida",
            "valor": valor,
            "descricao": descricao,
            "categoria": "Despesa",
            "sub_categoria": categoria,
            "origem": prefixo,
        }
        
        self.financeiro.adicionar_transacao(transacao)
        messagebox.showinfo("Sucesso", f"Gasto com {categoria} registrado e relacionado a '{obra_relacionada}' com sucesso.")
        
        # Limpa campos e reseta data
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        for key in [valor_key, f'{prefixo}_cidade', f'{prefixo}_tipo', f'{prefixo}_litro']:
            if key in self.entry_vars: 
                self.entry_vars[key].delete(0, 'end')
        self.entry_vars[f'{prefixo}_data'].delete(0, 'end')
        self.entry_vars[f'{prefixo}_data'].insert(0, data_hoje)
        
        if f'{prefixo}_descricao' in self.entry_vars: self.entry_vars[f'{prefixo}_descricao'].delete("1.0", "end")
        
        self.atualizar_saldo()
    
    # --- Telas de Saída com campo Obra Adicionado ---
    
    def criar_saida_combustivel(self):
        frame = self.aba_saida_combustivel
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['comb_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)
        
        self.entry_vars['comb_tipo'] = criar_label_entry(frame, "Tipo (Gasolina/Álcool/Gás):", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['comb_litro'] = criar_label_entry(frame, "Valor do Litro (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['comb_valor_gasto'] = criar_label_entry(frame, "Valor Gasto (R$):", 3, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['comb_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 4, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['comb_cidade'] = criar_label_entry(frame, "Cidade/Local:", 5, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=6, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['comb_descricao'] = criar_label_entry(frame, "", 6, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Gasto (Combustível)", command=lambda: self.registrar_saida_generica("Combustível", 'comb'), bg='red', fg='white')
        btn_saida.grid(row=7, column=1, sticky='e', padx=5, pady=10)

    def criar_saida_alimentacao(self):
        frame = self.aba_saida_alimentacao
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['alimen_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)
        
        tk.Label(frame, text="Local da Compra:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=1, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['alimen_local'] = ttk.Combobox(frame, values=["Supermercado", "Açougue", "Padaria", "Outros"], state="readonly", width=47)
        self.entry_vars['alimen_local'].grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['alimen_local'].current(0)
        
        self.entry_vars['alimen_valor_gasto'] = criar_label_entry(frame, "Valor Gasto (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['alimen_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 3, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=4, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['alimen_descricao'] = criar_label_entry(frame, "", 4, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Gasto (Alimentação)", command=lambda: self.registrar_saida_generica("Alimentação", 'alimen'), bg='red', fg='white')
        btn_saida.grid(row=5, column=1, sticky='e', padx=5, pady=10)

    def criar_saida_almoco_janta(self):
        frame = self.aba_saida_almoco_janta
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['refeicao_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)
        
        tk.Label(frame, text="Tipo de Despesa:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=1, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['refeicao_tipo'] = ttk.Combobox(frame, values=["Almoço - Trabalho", "Janta - Trabalho", "Almoço - Lazer", "Janta - Lazer"], state="readonly", width=47)
        self.entry_vars['refeicao_tipo'].grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['refeicao_tipo'].current(0)
        
        self.entry_vars['refeicao_valor_gasto'] = criar_label_entry(frame, "Valor Gasto (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['refeicao_cidade'] = criar_label_entry(frame, "Cidade:", 3, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['refeicao_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 4, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=5, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['refeicao_descricao'] = criar_label_entry(frame, "", 5, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Gasto (Refeição)", command=lambda: self.registrar_saida_generica("Refeição", 'refeicao'), bg='red', fg='white')
        btn_saida.grid(row=6, column=1, sticky='e', padx=5, pady=10)

    def criar_saida_funcionario(self):
        frame = self.aba_saida_funcionario
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['func_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)
        
        self.entry_vars['func_nome'] = criar_label_entry(frame, "Nome:", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['func_salario'] = criar_label_entry(frame, "Salário Combinado (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['func_periodo'] = criar_label_entry(frame, "Período (Semanal/Mensal):", 3, cor_fundo=self.COR_FUNDO_PADRAO)
        
        self.entry_vars['func_valor_pago'] = criar_label_entry(frame, "Valor Pago (R$):", 4, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['func_data_pagamento'] = criar_label_entry(frame, "Data Pagamento (dd/mm/aaaa):", 5, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Forma de Pagamento:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=6, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['func_forma_pagamento'] = ttk.Combobox(frame, values=["Total", "Parcial/Adiantamento"], state="readonly", width=47)
        self.entry_vars['func_forma_pagamento'].grid(row=6, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['func_forma_pagamento'].current(0)
        
        tk.Label(frame, text="Descrição/Observação:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=7, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['func_descricao'] = criar_label_entry(frame, "", 7, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Pagamento (Funcionário)", command=lambda: self.registrar_saida_funcionario_completa(), bg='red', fg='white')
        btn_saida.grid(row=8, column=1, sticky='e', padx=5, pady=10)

    def registrar_saida_funcionario_completa(self):
        obra_relacionada = self.entry_vars['func_obra'].get().strip()
        nome = self.entry_vars['func_nome'].get().strip()
        valor_pago_str = self.entry_vars['func_valor_pago'].get().replace(',', '.').strip()
        data_str = self.entry_vars['func_data_pagamento'].get().strip()
        
        if not obra_relacionada or (obra_relacionada not in self.lista_obras and "N/A" not in obra_relacionada):
             messagebox.showerror("Erro", "Selecione uma 'Obra Relacionada' válida.")
             return
        
        if not nome or not valor_pago_str or not data_str:
            messagebox.showerror("Erro", "Nome, Valor Pago e Data são obrigatórios.")
            return
            
        data_obj = valida_data(data_str)
        if not data_obj:
            messagebox.showerror("Erro", "Data inválida. Use dd/mm/aaaa.")
            return
            
        try:
            valor_pago = float(valor_pago_str)
            if valor_pago <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor Pago inválido.")
            return
            
        obra_para_salvar = "" if "N/A" in obra_relacionada else obra_relacionada
            
        transacao = {
            "obra": obra_para_salvar,
            "data": data_obj.strftime("%Y-%m-%d"),
            "tipo": "saida",
            "valor": valor_pago,
            "descricao": self.entry_vars['func_descricao'].get("1.0", "end").strip(),
            "categoria": "Despesa",
            "sub_categoria": "Funcionário",
            "origem": "funcionario",
        }
        
        self.financeiro.adicionar_transacao(transacao)
        messagebox.showinfo("Sucesso", f"Pagamento a {nome} registrado e relacionado a '{obra_relacionada}'.")
        
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        for key in ['func_nome', 'func_salario', 'func_periodo', 'func_valor_pago']:
            self.entry_vars[key].delete(0, 'end')
        self.entry_vars['func_data_pagamento'].delete(0, 'end')
        self.entry_vars['func_data_pagamento'].insert(0, data_hoje)
        self.entry_vars['func_descricao'].delete("1.0", "end")
        self.atualizar_saldo()

    def criar_saida_ferramentas(self):
        frame = self.aba_saida_ferramentas
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['ferr_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)
        
        self.entry_vars['ferr_item'] = criar_label_entry(frame, "Item/Ferramenta:", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['ferr_valor_total'] = criar_label_entry(frame, "Valor Total (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Forma de Pagamento:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=3, column=0, sticky='w', padx=5, pady=2)
        self.entry_vars['ferr_forma_pagamento'] = ttk.Combobox(frame, values=["À Vista", "Parcelado (Cria Dívida Futura)"], state="readonly", width=47)
        self.entry_vars['ferr_forma_pagamento'].grid(row=3, column=1, padx=5, pady=2, sticky='ew')
        self.entry_vars['ferr_forma_pagamento'].current(0)
        
        self.entry_vars['ferr_parcelas'] = criar_label_entry(frame, "Nº de Parcelas:", 4, valor_inicial="1", cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['ferr_data_compra'] = criar_label_entry(frame, "Data da Compra (dd/mm/aaaa):", 5, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição/Observação:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=6, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['ferr_descricao'] = criar_label_entry(frame, "", 6, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Compra (Ferramenta)", command=self.registrar_saida_ferramentas_completa, bg='red', fg='white')
        btn_saida.grid(row=7, column=1, sticky='e', padx=5, pady=10)

    def registrar_saida_ferramentas_completa(self):
        obra_relacionada = self.entry_vars['ferr_obra'].get().strip()
        item = self.entry_vars['ferr_item'].get().strip()
        valor_total_str = self.entry_vars['ferr_valor_total'].get().replace(',', '.').strip()
        forma_pagamento = self.entry_vars['ferr_forma_pagamento'].get()
        parcelas_str = self.entry_vars['ferr_parcelas'].get().strip()
        data_str = self.entry_vars['ferr_data_compra'].get().strip()
        
        if not obra_relacionada or (obra_relacionada not in self.lista_obras and "N/A" not in obra_relacionada):
             messagebox.showerror("Erro", "Selecione uma 'Obra Relacionada' válida.")
             return

        if not item or not valor_total_str or not data_str:
            messagebox.showerror("Erro", "Item, Valor Total e Data são obrigatórios.")
            return
            
        data_obj = valida_data(data_str)
        if not data_obj:
            messagebox.showerror("Erro", "Data inválida. Use dd/mm/aaaa.")
            return
            
        try:
            valor_total = float(valor_total_str)
            parcelas_totais = int(parcelas_str)
            if valor_total <= 0 or parcelas_totais <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor ou Nº de Parcelas inválidos.")
            return
        
        valor_a_registrar = valor_total
        tipo_transacao = "saida"

        if "Parcelado" in forma_pagamento:
            valor_a_registrar = round(valor_total / parcelas_totais, 2)
            tipo_transacao = "saida_parcela"
            messagebox.showinfo("Parcelamento", f"Compra parcelada em {parcelas_totais}x. A transação de hoje será de {formata_brl(valor_a_registrar)}. O restante será adicionado como dívida futura.")
        
        obra_para_salvar = "" if "N/A" in obra_relacionada else obra_relacionada
            
        transacao = {
            "obra": obra_para_salvar,
            "data": data_obj.strftime("%Y-%m-%d"),
            "tipo": tipo_transacao,
            "valor": valor_a_registrar, 
            "descricao": self.entry_vars['ferr_descricao'].get("1.0", "end").strip(),
            "categoria": "Despesa",
            "sub_categoria": "Ferramentas",
            "origem": "ferramentas",
            "parcelas_totais": parcelas_totais,
            "parcela_atual": 1,
            "valor_total_compra": valor_total
        }
        
        self.financeiro.adicionar_transacao(transacao)
        
        if "Parcelado" in forma_pagamento and parcelas_totais > 1:
            self.financeiro.adicionar_pendencia_parcelada('saida', transacao)
            
        messagebox.showinfo("Sucesso", f"Compra de {item} registrada e relacionada a '{obra_relacionada}'.")
        
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        for key in ['ferr_item', 'ferr_valor_total']:
            self.entry_vars[key].delete(0, 'end')
        self.entry_vars['ferr_parcelas'].delete(0, 'end')
        self.entry_vars['ferr_parcelas'].insert(0, "1")
        self.entry_vars['ferr_data_compra'].delete(0, 'end')
        self.entry_vars['ferr_data_compra'].insert(0, data_hoje)
        self.entry_vars['ferr_descricao'].delete("1.0", "end")
        self.atualizar_saldo()

    def criar_saida_outros(self):
        frame = self.aba_saida_outros
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        
        self.entry_vars['outros_obra'] = self.adicionar_campo_obra_sub_aba(frame, 0)

        self.entry_vars['outros_valor'] = criar_label_entry(frame, "Valor Gasto (R$):", 1, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['outros_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 2, valor_inicial=data_hoje, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Label(frame, text="Descrição do Gasto:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=3, column=0, sticky='nw', padx=5, pady=2)
        self.entry_vars['outros_descricao'] = criar_label_entry(frame, "", 3, tipo='text', cor_fundo=self.COR_FUNDO_PADRAO)
        
        btn_saida = tk.Button(frame, text="Salvar Outros Gastos", command=lambda: self.registrar_saida_generica("Outros Gastos", 'outros'), bg='red', fg='white')
        btn_saida.grid(row=4, column=1, sticky='e', padx=5, pady=10)

    # --- ABA AJUSTE DE SALDO (Reintroduzida) ---
    def criar_aba_ajuste(self):
        frame = self.aba_ajuste
        
        tk.Label(frame, text="Ajuste Rápido de Saldo (Caixa)", font=("Arial", 14, "bold"), bg=self.COR_FUNDO_PADRAO).grid(row=0, column=0, columnspan=2, pady=10)
        
        # 1. Ajuste Manual (Adicionar/Remover)
        tk.Label(frame, text="Tipo de Ajuste:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.entry_vars['ajuste_tipo'] = ttk.Combobox(frame, values=["Entrada (Ajuste Positivo)", "Saída (Ajuste Negativo)"], state="readonly", width=47)
        self.entry_vars['ajuste_tipo'].grid(row=1, column=1, padx=5, pady=5, sticky='ew')
        self.entry_vars['ajuste_tipo'].current(0)
        
        self.entry_vars['ajuste_valor'] = criar_label_entry(frame, "Valor do Ajuste (R$):", 2, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['ajuste_data'] = criar_label_entry(frame, "Data (dd/mm/aaaa):", 3, valor_inicial=datetime.now().strftime("%d/%m/%Y"), cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['ajuste_descricao'] = criar_label_entry(frame, "Motivo do Ajuste:", 4, cor_fundo=self.COR_FUNDO_PADRAO)
        
        tk.Button(frame, text="Registrar Ajuste", command=self.registrar_ajuste, bg='#0077b6', fg='white').grid(row=5, column=1, sticky='e', padx=5, pady=10)

        # 2. Re-inicialização de Saldo (Zerar)
        tk.Label(frame, text="--- ZERAR SALDO E REINICIAR CONTROLE ---", font=("Arial", 12, "italic"), bg=self.COR_FUNDO_PADRAO).grid(row=6, column=0, columnspan=2, pady=20)
        
        tk.Label(frame, text="Seu saldo atual é:", font=("Arial", 10), bg=self.COR_FUNDO_PADRAO).grid(row=7, column=0, sticky='w', padx=5, pady=5)
        self.saldo_atual_ajuste_var = tk.StringVar(value=formata_brl(self.financeiro.resumo_financeiro()['saldo']))
        tk.Label(frame, textvariable=self.saldo_atual_ajuste_var, font=("Arial", 12, "bold"), bg=self.COR_FUNDO_PADRAO).grid(row=7, column=1, sticky='w', padx=5, pady=5)
        
        self.entry_vars['ajuste_novo_valor'] = criar_label_entry(frame, "Novo Valor de Saldo (R$):", 8, cor_fundo=self.COR_FUNDO_PADRAO)
        self.entry_vars['ajuste_novo_valor'].insert(0, "0.00")
        
        tk.Button(frame, text="Zerar Saldo e Aplicar Novo Valor", command=self.reiniciar_saldo, bg='darkred', fg='white').grid(row=9, column=1, sticky='e', padx=5, pady=10)
        
    def atualizar_aba_ajuste(self):
        # Garante que o saldo atual na aba de ajuste seja atualizado
        self.saldo_atual_ajuste_var.set(formata_brl(self.financeiro.resumo_financeiro()['saldo']))

    def registrar_ajuste(self):
        # Lógica de registro de ajuste mantida igual
        tipo_str = self.entry_vars['ajuste_tipo'].get()
        valor_str = self.entry_vars['ajuste_valor'].get().replace(',', '.').strip()
        data_str = self.entry_vars['ajuste_data'].get().strip()
        descricao = self.entry_vars['ajuste_descricao'].get().strip()

        if not valor_str or not data_str:
            messagebox.showerror("Erro", "Valor e Data são obrigatórios.")
            return

        data_obj = valida_data(data_str)
        if not data_obj:
            messagebox.showerror("Erro", "Data inválida. Use dd/mm/aaaa.")
            return

        try:
            valor = float(valor_str)
            if valor <= 0: raise ValueError
        except:
            messagebox.showerror("Erro", "Valor inválido.")
            return

        tipo_transacao = "ajuste_positivo" if "Positivo" in tipo_str else "ajuste_negativo"
        
        transacao = {
            "obra": "",
            "data": data_obj.strftime("%Y-%m-%d"),
            "tipo": tipo_transacao,
            "valor": valor,
            "descricao": f"Ajuste de Saldo: {descricao}",
            "categoria": "Ajuste",
            "sub_categoria": tipo_transacao,
            "origem": "ajuste_manual"
        }
        self.financeiro.adicionar_transacao(transacao)
        messagebox.showinfo("Sucesso", f"Ajuste {tipo_str.split()[1]} de {formata_brl(valor)} registrado com sucesso.")
        
        self.entry_vars['ajuste_valor'].delete(0, 'end')
        self.entry_vars['ajuste_descricao'].delete(0, 'end')
        self.atualizar_saldo()
        
    def reiniciar_saldo(self):
        # Lógica de reinício de saldo mantida igual
        novo_valor_str = self.entry_vars['ajuste_novo_valor'].get().replace(',', '.').strip()
        
        try:
            novo_valor = float(novo_valor_str)
        except:
            messagebox.showerror("Erro", "Novo Valor inválido.")
            return

        saldo_atual = self.financeiro.resumo_financeiro()['saldo']
        diferenca = novo_valor - saldo_atual
        
        tipo_transacao = "ajuste_positivo" if diferenca >= 0 else "ajuste_negativo"
        valor_ajuste = abs(diferenca)
        
        if not messagebox.askyesno("Confirmar Reinicialização", 
                                   f"O saldo atual é {formata_brl(saldo_atual)}. \n\n"
                                   f"Isto irá registrar um ajuste de {formata_brl(valor_ajuste)} ({tipo_transacao.split('_')[1].upper()}) "
                                   f"para que o novo saldo seja {formata_brl(novo_valor)}.\n\n"
                                   f"Tem certeza que deseja continuar?"):
            return

        transacao = {
            "obra": "REINICIALIZAÇÃO",
            "data": datetime.now().strftime("%Y-%m-%d"),
            "tipo": tipo_transacao,
            "valor": valor_ajuste,
            "descricao": f"Reinicialização de Saldo para valor de {formata_brl(novo_valor)}.",
            "categoria": "Ajuste",
            "sub_categoria": "Reinicialização",
            "origem": "ajuste_zero"
        }
        
        if valor_ajuste > 0.01: 
            self.financeiro.adicionar_transacao(transacao)
        
        messagebox.showinfo("Sucesso", f"Saldo ajustado para {formata_brl(novo_valor)}.")
        self.atualizar_saldo()


    # --- ABA RELATÓRIO E FILTRO ---
    def criar_aba_relatorio(self):
        frame = self.aba_relatorio
        
        self.notebook_relatorio = ttk.Notebook(frame)
        self.notebook_relatorio.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.aba_rel_fluxo = ttk.Frame(self.notebook_relatorio, style='TFrame')
        self.aba_rel_lucro = ttk.Frame(self.notebook_relatorio, style='TFrame') 
        
        self.notebook_relatorio.add(self.aba_rel_fluxo, text="Fluxo de Caixa Detalhado")
        # self.notebook_relatorio.add(self.aba_rel_lucro, text="Lucratividade por Obra (Profit Tracker)") 

        self.criar_relatorio_fluxo_caixa(self.aba_rel_fluxo)
        # self.criar_relatorio_lucratividade(self.aba_rel_lucro) 

    def criar_relatorio_fluxo_caixa(self, frame):
        resumo_frame = tk.LabelFrame(frame, text="Resumo Financeiro", padx=10, pady=10, bg=self.COR_FUNDO_PADRAO)
        resumo_frame.pack(fill="x", padx=10, pady=10)
        
        self.rel_saldo_var = tk.StringVar()
        self.rel_acordado_var = tk.StringVar()
        self.rel_recebido_var = tk.StringVar()
        self.rel_a_receber_var_obra = tk.StringVar()
        self.rel_a_receber_var_parc = tk.StringVar()
        self.rel_a_pagar_var_parc = tk.StringVar()
        
        # Labels dentro do resumo_frame precisam de bg
        tk.Label(resumo_frame, textvariable=self.rel_saldo_var, font=("Arial", 14, "bold"), bg=self.COR_FUNDO_PADRAO).pack(pady=5)
        tk.Label(resumo_frame, textvariable=self.rel_acordado_var, font=("Arial", 12), bg=self.COR_FUNDO_PADRAO).pack(pady=2)
        tk.Label(resumo_frame, textvariable=self.rel_recebido_var, font=("Arial", 12), bg=self.COR_FUNDO_PADRAO).pack(pady=2)
        tk.Label(resumo_frame, textvariable=self.rel_a_receber_var_obra, font=("Arial", 12), fg='blue', bg=self.COR_FUNDO_PADRAO).pack(pady=2)
        tk.Label(resumo_frame, textvariable=self.rel_a_receber_var_parc, font=("Arial", 12), fg='green', bg=self.COR_FUNDO_PADRAO).pack(pady=2)
        tk.Label(resumo_frame, textvariable=self.rel_a_pagar_var_parc, font=("Arial", 12), fg='red', bg=self.COR_FUNDO_PADRAO).pack(pady=2)

        # --- FILTROS DE TEMPO ---
        acao_frame = tk.LabelFrame(frame, text="Filtros e Exportação", padx=10, pady=10, bg=self.COR_FUNDO_PADRAO)
        acao_frame.pack(fill="x", padx=10, pady=10)
        
        # Labels dentro do acao_frame precisam de bg
        tk.Label(acao_frame, text="Data Início (dd/mm/aaaa):", bg=self.COR_FUNDO_PADRAO).grid(row=0, column=0, padx=5)
        self.entry_vars['filtro_data_inicio'] = tk.Entry(acao_frame, width=15)
        self.entry_vars['filtro_data_inicio'].grid(row=0, column=1, padx=5)
        
        tk.Label(acao_frame, text="Data Fim:", bg=self.COR_FUNDO_PADRAO).grid(row=0, column=2, padx=5)
        self.entry_vars['filtro_data_fim'] = tk.Entry(acao_frame, width=15)
        self.entry_vars['filtro_data_fim'].grid(row=0, column=3, padx=5)
        
        tk.Button(acao_frame, text="Aplicar Filtro", command=self.aplicar_filtro_relatorio).grid(row=0, column=4, padx=10)
        
        tk.Button(acao_frame, text="Exportar relatório TXT (Área de Trabalho)", command=self.exportar_pdf, bg='purple', fg='white').grid(row=1, column=0, columnspan=5, pady=10)

        columns = ("Data", "Tipo", "Categoria", "Obra/Item", "Descrição", "Valor")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
        self.tree.column("Descrição", width=300)
        self.tree.column("Valor", anchor='e')
        
        self.atualizar_relatorio()
    
    def atualizar_relatorio(self, transacoes_filtradas=None):
        resumo = self.financeiro.resumo_financeiro()
        
        self.rel_saldo_var.set(f"Saldo Total: {formata_brl(resumo['saldo'])}")
        self.rel_acordado_var.set(f"Valor Acordado Total (Obras): {formata_brl(resumo['valor_acordado'])}")
        self.rel_recebido_var.set(f"Valor Total Recebido (Caixa): {formata_brl(resumo['valor_total_recebido'])}")
        self.rel_a_receber_var_obra.set(f"A Receber (Obras - Contrato): {formata_brl(resumo['valor_a_receber_obras'])}")
        self.rel_a_receber_var_parc.set(f"A Receber (Parcelas Futuras): {formata_brl(resumo['a_receber_parcelas'])}")
        self.rel_a_pagar_var_parc.set(f"A Pagar (Dívidas Parceladas): {formata_brl(resumo['a_pagar_parcelas'])}")
        
        self.tree.delete(*self.tree.get_children())
        
        dados = transacoes_filtradas if transacoes_filtradas is not None else self.financeiro.transacoes
        dados_ordenados = sorted(dados, key=lambda x: x['data'], reverse=True)
        
        for t in dados_ordenados:
            valor_formatado = formata_brl(t['valor'])
            
            tipo = "Entrada"
            if t['tipo'] in ["saida", "saida_parcela", "ajuste_negativo"]:
                tipo = "Saída"
            elif t['tipo'] == "agendamento":
                tipo = "Acordo (Futuro)"
            elif t['tipo'] == "agendamento_cancelado":
                tipo = "Acordo Cancelado"

            categoria = "ACORDO CANCELADO" if t['tipo'] == "agendamento_cancelado" else (t.get('sub_categoria', '') or t['categoria'])
            
            self.tree.insert("", "end", values=(
                t['data'],
                tipo,
                categoria,
                t['obra'],
                f"{t['descricao']} (P: {t.get('parcela_atual', 1)}/{t.get('parcelas_totais', 1)})",
                valor_formatado
            ))

    def aplicar_filtro_relatorio(self):
        # Lógica de filtro mantida
        data_inicio_str = self.entry_vars['filtro_data_inicio'].get().strip()
        data_fim_str = self.entry_vars['filtro_data_fim'].get().strip()
        
        data_inicio_obj = valida_data(data_inicio_str)
        data_fim_obj = valida_data(data_fim_str)

        if (data_inicio_str and not data_inicio_obj) or (data_fim_str and not data_fim_obj):
            messagebox.showerror("Erro de Filtro", "Datas inválidas. Use dd/mm/aaaa.")
            return
            
        if data_fim_obj:
            data_fim_obj = data_fim_obj + timedelta(days=1)

        transacoes_filtradas = []
        for t in self.financeiro.transacoes:
            data_transacao_obj = valida_data(t['data'])
            
            if data_inicio_obj and data_transacao_obj < data_inicio_obj:
                continue
                
            if data_fim_obj and data_transacao_obj >= data_fim_obj:
                continue
                
            transacoes_filtradas.append(t)
            
        self.atualizar_relatorio(transacoes_filtradas)
        messagebox.showinfo("Filtro", f"{len(transacoes_filtradas)} transações encontradas.")


    def exportar_pdf(self):
        # Lógica de exportação mantida
        if platform.system() == "Windows":
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        elif platform.system() == "Darwin": 
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        else: 
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            
        nome_arquivo = f"Relatorio_Financeiro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt" 
        caminho_completo = os.path.join(desktop, nome_arquivo)
        
        dados = self.financeiro.transacoes 
        dados_ordenados = sorted(dados, key=lambda x: x['data'], reverse=True)

        try:
            with open(caminho_completo, 'w', encoding='utf-8') as f:
                f.write(f"RELATÓRIO FINANCEIRO - {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
                resumo = self.financeiro.resumo_financeiro()
                f.write("-" * 50 + "\n")
                f.write(f"Saldo Total: {formata_brl(resumo['saldo'])}\n")
                f.write(f"A Receber (Parcelas): {formata_brl(resumo['a_receber_parcelas'])}\n")
                f.write(f"A Pagar (Parcelas): {formata_brl(resumo['a_pagar_parcelas'])}\n")
                f.write("-" * 50 + "\n")
                f.write(f"{'Data':<12}{'Tipo':<15}{'Categoria':<20}{'Obra/Item':<20}{'Descrição':<40}{'Valor':>15}\n")
                f.write("-" * 140 + "\n")
                
                for t in dados_ordenados:
                    if t['tipo'] in ["entrada", "pagamento_parcial", "ajuste_positivo"]:
                        tipo = "Entrada"
                    elif t['tipo'] == "agendamento":
                        tipo = "Acordo"
                    elif t['tipo'] == "agendamento_cancelado":
                        tipo = "Acordo Cancelado"
                    else:
                        tipo = "Saída"
                    f.write(
                        f"{t['data']:<12}"
                        f"{tipo:<15}"
                        f"{t.get('sub_categoria', '') or t['categoria']:<20}"
                        f"{t['obra']:<20}"
                        f"{t['descricao'][:37]:<40}"
                        f"{formata_brl(t['valor']):>15}\n"
                    )
            
            messagebox.showinfo("Exportação", f"Relatório exportado (TXT) em:\n{caminho_completo}")
        
        except Exception as e:
            messagebox.showerror("Erro de Exportação", f"Não foi possível criar o arquivo. Erro: {e}")

    # --- ABA GERENCIAR PARCELAS ---
    def criar_aba_parcelas(self):
        frame = self.aba_parcelas
        
        # Corrigido o LabelFrame para usar o estilo TFrame/cor de fundo
        pagar_frame = tk.LabelFrame(frame, text="Dívidas Futuras (a Pagar)", padx=10, pady=5, bg='#F8D7DA', fg='#721C24') 
        pagar_frame.pack(fill="x", padx=10, pady=5)
        
        columns_pagar = ("Vencimento", "Parcela", "Valor", "Descrição")
        self.tree_pagar = ttk.Treeview(pagar_frame, columns=columns_pagar, show="headings", height=8)
        self.tree_pagar.pack(fill="both", expand=True)
        for col in columns_pagar:
            self.tree_pagar.heading(col, text=col)
            self.tree_pagar.column(col, width=120)
        self.tree_pagar.column("Valor", anchor='e')
        self.tree_pagar.column("Descrição", width=250)
        
        tk.Button(pagar_frame, text="Registrar Pagamento de Parcela Selecionada", command=self.pagar_parcela, bg='red', fg='white').pack(pady=5)
        
        # Corrigido o LabelFrame para usar o estilo TFrame/cor de fundo
        receber_frame = tk.LabelFrame(frame, text="Créditos Futuros (a Receber)", padx=10, pady=5, bg='#D4EDDA', fg='#155724') 
        receber_frame.pack(fill="x", padx=10, pady=5)
        
        columns_receber = ("Vencimento", "Parcela", "Valor", "Descrição")
        self.tree_receber = ttk.Treeview(receber_frame, columns=columns_receber, show="headings", height=8)
        self.tree_receber.pack(fill="both", expand=True)
        for col in columns_receber:
            self.tree_receber.heading(col, text=col)
            self.tree_receber.column(col, width=120)
        self.tree_receber.column("Valor", anchor='e')
        self.tree_receber.column("Descrição", width=250)
        
        tk.Button(receber_frame, text="Registrar Recebimento de Parcela Selecionada", command=self.receber_parcela, bg='green', fg='white').pack(pady=5)

        self.atualizar_aba_parcelas()

    def atualizar_aba_parcelas(self):
        self.tree_pagar.delete(*self.tree_pagar.get_children())
        self.tree_receber.delete(*self.tree_receber.get_children())
        
        pendencias = self.financeiro.pendencias
        
        pendencias['a_pagar'].sort(key=lambda x: x['data_vencimento'])
        pendencias['a_receber'].sort(key=lambda x: x['data_vencimento'])
        
        for p in pendencias['a_pagar']:
            self.tree_pagar.insert("", "end", values=(
                p['data_vencimento'],
                f'{p["parcela"]}/{p["detalhes"]["parcelas_totais"]}',
                formata_brl(p['valor']),
                p['descricao']
            ), iid=p['id'])

        for p in pendencias['a_receber']:
            self.tree_receber.insert("", "end", values=(
                p['data_vencimento'],
                f'{p["parcela"]}/{p["detalhes"]["parcelas_totais"]}',
                formata_brl(p['valor']),
                p['descricao']
            ), iid=p['id'])

    def pagar_parcela(self):
        selected_item = self.tree_pagar.focus()
        if not selected_item:
            messagebox.showwarning("Aviso", "Selecione uma parcela para pagar.")
            return

        item_data = self.tree_pagar.item(selected_item, 'values')
        if not messagebox.askyesno("Confirmar Pagamento", f"Confirmar pagamento de {item_data[2]} para a parcela {item_data[1]} (vencimento: {item_data[0]})?"):
            return

        pendencia_id = self.tree_pagar.item(selected_item, 'iid')
        pendencia = next((p for p in self.financeiro.pendencias['a_pagar'] if p['id'] == pendencia_id), None)
        
        if not pendencia:
            messagebox.showerror("Erro", "Pendência não encontrada.")
            return

        transacao = {
            "obra": pendencia['detalhes']['obra'] or 'N/A',
            "data": datetime.now().strftime("%Y-%m-%d"),
            "tipo": "saida_parcela",
            "valor": pendencia['valor'],
            "descricao": f"Pagamento da {pendencia['descricao']}",
            "categoria": "Despesa",
            "sub_categoria": pendencia['detalhes']['sub_categoria'],
            "origem": "pagamento_parcela",
            "parcelas_totais": pendencia['detalhes']['parcelas_totais'],
            "parcela_atual": pendencia['parcela'],
            "valor_total_compra": pendencia['detalhes']['valor_total_compra']
        }
        self.financeiro.adicionar_transacao(transacao)

        # Usar list comprehension para remover a pendência (mais seguro que .remove())
        self.financeiro.pendencias['a_pagar'] = [
            p for p in self.financeiro.pendencias['a_pagar'] 
            if p['data_vencimento'] != pendencia['data_vencimento'] or p['id'] != pendencia_id or p['parcela'] != pendencia['parcela']
        ]
        self.financeiro.salvar()
        
        messagebox.showinfo("Sucesso", "Parcela paga e abatida do saldo.")
        self.atualizar_aba_parcelas()
        self.atualizar_saldo()

    def receber_parcela(self):
        selected_item = self.tree_receber.focus()
        if not selected_item:
            messagebox.showwarning("Aviso", "Selecione uma parcela para receber.")
            return

        item_data = self.tree_receber.item(selected_item, 'values')
        if not messagebox.askyesno("Confirmar Recebimento", f"Confirmar recebimento de {item_data[2]} para a parcela {item_data[1]} (vencimento: {item_data[0]})?"):
            return

        pendencia_id = self.tree_receber.item(selected_item, 'iid')
        pendencia = next((p for p in self.financeiro.pendencias['a_receber'] if p['id'] == pendencia_id), None)
        
        if not pendencia:
            messagebox.showerror("Erro", "Crédito não encontrado.")
            return

        transacao = {
            "obra": pendencia['detalhes']['obra'] or 'N/A',
            "data": datetime.now().strftime("%Y-%m-%d"),
            "tipo": "pagamento_parcial",
            "valor": pendencia['valor'],
            "descricao": f"Recebimento da {pendencia['descricao']}",
            "categoria": "Recebimento",
            "sub_categoria": pendencia['detalhes']['sub_categoria'],
            "origem": "recebimento_parcela",
            "parcelas_totais": pendencia['detalhes']['parcelas_totais'],
            "parcela_atual": pendencia['parcela'],
            "valor_total_compra": pendencia['detalhes']['valor_total_compra']
        }
        self.financeiro.adicionar_transacao(transacao)

        self.financeiro.pendencias['a_receber'] = [
            p for p in self.financeiro.pendencias['a_receber'] 
            if p['data_vencimento'] != pendencia['data_vencimento'] or p['id'] != pendencia_id or p['parcela'] != pendencia['parcela']
        ]
        self.financeiro.salvar()
        
        messagebox.showinfo("Sucesso", "Parcela recebida e adicionada ao saldo.")
        self.atualizar_aba_parcelas()
        self.atualizar_saldo()


# --- Execução ---
def main():
    app = AppFinanceiro()
    app.mainloop()


if __name__ == "__main__":
    main()
