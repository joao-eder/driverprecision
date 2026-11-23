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
import driverprecision_saude as sd
import driverprecision_tema as tema
from driverprecision_tema import AZUL, CINZA, LARANJA, VERDE, VERMELHO
ON, OFF = "☑", "☐"


class Aba:
    """Base: fila de mensagens da thread de trabalho, barra de progresso e área de detalhes."""

    def __init__(self, root: tk.Tk, parent, titulo: str, sub: str) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        topo = ttk.Frame(parent, padding=(28, 24, 28, 4))
        topo.pack(fill="x")
        ttk.Label(topo, text=titulo, style="Titulo.TLabel").pack(anchor="w")
        self.sub = ttk.Label(topo, text=sub, style="Sub.TLabel", wraplength=820, justify="left")
        self.sub.pack(anchor="w")
        self.corpo = ttk.Frame(parent, padding=(28, 12))
        self.corpo.pack(fill="both", expand=True)
        self.msg = ttk.Label(self.corpo, text="", style="Msg.TLabel", wraplength=820, justify="left")
        self.msg.pack(anchor="w", pady=(0, 6))
        tema.quebra_automatica(parent, self.sub, self.msg)
        self.barra = ttk.Progressbar(self.corpo, mode="indeterminate")
        self.base = ttk.Frame(parent, padding=(28, 10, 28, 22))
        self.base.pack(side="bottom", fill="x", before=self.corpo)  # botões sempre visíveis, mesmo em tela baixa
        self.det = tema.texto_log(parent, height=7)
        self.btn_det = ttk.Button(self.base, text="Detalhes", command=self._toggle_det)
        self.btn_det.pack(side="left")
        root.after(150, self._poll)

    def _toggle_det(self) -> None:
        if self.det.winfo_ismapped():
            self.det.pack_forget()
            self.btn_det.config(text="Detalhes")
        else:
            self.det.pack(side="bottom", fill="x", padx=28, pady=(0, 12), after=self.base)
            self.btn_det.config(text="Ocultar")

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
        fr, self.tree = tema.lista(self.corpo, columns=("sel", "nome", "sit", "det"), show="headings", selectmode="browse")
        tema.barra_selecao(self.corpo, self.marcar_todos, self.desmarcar_todos).pack(fill="x", pady=(4, 6))
        fr.pack(fill="both", expand=True)
        for c, t, w, st in (("sel", "", 36, False), ("nome", "Componente", 230, True), ("sit", "Situação", 130, False),
                            ("det", "Detalhe", 190, True)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=st, anchor="center" if c == "sel" else "w")
        for st, cor in (("OK", tema.TEXTO), ("FALTA", VERMELHO), ("DESATUALIZADO", LARANJA), ("INFO", CINZA)):
            self.tree.tag_configure(st, foreground=cor)
        self.tree.bind("<Button-1>", self._clique)
        self.tree.bind("<<TreeviewSelect>>", self._mostra_desc)
        self.desc = ttk.Label(self.corpo, text="", style="Sub.TLabel", wraplength=820, justify="left")
        self.desc.pack(side="bottom", anchor="w", pady=(6, 0), before=fr)  # a explicação nunca some
        tema.quebra_automatica(parent, self.desc)
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

    def _marcar(self, sim: bool) -> None:
        for iid in self.tree.get_children():
            if iid in self.itens and self.tree.set(iid, "sel") != "":  # só o que tem caixinha (dá para instalar)
                (self.marcados.add if sim else self.marcados.discard)(iid)
                self.tree.set(iid, "sel", ON if sim else OFF)
        self._botao()

    def marcar_todos(self) -> None:
        self._marcar(True)

    def desmarcar_todos(self) -> None:
        self._marcar(False)

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

COR_RISCO = {"baixo": tema.TEXTO, "médio": tema.TEXTO, "alto": VERMELHO}
ROT_EST = {"ATIVO": "● Ativo", "PADRÃO": "○ Padrão", "PARCIAL": "◐ Parcial", "N/A": "— Não se aplica"}


TEXTOS_PERFIL = {
    "jogos": ("Otimização avançada",
              "Ajustes profundos do Windows para jogos. Marque o que quer aplicar. Antes de mexer, o valor "
              "original de cada configuração é guardado (e, com a Proteção do sistema ligada, é criado um ponto de restauração) — "
              "tudo pode ser desfeito por aqui."),
    "escritorio": ("Escritório",
                   "Para trabalhar com muitas abas, planilhas (Excel, Google Planilhas, LibreOffice), pastas e impressoras "
                   "da rede e VPN, com mais segurança. O valor original de cada configuração é guardado e tudo pode ser desfeito."),
}


class AbaOtimizacao(Aba):
    def __init__(self, root, parent, perfil: str = "jogos") -> None:
        self.perfil = perfil
        super().__init__(root, parent, *TEXTOS_PERFIL[perfil])
        self.ajustes: dict[str, dict] = {}
        self.marcados: set[str] = set()
        fr, self.tree = tema.lista(self.corpo, columns=("sel", "risco", "estado"), show="tree headings", selectmode="browse")
        tema.barra_selecao(self.corpo, self.marcar_todos, self.desmarcar_todos,
                           ("Marcar recomendados", self.recomendados)).pack(fill="x", pady=(4, 6))
        fr.pack(fill="both", expand=True)
        self.tree.heading("#0", text="Ajuste")
        self.tree.column("#0", width=290, minwidth=200, stretch=True)
        for c, t, w in (("sel", "", 36), ("risco", "Risco", 70), ("estado", "Estado atual", 200)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=False, anchor="center" if c != "estado" else "w")
        for r, cor in COR_RISCO.items():
            self.tree.tag_configure(r, foreground=cor)
        self.tree.tag_configure("cat", font=(tema.FONTE, 10, "bold"), foreground=tema.SUAVE, background=tema.CARTAO_2)
        self.tree.tag_configure("bloq", foreground=tema.APAGADO)
        self.tree.bind("<Button-1>", self._clique)
        self.tree.bind("<<TreeviewSelect>>", self._mostra_desc)
        self.desc = ttk.Label(self.corpo, text="Clique num ajuste para ver o que ele faz.", style="Sub.TLabel",
                              wraplength=820, justify="left")
        self.desc.pack(side="bottom", anchor="w", pady=(6, 0), before=fr)  # a explicação nunca some
        tema.quebra_automatica(parent, self.desc)

        self.btn = ttk.Button(self.base, text="Aplicar marcados", style="Grande.TButton", command=self.aplicar)
        self.btn.pack(side="right")
        self.btn_desf = ttk.Button(self.base, text="Desfazer", command=self.desfazer)
        self.btn_desf.pack(side="right", padx=(0, 8))
        self.btn_tudo = ttk.Button(self.base, text="Desfazer tudo", command=self.desfazer_tudo)
        self.btn_tudo.pack(side="right", padx=(0, 8))
        self.msg.config(text="Lendo configurações atuais...")
        self._botoes(False)
        self.trabalhar(lambda: self.q.put(("lista", ot.listar(self.perfil))))

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
            self.trabalhar(lambda: self.q.put(("lista", ot.listar(self.perfil))))

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
            nome = a["nome"] + ("  ⚠ reduz segurança" if a["seguranca"] else "")
            empresa = a.get("bloqueado", "").startswith("PC gerenciado")
            est = ROT_EST.get(a["estado"], a["estado"]) + ("  ↻ reinicie" if a.get("reiniciar") else "") + \
                ("  🔒 empresa" if empresa else "")
            pode = a["estado"] != "N/A" and not a.get("bloqueado")
            self.tree.insert(cats[a["cat"]], "end", iid=a["id"], text=nome,
                             values=(OFF if pode else "", a["risco"], est),
                             tags=("bloq",) if empresa else (a["risco"],))
        n_at = sum(1 for a in lista if a["estado"] == "ATIVO")
        n_rb = sum(1 for a in lista if a.get("reiniciar"))
        n_emp = sum(1 for a in lista if a.get("bloqueado", "").startswith("PC gerenciado"))
        txt = f"{n_at} de {len(lista)} ajustes estão ativos."
        if n_rb:
            txt += f" {n_rb} só passam a valer quando você reiniciar o PC (↻)."
        if n_emp:
            txt += f" PC da empresa: {n_emp} ajuste(s) ficam com a TI (🔒)."
        self.msg.config(text=txt, foreground=LARANJA if n_rb else "")
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
            extra = " Aguardando você reiniciar o PC." if a.get("reiniciar") else (" Precisa reiniciar para valer." if a["reboot"] else "")
            if a.get("bloqueado"):
                extra += f" [{a['bloqueado'][0].upper() + a['bloqueado'][1:]}.]"
            self.desc.config(text=f"{a['nome']} — risco {a['risco']}. {a['desc']}{extra}")

    def _marcar(self, sim: bool) -> None:
        for iid in self.ajustes:  # só ajustes com caixinha (não as categorias, nem "não se aplica"/empresa)
            if self.tree.exists(iid) and self.tree.set(iid, "sel") != "":
                (self.marcados.add if sim else self.marcados.discard)(iid)
                self.tree.set(iid, "sel", ON if sim else OFF)

    def marcar_todos(self) -> None:
        self._marcar(True)

    def desmarcar_todos(self) -> None:
        self._marcar(False)

    def recomendados(self) -> None:
        for iid, a in self.ajustes.items():
            marcar = a["risco"] in ("baixo", "médio") and a["estado"] in ("PADRÃO", "PARCIAL") and a.get("recomendado", True)
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
                    self.q.put(("lista", ot.listar(self.perfil)))
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
        ids = [i for i in ot.aplicados() if i in self.ajustes]  # só os desta tela
        if not ids:
            messagebox.showinfo("Desfazer tudo", "Nenhum ajuste desta tela foi aplicado por este programa.")
            return
        if messagebox.askyesno("Desfazer tudo", f"Voltar {len(ids)} ajuste(s) ao valor original?"):
            self._executa(ids, ot.desfazer, "Desfazendo", False)


# =========================================================================== Saúde do PC

ROT_SAUDE = {"OK": "✔ OK", "ATENÇÃO": "⚠ Atenção", "PROBLEMA": "✖ Problema", "INFO": "ℹ Informação"}


class AbaSaude(Aba):
    def __init__(self, root, parent) -> None:
        super().__init__(root, parent, "Saúde do PC",
                         "Segurança, integridade do Windows, memória e rede numa olhada só. A verificação só lê; "
                         "nada é alterado até você clicar num reparo.")
        self.itens: dict[str, dict] = {}
        fr, self.tree = tema.lista(self.corpo, columns=("sit", "det"), show="tree headings", selectmode="browse")
        fr.pack(fill="both", expand=True, pady=(4, 0))
        self.tree.heading("#0", text="Item")
        self.tree.column("#0", width=300, minwidth=230, stretch=True)
        self.tree.heading("sit", text="Situação")
        self.tree.column("sit", width=115, stretch=False)
        self.tree.heading("det", text="Detalhe")
        self.tree.column("det", width=260, stretch=True)
        for st, cor in (("OK", tema.TEXTO), ("ATENÇÃO", LARANJA), ("PROBLEMA", VERMELHO), ("INFO", CINZA)):
            self.tree.tag_configure(st, foreground=cor)
        self.tree.tag_configure("cat", font=(tema.FONTE, 10, "bold"), foreground=tema.SUAVE, background=tema.CARTAO_2)
        self.tree.bind("<<TreeviewSelect>>", self._mostra)

        rep = ttk.Frame(self.corpo)
        rep.pack(side="bottom", fill="x", pady=(8, 0), before=fr)
        self.desc = ttk.Label(self.corpo, text="Clique num item para ver a dica. Passe o mouse num reparo para ver o que ele faz.",
                              style="Sub.TLabel", wraplength=820, justify="left")
        self.desc.pack(side="bottom", anchor="w", pady=(6, 0), before=rep)
        tema.quebra_automatica(parent, self.desc)
        ttk.Label(rep, text="Reparos", style="Sub.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.botoes_rep = []
        for n, r in enumerate(sd.REPAROS):
            b = ttk.Button(rep, text=r["nome"], style="Rep.TButton", command=lambda rid=r["id"]: self.reparar(rid))
            b.grid(row=1 + n // 4, column=n % 4, sticky="ew", padx=(0, 6), pady=(0, 6))
            b.bind("<Enter>", lambda _e, r=r: self.desc.config(
                text=f"{r['nome']} ({r['tempo']}). {r['desc']}" + (" Pede reinício." if r["reboot"] else "")))
            self.botoes_rep.append(b)
        for c in range(4):
            rep.columnconfigure(c, weight=1, uniform="reparos")

        self.btn = ttk.Button(self.base, text="Verificar de novo", style="Grande.TButton", command=self.verificar)
        self.btn.pack(side="right")
        self.verificar()

    def _estado_botoes(self, on: bool) -> None:
        self.btn.config(state="normal" if on else "disabled")
        for b in self.botoes_rep:
            b.config(state="normal" if on and dp.is_admin() else "disabled")

    def verificar(self) -> None:
        self._estado_botoes(False)
        self.msg.config(text="Verificando segurança, disco, memória e rede (até 1 minuto)...", foreground="")
        self.trabalhar(lambda: self.q.put(("diag", sd.avaliar(sd.diagnostico(), ot.ambiente()))))

    def evento(self, tipo, dado) -> None:
        if tipo == "diag":
            self.parar()
            self._preenche(dado)
            self._estado_botoes(True)
        elif tipo == "rep":
            self.parar()
            r, (ok, rb, msg) = dado
            self.msg.config(text=("✔ " if ok else "⚠ ") + f"{r['nome']}: {msg[:220]}", foreground=VERDE if ok else LARANJA)
            if rb and ok:
                _oferecer_reinicio(f"{r['nome']} pede reinício para concluir.")
            self._estado_botoes(True)

    def ao_erro(self) -> None:
        self._estado_botoes(True)

    def _preenche(self, itens: list[dict]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.itens.clear()
        grupos: dict[str, str] = {}
        # o que precisa de ação primeiro: grupos e itens em ordem de gravidade
        peso = {"PROBLEMA": 0, "ATENÇÃO": 1, "INFO": 2, "OK": 3}
        pior = {}
        for i in itens:
            pior[i["grupo"]] = min(pior.get(i["grupo"], 9), peso.get(i["status"], 2))
        itens = sorted(itens, key=lambda i: (pior[i["grupo"]], peso.get(i["status"], 2)))
        for n, i in enumerate(itens):
            if i["grupo"] not in grupos:
                grupos[i["grupo"]] = self.tree.insert("", "end", text=i["grupo"], open=True, tags=("cat",))
            iid = f"s{n}"
            self.itens[iid] = i
            self.tree.insert(grupos[i["grupo"]], "end", iid=iid, text=i["nome"],
                             values=(ROT_SAUDE.get(i["status"], i["status"]), i["detalhe"]), tags=(i["status"],))
        prob = sum(1 for i in itens if i["status"] == "PROBLEMA")
        aten = sum(1 for i in itens if i["status"] == "ATENÇÃO")
        if prob or aten:
            partes = ([f"{prob} problema(s)"] if prob else []) + ([f"{aten} ponto(s) de atenção"] if aten else [])
            self.msg.config(text=" e ".join(partes) + ". Clique em cada um para ver o que fazer.",
                            foreground=VERMELHO if prob else LARANJA)
        else:
            self.msg.config(text="✔ Tudo em ordem neste PC.", foreground=VERDE)

    def _mostra(self, _=None) -> None:
        s = self.tree.selection()
        if s and s[0] in self.itens:
            i = self.itens[s[0]]
            txt = f"{i['nome']}: {i['detalhe']}." + (f" {i['dica']}" if i["dica"] else "")
            if i.get("reparo"):
                txt += f" → Reparo sugerido: {sd.REP_ID[i['reparo']]['nome']}."
            if i.get("ajuste"):
                txt += f" → Ajuste: {ot.POR_ID[i['ajuste']]['nome']} (tela Escritório)."
            self.desc.config(text=txt)

    def reparar(self, rid: str) -> None:
        r = sd.REP_ID[rid]
        if not messagebox.askyesno(r["nome"], f"{r['desc']}\n\nTempo: {r['tempo']}." +
                                   ("\nPode pedir para reiniciar no final." if r["reboot"] else "") + "\n\nContinuar?"):
            return
        self._estado_botoes(False)
        self.msg.config(text=f"{r['nome']}... ({r['tempo']})", foreground="")

        def job():
            dp.log(f"Reparo: {r['nome']}")
            try:
                res = sd.executar(rid)
            except Exception as ex:
                res = (False, False, f"{type(ex).__name__}: {ex}")
            dp.log("  " + res[2])
            self.q.put(("rep", (r, res)))
        self.trabalhar(job)
