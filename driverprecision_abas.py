"""Abas 'Jogos' e 'Otimização avançada' da interface gráfica."""
from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import driverprecision as dp
import driverprecision_jogos as jg
import driverprecision_otimiza as ot

AZUL, VERDE, LARANJA, VERMELHO, CINZA = "#2457d6", "#2e7d32", "#d9730d", "#c62828", "#5f6b7a"
ON, OFF = "☑", "☐"


class Aba:
    """Base: fila de mensagens da thread de trabalho, barra de progresso e área de detalhes."""

    def __init__(self, root: tk.Tk, parent, titulo: str, sub: str) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        topo = ttk.Frame(parent, padding=(20, 16, 20, 4))
        topo.pack(fill="x")
        ttk.Label(topo, text=titulo, style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(topo, text=sub, style="Sub.TLabel", wraplength=860, justify="left").pack(anchor="w")
        self.corpo = ttk.Frame(parent, padding=(20, 8))
        self.corpo.pack(fill="both", expand=True)
        self.msg = ttk.Label(self.corpo, text="", style="Msg.TLabel", wraplength=860, justify="left")
        self.msg.pack(anchor="w", pady=(0, 6))
        self.barra = ttk.Progressbar(self.corpo, mode="indeterminate")
        self.base = ttk.Frame(parent, padding=(20, 8, 20, 16))
        self.base.pack(fill="x")
        self.det = tk.Text(parent, height=7, font=("Consolas", 9), wrap="word", state="disabled")
        self.btn_det = ttk.Button(self.base, text="Mostrar detalhes", command=self._toggle_det)
        self.btn_det.pack(side="left")
        root.after(150, self._poll)

    def _toggle_det(self) -> None:
        if self.det.winfo_ismapped():
            self.det.pack_forget()
            self.btn_det.config(text="Mostrar detalhes")
        else:
            self.det.pack(fill="x", padx=20, pady=(0, 12), before=self.base)
            self.btn_det.config(text="Ocultar detalhes")

    def _log(self, m: str) -> None:
        self.det.configure(state="normal")
        self.det.insert("end", m + "\n")
        self.det.see("end")
        self.det.configure(state="disabled")

    def trabalhar(self, fn, *a) -> None:
        dp.set_logger(lambda m: self.q.put(("log", m)))
        self.barra.config(mode="indeterminate")
        self.barra.pack(fill="x", pady=4, after=self.msg)
        self.barra.start(12)

        def run():
            try:
                fn(*a)
            except Exception as ex:
                self.q.put(("erro", f"{type(ex).__name__}: {ex}"))
        threading.Thread(target=run, daemon=True).start()

    def parar(self) -> None:
        self.barra.stop()
        self.barra.pack_forget()

    def _poll(self) -> None:
        try:
            while True:
                tipo, dado = self.q.get_nowait()
                if tipo == "log":
                    self._log(dado)
                elif tipo == "erro":
                    self.parar()
                    self.msg.config(text="Algo deu errado: " + dado[:200], foreground=LARANJA)
                    self.ao_erro()
                elif tipo == "prog":
                    n, tot, nome = dado
                    self.barra.stop()
                    self.barra.config(mode="determinate", maximum=tot, value=n - 1)
                    self.msg.config(text=f"{n} de {tot}: {nome}", foreground="")
                elif tipo == "pergunta":
                    titulo, texto, resp = dado
                    resp.put(messagebox.askyesno(titulo, texto, icon="warning"))
                else:
                    self.evento(tipo, dado)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def perguntar(self, titulo: str, texto: str) -> bool:
        """Chamado da thread de trabalho: pergunta na thread da interface e espera a resposta."""
        r: queue.Queue = queue.Queue()
        self.q.put(("pergunta", (titulo, texto, r)))
        return r.get()

    def evento(self, tipo, dado) -> None:  # sobrescrito
        pass

    def ao_erro(self) -> None:  # sobrescrito
        pass


def _oferecer_reinicio(texto: str) -> None:
    if messagebox.askyesno("Reiniciar", texto + "\n\nSalve seus arquivos. Reiniciar agora?"):
        subprocess.run(["shutdown.exe", "/r", "/t", "10", "/c", "DriverPrecision: concluindo"], creationflags=dp.NO_WINDOW)


# =========================================================================== Jogos

ROTULO = {"OK": "✔ Instalado", "FALTA": "✖ Falta", "DESATUALIZADO": "⚠ Desatualizado", "INFO": "ℹ Informação"}


class AbaJogos(Aba):
    def __init__(self, root, parent) -> None:
        super().__init__(root, parent, "Pronto para jogar?",
                         "Verifica os componentes que os jogos precisam para abrir — independe da placa de vídeo. "
                         "Sem eles aparecem erros como 'MSVCP140.dll não encontrado', 'd3dx9_43.dll ausente' "
                         "ou o jogo simplesmente fecha.")
        self.itens: dict[str, dict] = {}
        self.marcados: set[str] = set()
        fr = ttk.Frame(self.corpo)
        fr.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(fr, columns=("sel", "nome", "sit", "det"), show="headings", selectmode="browse")
        for c, t, w, st in (("sel", "", 36, False), ("nome", "Componente", 300, True), ("sit", "Situação", 150, False),
                            ("det", "Detalhe", 300, True)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=st, anchor="center" if c == "sel" else "w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for st, cor in (("OK", VERDE), ("FALTA", VERMELHO), ("DESATUALIZADO", LARANJA), ("INFO", CINZA)):
            self.tree.tag_configure(st, foreground=cor)
        self.tree.bind("<Button-1>", self._clique)
        self.tree.bind("<<TreeviewSelect>>", self._mostra_desc)
        self.desc = ttk.Label(self.corpo, text="", style="Sub.TLabel", wraplength=860, justify="left")
        self.desc.pack(anchor="w", pady=(6, 0))
        self.btn = ttk.Button(self.base, text="Verificar", style="Grande.TButton", command=self.verificar)
        self.btn.pack(side="right")
        self.msg.config(text="Clique em Verificar. Leva poucos segundos.")

    def verificar(self) -> None:
        self.btn.config(state="disabled")
        self.msg.config(text="Verificando componentes...", foreground="")
        self.trabalhar(lambda: self.q.put(("lista", jg.verificar())))

    def evento(self, tipo, dado) -> None:
        if tipo == "lista":
            self.parar()
            self._preenche(dado)
        elif tipo == "fim":
            self.parar()
            ok, falha = len(dado["ok"]), len(dado["falha"])
            self.msg.config(text=(f"✔ {ok} componente(s) instalado(s)." if not falha else
                                  f"{ok} instalado(s), {falha} com falha (veja os detalhes)."),
                            foreground=VERDE if not falha else LARANJA)
            if dado["reboot"]:
                _oferecer_reinicio("Algum componente pede reinício para concluir.")
            self.verificar()

    def ao_erro(self) -> None:
        self.btn.config(text="Verificar", state="normal", command=self.verificar)

    def _preenche(self, itens: list[dict]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.itens = {i["id"]: i for i in itens}
        self.marcados = set(jg.pendentes(itens))
        for i in itens:
            sel = ON if i["id"] in self.marcados else (OFF if i["status"] in ("FALTA", "DESATUALIZADO") and i["instalavel"] else "")
            nome = i["nome"] + ("  (opcional)" if i["opcional"] else "")
            self.tree.insert("", "end", iid=i["id"], values=(sel, nome, ROTULO.get(i["status"], i["status"]), i["detalhe"]),
                             tags=(i["status"],))
        falta = [i for i in itens if i["status"] in ("FALTA", "DESATUALIZADO") and not i["opcional"] and i["instalavel"]]
        if falta:
            self.msg.config(text=f"Faltam {len(falta)} componente(s) para os jogos funcionarem bem.", foreground=AZUL)
        else:
            self.msg.config(text="✔ Tudo pronto! Este computador tem tudo o que os jogos precisam.", foreground=VERDE)
        self._botao()

    def _botao(self) -> None:
        n = len(self.marcados)
        if n and dp.is_admin():
            self.btn.config(text=f"Instalar {n} componente(s)", state="normal", command=self.instalar)
        elif n:
            self.btn.config(text="Instalar (precisa de administrador)", state="disabled")
        else:
            self.btn.config(text="Verificar de novo", state="normal", command=self.verificar)

    def _clique(self, ev) -> None:
        iid = self.tree.identify_row(ev.y)
        if not iid or self.tree.set(iid, "sel") == "":  # sem caixinha = nada a instalar
            return
        if iid in self.marcados:
            self.marcados.discard(iid)
            self.tree.set(iid, "sel", OFF)
        else:
            self.marcados.add(iid)
            self.tree.set(iid, "sel", ON)
        self._botao()

    def _mostra_desc(self, _=None) -> None:
        s = self.tree.selection()
        if s and s[0] in self.itens:
            self.desc.config(text=self.itens[s[0]]["desc"])

    def instalar(self) -> None:
        ids = [i for i in self.tree.get_children() if i in self.marcados]
        if not messagebox.askokcancel("Instalar componentes",
                                      f"Vamos baixar e instalar {len(ids)} componente(s) direto da Microsoft "
                                      "(OpenAL: Creative). Pode levar alguns minutos.", icon="info"):
            return
        self.btn.config(state="disabled")
        self.msg.config(text="Preparando...", foreground="")

        def job():
            dp.log("Criando ponto de restauração...")
            ok, m = dp.ponto_restauracao()
            dp.log("  " + ("criado" if ok else f"não foi possível ({m[:120]}); seguindo, componentes são de baixo risco"))
            r = jg.instalar(ids, lambda n, t, nome: self.q.put(("prog", (n, t, nome))))
            self.q.put(("fim", r))
        self.trabalhar(job)


# =========================================================================== Otimização

COR_RISCO = {"baixo": VERDE, "médio": LARANJA, "alto": VERMELHO}
ROT_EST = {"ATIVO": "● Ativo", "PADRÃO": "○ Padrão do Windows", "PARCIAL": "◐ Parcial", "N/A": "— Não se aplica"}


class AbaOtimizacao(Aba):
    def __init__(self, root, parent) -> None:
        super().__init__(root, parent, "Otimização avançada",
                         "Ajustes profundos do Windows para jogos. Marque o que quer aplicar. Antes de mexer, o valor "
                         "original de cada configuração é guardado e um ponto de restauração é criado — "
                         "tudo pode ser desfeito por aqui.")
        self.ajustes: dict[str, dict] = {}
        self.marcados: set[str] = set()
        fr = ttk.Frame(self.corpo)
        fr.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(fr, columns=("sel", "risco", "estado"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Ajuste")
        self.tree.column("#0", width=430, stretch=True)
        for c, t, w in (("sel", "", 40), ("risco", "Risco", 90), ("estado", "Estado atual", 180)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=False, anchor="center" if c != "estado" else "w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for r, cor in COR_RISCO.items():
            self.tree.tag_configure(r, foreground=cor)
        self.tree.tag_configure("cat", font=("Segoe UI Semibold", 10))
        self.tree.bind("<Button-1>", self._clique)
        self.tree.bind("<<TreeviewSelect>>", self._mostra_desc)
        self.desc = ttk.Label(self.corpo, text="Clique num ajuste para ver o que ele faz.", style="Sub.TLabel",
                              wraplength=860, justify="left")
        self.desc.pack(anchor="w", pady=(6, 0))

        self.btn = ttk.Button(self.base, text="Aplicar marcados", style="Grande.TButton", command=self.aplicar)
        self.btn.pack(side="right")
        self.btn_desf = ttk.Button(self.base, text="Desfazer marcados", command=self.desfazer)
        self.btn_desf.pack(side="right", padx=(0, 8))
        self.btn_tudo = ttk.Button(self.base, text="Desfazer tudo", command=self.desfazer_tudo)
        self.btn_tudo.pack(side="right", padx=(0, 8))
        self.btn_rec = ttk.Button(self.base, text="Marcar recomendados", command=self.recomendados)
        self.btn_rec.pack(side="left", padx=(8, 0))
        self.msg.config(text="Lendo configurações atuais...")
        self._botoes(False)
        self.trabalhar(lambda: self.q.put(("lista", ot.listar())))

    def _botoes(self, on: bool) -> None:
        on = on and dp.is_admin()
        for b in (self.btn, self.btn_desf, self.btn_tudo):
            b.config(state="normal" if on else "disabled")
        if not dp.is_admin():
            self.msg.config(text="Abra o programa como administrador para aplicar ajustes.", foreground=LARANJA)

    def evento(self, tipo, dado) -> None:
        if tipo == "lista":
            self.parar()
            self._preenche(dado)
        elif tipo == "fim":
            self.parar()
            ok, falha, rb = dado
            self.msg.config(text=f"✔ {ok} ajuste(s) concluído(s)." + (f" {len(falha)} com problema (veja os detalhes)." if falha else ""),
                            foreground=VERDE if not falha else LARANJA)
            if rb:
                _oferecer_reinicio("Alguns ajustes só valem depois de reiniciar.")
            self.trabalhar(lambda: self.q.put(("lista", ot.listar())))

    def ao_erro(self) -> None:
        self._botoes(True)

    def _preenche(self, lista: list[dict]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.ajustes = {a["id"]: a for a in lista}
        self.marcados.clear()
        cats: dict[str, str] = {}
        for a in lista:
            if a["cat"] not in cats:
                cats[a["cat"]] = self.tree.insert("", "end", text=a["cat"], open=True, tags=("cat",))
            nome = a["nome"] + ("  ⚠ reduz segurança" if a["seguranca"] else "") + ("  ↻" if a["reboot"] else "")
            self.tree.insert(cats[a["cat"]], "end", iid=a["id"], text=nome,
                             values=(OFF if a["estado"] != "N/A" else "", a["risco"], ROT_EST.get(a["estado"], a["estado"])),
                             tags=(a["risco"],))
        n_at = sum(1 for a in lista if a["estado"] == "ATIVO")
        self.msg.config(text=f"{n_at} de {len(lista)} ajustes já estão ativos. ↻ = precisa reiniciar.", foreground="")
        self._botoes(True)

    def _clique(self, ev) -> None:
        iid = self.tree.identify_row(ev.y)
        if not iid or iid not in self.ajustes or self.tree.set(iid, "sel") == "":
            return
        if iid in self.marcados:
            self.marcados.discard(iid)
            self.tree.set(iid, "sel", OFF)
        else:
            self.marcados.add(iid)
            self.tree.set(iid, "sel", ON)

    def _mostra_desc(self, _=None) -> None:
        s = self.tree.selection()
        if s and s[0] in self.ajustes:
            a = self.ajustes[s[0]]
            self.desc.config(text=f"{a['nome']} — risco {a['risco']}. {a['desc']}")

    def recomendados(self) -> None:
        for iid, a in self.ajustes.items():
            marcar = a["risco"] in ("baixo", "médio") and a["estado"] in ("PADRÃO", "PARCIAL")
            if self.tree.set(iid, "sel") == "":
                continue
            (self.marcados.add if marcar else self.marcados.discard)(iid)
            self.tree.set(iid, "sel", ON if marcar else OFF)

    def _executa(self, ids: list[str], fn, verbo: str, criar_rp: bool) -> None:
        self._botoes(False)

        def job():
            if criar_rp:
                dp.log("Criando ponto de restauração...")
                ok, m = dp.ponto_restauracao()
                dp.log("  " + ("criado" if ok else f"não foi possível: {m[:160]}"))
                if not ok and not self.perguntar(
                        "Ponto de restauração",
                        "Não foi possível criar um ponto de restauração (a Proteção do Sistema pode estar desligada).\n\n"
                        "Os valores originais continuam salvos e o botão Desfazer funciona.\n\nContinuar?"):
                    self.q.put(("lista", ot.listar()))
                    return
            falha, rb = [], False
            for n, aid in enumerate(ids, 1):
                a = ot.POR_ID[aid]
                self.q.put(("prog", (n, len(ids), f"{verbo}: {a['nome']}")))
                try:
                    dp.log(f"{verbo}: {a['nome']} -> {fn(aid)}")
                    rb = rb or a.get("reboot", False)
                except Exception as ex:
                    dp.log(f"{verbo}: {a['nome']} -> FALHOU: {ex}")
                    falha.append(aid)
            self.q.put(("fim", (len(ids) - len(falha), falha, rb)))
        self.trabalhar(job)

    def aplicar(self) -> None:
        ids = [i for i in self.ajustes if i in self.marcados]
        if not ids:
            messagebox.showinfo("Otimização", "Marque pelo menos um ajuste (clique na caixinha).")
            return
        fortes = [ot.POR_ID[i] for i in ids if ot.POR_ID[i]["risco"] == "alto" or ot.POR_ID[i].get("seguranca")]
        texto = f"Aplicar {len(ids)} ajuste(s)?"
        if fortes:
            texto += "\n\nAtenção, ajustes de risco ALTO:\n" + "\n".join(f"• {a['nome']}" for a in fortes) + \
                     "\n\nLeia a descrição de cada um. Se algo der errado, use Desfazer (ou o ponto de restauração)."
        if not messagebox.askyesno("Otimização avançada", texto, icon="warning" if fortes else "question"):
            return
        self._executa(ids, ot.aplicar, "Aplicando", True)

    def desfazer(self) -> None:
        ids = [i for i in self.ajustes if i in self.marcados]
        if ids:
            self._executa(ids, ot.desfazer, "Desfazendo", False)

    def desfazer_tudo(self) -> None:
        ids = ot.aplicados()
        if not ids:
            messagebox.showinfo("Otimização", "Nenhum ajuste foi aplicado por este programa.")
            return
        if messagebox.askyesno("Desfazer tudo", f"Voltar {len(ids)} ajuste(s) ao valor original?"):
            self._executa(ids, ot.desfazer, "Desfazendo", False)
