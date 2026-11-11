"""
Interface gráfica do DriverPrecision para usuário comum.

Fluxo: [Verificar agora] -> lista do que foi encontrado (já marcado) -> [Instalar] -> pronto.
Tudo o que é técnico fica no relatório e em "Mostrar detalhes".
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import driverprecision as dp

AZUL = "#2457d6"
VERDE = "#2e7d32"
LARANJA = "#d9730d"
CINZA = "#5f6b7a"


def _elevar_se_preciso() -> bool:
    """Reabre o programa como administrador (1 aviso do UAC). True = este processo deve encerrar."""
    if dp.is_admin() or "--sem-elevar" in sys.argv:
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, "--sem-elevar"
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        params = f'"{os.path.abspath(sys.argv[0])}" --sem-elevar'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.getcwd(), 1)
    return r > 32  # usuário recusou o UAC: segue sem admin (só verifica)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.estado: dict | None = None
        self.itens: dict[str, dict] = {}
        self.marcados: set[str] = set()
        self.relatorio = None

        root.title(f"DriverPrecision {dp.VERSION}")
        root.geometry("940x680")
        root.minsize(720, 560)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        st = ttk.Style()
        st.configure("Titulo.TLabel", font=("Segoe UI Semibold", 18))
        st.configure("Sub.TLabel", font=("Segoe UI", 10), foreground=CINZA)
        st.configure("Msg.TLabel", font=("Segoe UI Semibold", 13))
        st.configure("Grande.TButton", font=("Segoe UI Semibold", 12), padding=(18, 10))
        st.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        st.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

        topo = ttk.Frame(root, padding=(20, 16, 20, 4))
        topo.pack(fill="x")
        ttk.Label(topo, text="Drivers do seu computador", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(topo, text="Encontra e instala o driver certo de cada peça, direto do fabricante. "
                             "Nada de driver genérico.", style="Sub.TLabel", wraplength=760).pack(anchor="w")

        self.corpo = ttk.Frame(root, padding=(20, 10))
        self.corpo.pack(fill="both", expand=True)

        self.msg = ttk.Label(self.corpo, text="Clique em Verificar agora. Leva de 1 a 3 minutos.",
                             style="Msg.TLabel", wraplength=760, justify="left")
        self.msg.pack(anchor="w", pady=(0, 8))
        self.passo = ttk.Label(self.corpo, text="", style="Sub.TLabel")
        self.passo.pack(anchor="w")
        self.barra = ttk.Progressbar(self.corpo, mode="indeterminate")

        self.lista_frame = ttk.Frame(self.corpo)
        self.tree = ttk.Treeview(self.lista_frame, columns=("sel", "disp", "atual", "novo", "fonte"),
                                 show="headings", selectmode="none")
        for col, txt, w, anc in (("sel", "", 36, "center"), ("disp", "Peça do computador", 380, "w"),
                                 ("atual", "Versão atual", 130, "w"), ("novo", "Nova versão", 130, "w"),
                                 ("fonte", "Origem", 150, "w")):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor=anc, stretch=col == "disp")
        sb = ttk.Scrollbar(self.lista_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._toggle)
        self.aviso = ttk.Label(self.corpo, text="", style="Sub.TLabel", wraplength=760, justify="left")

        self.det_frame = ttk.Frame(self.corpo)
        self.txt = tk.Text(self.det_frame, height=10, font=("Consolas", 9), wrap="word", state="disabled")
        self.txt.pack(fill="both", expand=True)

        base = ttk.Frame(root, padding=(20, 8, 20, 16))
        base.pack(fill="x")
        self.btn = ttk.Button(base, text="Verificar agora", style="Grande.TButton", command=self.verificar)
        self.btn.pack(side="right")
        self.btn2 = ttk.Button(base, text="Ver relatório completo", command=self.abrir_relatorio)
        self.btn_det = ttk.Button(base, text="Mostrar detalhes", command=self._detalhes)
        self.btn_det.pack(side="left")

        if not dp.is_admin():
            self.passo.config(text="Sem permissão de administrador: é possível verificar, mas não instalar. "
                                   "Abra de novo e aceite o aviso do Windows para instalar.")
        dp.set_logger(lambda m: self.q.put(("log", m)))
        root.after(100, self._poll)

    # ------------------------------------------------------------------ util
    def _detalhes(self) -> None:
        if self.det_frame.winfo_ismapped():
            self.det_frame.pack_forget()
            self.btn_det.config(text="Mostrar detalhes")
        else:
            self.det_frame.pack(fill="both", expand=True, pady=(8, 0))
            self.btn_det.config(text="Ocultar detalhes")

    def _log(self, m: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", m + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")
        s = m.strip()
        if s.startswith("[") and "]" in s[:8]:
            self.passo.config(text=s)

    def _poll(self) -> None:
        try:
            while True:
                tipo, dado = self.q.get_nowait()
                if tipo == "log":
                    self._log(dado)
                elif tipo == "scan_ok":
                    self._mostrar_resultado(dado)
                elif tipo == "erro":
                    self._erro(dado)
                elif tipo == "prog":
                    n, tot, titulo = dado
                    self.barra.config(mode="determinate", maximum=tot, value=n - 1)
                    self.msg.config(text=f"Instalando {n} de {tot}: {titulo}")
                elif tipo == "inst_ok":
                    self._fim_instalacao(dado)
                elif tipo == "pergunta_rp":
                    ok = messagebox.askyesno(
                        "Ponto de restauração",
                        "Não foi possível criar um ponto de restauração do Windows "
                        "(a Proteção do Sistema pode estar desligada).\n\n"
                        "Sem ele, desfazer uma instalação fica mais difícil.\n\nContinuar mesmo assim?",
                        icon="warning")
                    dado.put(ok)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _ocupado(self, texto: str) -> None:
        self.btn.config(state="disabled")
        self.btn2.pack_forget()
        self.lista_frame.pack_forget()
        self.aviso.pack_forget()
        self.msg.config(text=texto, foreground="")
        self.barra.config(mode="indeterminate")
        self.barra.pack(fill="x", pady=8, before=self.passo)
        self.barra.start(12)

    def _erro(self, e: str) -> None:
        self.barra.stop()
        self.barra.pack_forget()
        self.msg.config(text="Algo deu errado. Verifique a internet e tente de novo.", foreground=LARANJA)
        self.passo.config(text=e[:300])
        self.btn.config(text="Tentar de novo", state="normal", command=self.verificar)

    # ------------------------------------------------------------------ verificar
    def verificar(self) -> None:
        self._ocupado("Verificando o hardware e procurando os drivers certos...")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

        def trabalho():
            try:
                args = argparse.Namespace(sem_oem=False, sem_wu=False, sem_catalogo=False, nao_abrir=True)
                self.q.put(("scan_ok", dp.scan(args)))
            except Exception as ex:
                self.q.put(("erro", f"{type(ex).__name__}: {ex}"))
        threading.Thread(target=trabalho, daemon=True).start()

    def _mostrar_resultado(self, e: dict) -> None:
        self.estado = e
        self.barra.stop()
        self.barra.pack_forget()
        self.relatorio = e.get("relatorio")
        self.btn2.pack(side="right", padx=(0, 10))
        s = e["system"]
        self.passo.config(text=f"{s.get('mfr') or ''} {s.get('model') or ''} · {s.get('os') or ''} · "
                               f"{len(e['devices'])} peças verificadas")
        rec = dp.recomendados(e)
        self.tree.delete(*self.tree.get_children())
        self.itens.clear()
        self.marcados.clear()
        for d, b in rec:
            iid = b["cid"]
            self.itens[iid] = b
            self.marcados.add(iid)
            novo = b.get("version") or b.get("pkg_version") or "?"
            origem = {"CAT": "Microsoft (WHQL)", "WU": "Windows Update"}.get(
                b["source"], "Fabricante " + b["source_name"].split(" (")[0])
            self.tree.insert("", "end", iid=iid, values=("☑", d["name"], d.get("ver") or "nenhum", novo, origem))
        extras = []
        n_ver = sum(1 for d in e["devices"] if d["status"] in ("VERIFICAR", "GENÉRICO", "SEM DRIVER"))
        if n_ver:
            extras.append(f"{n_ver} item(ns) precisam de conferência técnica e não serão instalados "
                          "automaticamente (veja o relatório).")
        if any(x.get("status") == "ATUALIZAR" for x in e["sistema"]):
            extras.append("Há atualização de BIOS/firmware. Por segurança ela não é instalada "
                          "automaticamente: veja o relatório.")
        if rec:
            self.msg.config(text=f"Encontramos {len(rec)} driver(s) para instalar ou atualizar.", foreground=AZUL)
            self.lista_frame.pack(fill="both", expand=True, pady=(8, 4))
            self._atualiza_botao()
        else:
            self.msg.config(text="✔ Tudo certo! Os drivers deste computador estão em dia.", foreground=VERDE)
            self.btn.config(text="Verificar de novo", state="normal", command=self.verificar)
        if extras:
            self.aviso.config(text="\n".join(extras))
            self.aviso.pack(anchor="w", pady=(4, 0))

    def _toggle(self, ev) -> None:
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        if iid in self.marcados:
            self.marcados.discard(iid)
            self.tree.set(iid, "sel", "☐")
        else:
            self.marcados.add(iid)
            self.tree.set(iid, "sel", "☑")
        self._atualiza_botao()

    def _atualiza_botao(self) -> None:
        n = len(self.marcados)
        if not dp.is_admin():
            self.btn.config(text="Instalar (precisa de administrador)", state="disabled")
        elif n:
            self.btn.config(text=f"Instalar {n} driver(s)", state="normal", command=self.instalar)
        else:
            self.btn.config(text="Nada marcado", state="disabled")

    # ------------------------------------------------------------------ instalar
    def instalar(self) -> None:
        cs = [self.itens[i] for i in self.tree.get_children() if i in self.marcados]
        if not messagebox.askokcancel(
                "Instalar drivers",
                f"Vamos criar um ponto de restauração e instalar {len(cs)} driver(s).\n\n"
                "A tela pode piscar e a internet pode cair por alguns segundos durante a instalação. "
                "Não desligue o computador.", icon="info"):
            return
        self._ocupado("Preparando a instalação...")

        def trabalho():
            try:
                self.q.put(("log", "Criando ponto de restauração..."))
                ok, msg = dp.ponto_restauracao()
                self.q.put(("log", "  " + ("criado" if ok else f"não foi possível: {msg}")))
                if not ok:
                    resp: queue.Queue = queue.Queue()
                    self.q.put(("pergunta_rp", resp))
                    if not resp.get():
                        self.q.put(("scan_ok", self.estado))
                        return
                r = dp.instalar_lista(cs, lambda n, tot, c: self.q.put(("prog", (n, tot, c["title"]))))
                self.q.put(("inst_ok", r))
            except Exception as ex:
                self.q.put(("erro", f"{type(ex).__name__}: {ex}"))
        threading.Thread(target=trabalho, daemon=True).start()

    def _fim_instalacao(self, r: dict) -> None:
        self.barra.stop()
        self.barra.pack_forget()
        ok, falha = len(r["ok"]), len(r["falha"])
        if falha == 0:
            self.msg.config(text=f"✔ Pronto! {ok} driver(s) instalado(s).", foreground=VERDE)
        else:
            self.msg.config(text=f"{ok} instalado(s), {falha} não puderam ser instalados.", foreground=LARANJA)
            self.aviso.config(text="Não instalados:\n" + "\n".join(f"• {c['title']} ({m})" for c, m in r["falha"]))
            self.aviso.pack(anchor="w", pady=(4, 0))
        self.passo.config(text="Reinicie o computador para concluir." if r["reboot"] else
                          "Clique em Verificar de novo para conferir.")
        self.btn.config(text="Verificar de novo", state="normal", command=self.verificar)
        if r["reboot"] and messagebox.askyesno("Reiniciar", "Para concluir, o computador precisa reiniciar.\n\n"
                                                            "Salve seus arquivos. Reiniciar agora?"):
            subprocess.run(["shutdown.exe", "/r", "/t", "10", "/c", "DriverPrecision: concluindo instalação de drivers"],
                           creationflags=dp.NO_WINDOW)

    def abrir_relatorio(self) -> None:
        if self.relatorio and os.path.exists(self.relatorio):
            os.startfile(self.relatorio)  # type: ignore[attr-defined]


def run_gui() -> None:
    if _elevar_se_preciso():
        return
    # saída numa pasta fixa do usuário (programa elevado pode iniciar em System32)
    dp.OUT = dp.BASE / "saida"
    dp.STATE = dp.OUT / "ultimo_scan.json"
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
