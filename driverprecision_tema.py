"""
Visual do DriverPrecision: tema escuro, menu lateral e páginas.

Só tkinter/ttk (biblioteca padrão). O ttk usa o tema "clam", que aceita todas as cores;
os ícones vêm da fonte do próprio Windows (Segoe Fluent Icons no 11, Segoe MDL2 Assets no 10).
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont, ttk

from driverprecision import recurso

# ---------------------------------------------------------------- cores
FUNDO = "#0f1117"       # janela
LATERAL = "#151821"     # menu lateral
CARTAO = "#1b1f2a"      # listas e caixas
CARTAO_2 = "#232838"    # cabeçalho de tabela / hover
BORDA = "#2a3042"
TEXTO = "#e9ecf2"
SUAVE = "#98a2b3"
APAGADO = "#5d6678"
AZUL = "#4c8dff"
AZUL_HOVER = "#6aa1ff"
AZUL_ESCURO = "#1d3566"
VERDE = "#3ecf8e"
LARANJA = "#f5a524"
VERMELHO = "#ff5c6c"
CINZA = SUAVE

FONTE = "Segoe UI"
ICONE: str | None = None
ICONES = {"drivers": "", "jogos": "", "otimiza": "", "escudo": "", "escritorio": "\uE821", "saude": "\uE95E"}


def _fontes(root: tk.Tk) -> None:
    global FONTE, ICONE
    fam = set(tkfont.families(root))
    for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "DejaVu Sans"):
        if f in fam:
            FONTE = f
            break
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in fam:
            ICONE = f
            break


def _barra_titulo_escura(root: tk.Tk) -> None:
    """Barra de título escura no Windows 10 (1809+) e 11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        v = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (novo, antigo)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0:
                break
    except Exception:
        pass


def aplicar(root: tk.Tk) -> None:
    _fontes(root)
    root.configure(bg=FUNDO)
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=FUNDO, foreground=TEXTO, font=(FONTE, 10), bordercolor=BORDA,
                 lightcolor=FUNDO, darkcolor=FUNDO, troughcolor=CARTAO, focuscolor=FUNDO,
                 selectbackground=AZUL_ESCURO, selectforeground=TEXTO, insertcolor=TEXTO)
    st.configure("TFrame", background=FUNDO)
    st.configure("Cartao.TFrame", background=CARTAO)
    st.configure("TLabel", background=FUNDO, foreground=TEXTO)
    st.configure("Titulo.TLabel", font=(FONTE, 22, "bold"), foreground=TEXTO)
    st.configure("Sub.TLabel", font=(FONTE, 10), foreground=SUAVE)
    st.configure("Msg.TLabel", font=(FONTE, 13, "bold"), foreground=TEXTO)

    # botões
    st.configure("TButton", background=CARTAO_2, foreground=TEXTO, borderwidth=0, padding=(12, 8), width=-5,
                 font=(FONTE, 10), relief="flat", lightcolor=CARTAO_2, darkcolor=CARTAO_2, bordercolor=CARTAO_2)
    st.map("TButton", background=[("disabled", CARTAO), ("pressed", BORDA), ("active", BORDA)],
           foreground=[("disabled", APAGADO)],
           lightcolor=[("active", BORDA)], darkcolor=[("active", BORDA)], bordercolor=[("active", BORDA)])
    st.configure("Rep.TButton", padding=(6, 7))
    st.configure("Grande.TButton", background=AZUL, foreground="#ffffff", font=(FONTE, 11, "bold"), padding=(18, 11),
                 lightcolor=AZUL, darkcolor=AZUL, bordercolor=AZUL)
    st.map("Grande.TButton", background=[("disabled", CARTAO_2), ("pressed", AZUL), ("active", AZUL_HOVER)],
           foreground=[("disabled", APAGADO)],
           lightcolor=[("disabled", CARTAO_2), ("active", AZUL_HOVER)], darkcolor=[("disabled", CARTAO_2), ("active", AZUL_HOVER)],
           bordercolor=[("disabled", CARTAO_2), ("active", AZUL_HOVER)])

    # listas
    st.configure("Treeview", background=CARTAO, fieldbackground=CARTAO, foreground=TEXTO, rowheight=34,
                 font=(FONTE, 10), borderwidth=0, relief="flat", lightcolor=CARTAO, darkcolor=CARTAO, bordercolor=CARTAO)
    st.map("Treeview", background=[("selected", AZUL_ESCURO)], foreground=[("selected", TEXTO)])
    st.configure("Treeview.Heading", background=CARTAO_2, foreground=SUAVE, font=(FONTE, 9, "bold"), relief="flat",
                 borderwidth=0, padding=(10, 8), lightcolor=CARTAO_2, darkcolor=CARTAO_2, bordercolor=CARTAO_2)
    st.map("Treeview.Heading", background=[("active", BORDA)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # sem moldura

    st.configure("Vertical.TScrollbar", background=CARTAO_2, troughcolor=CARTAO, borderwidth=0, arrowsize=0,
                 lightcolor=CARTAO_2, darkcolor=CARTAO_2, bordercolor=CARTAO, gripcount=0)
    st.map("Vertical.TScrollbar", background=[("active", BORDA)])
    st.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])

    st.configure("TProgressbar", background=AZUL, troughcolor=CARTAO, borderwidth=0, thickness=6,
                 lightcolor=AZUL, darkcolor=AZUL, bordercolor=CARTAO)
    _barra_titulo_escura(root)
    try:  # ícone da janela e da barra de tarefas
        if sys.platform == "win32":
            root.iconbitmap(default=str(recurso("icone.ico")))
        else:
            root._icone = tk.PhotoImage(file=str(recurso("logo_66.png")))
            root.iconphoto(True, root._icone)
    except Exception:
        pass


def quebra_automatica(frame, *rotulos) -> None:
    """Os textos quebram de linha na largura real da janela (não cortam em tela estreita)."""
    def ajusta(ev):
        for r in rotulos:
            r.configure(wraplength=max(280, ev.width - 96))
    frame.bind("<Configure>", ajusta, add="+")


def texto_log(parent, **kw) -> tk.Text:
    """Caixa de detalhes técnicos, no tom do tema."""
    return tk.Text(parent, font=("Consolas", 9), wrap="word", state="disabled", bg=CARTAO, fg=SUAVE,
                   insertbackground=TEXTO, relief="flat", bd=0, highlightthickness=0, padx=12, pady=10, **kw)


def lista(parent, **kw) -> tuple[tk.Frame, ttk.Treeview]:
    """Treeview dentro de um cartão com borda arredondada visual (moldura de 1px) e barra de rolagem fina."""
    moldura = tk.Frame(parent, bg=BORDA, padx=1, pady=1)
    dentro = tk.Frame(moldura, bg=CARTAO)
    dentro.pack(fill="both", expand=True)
    tree = ttk.Treeview(dentro, **kw)
    sb = ttk.Scrollbar(dentro, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
    return moldura, tree


# ---------------------------------------------------------------- janela com menu lateral

class Janela:
    """Menu lateral fixo à esquerda e uma página por item; só a página escolhida aparece."""

    def __init__(self, root: tk.Tk, versao: str, admin: bool) -> None:
        self.root = root
        self.lado = tk.Frame(root, bg=LATERAL, width=232)
        self.lado.pack(side="left", fill="y")
        self.lado.pack_propagate(False)
        tk.Frame(root, bg=BORDA, width=1).pack(side="left", fill="y")
        self.area = tk.Frame(root, bg=FUNDO)
        self.area.pack(side="left", fill="both", expand=True)

        marca = tk.Frame(self.lado, bg=LATERAL)
        marca.pack(fill="x", padx=20, pady=(24, 28))
        try:  # logo do app; tamanho conforme a escala da tela (100%, 150%, 200%)
            esc = root.winfo_fpixels("1i") / 96
            arq = recurso(f"logo_{88 if esc >= 1.75 else 66 if esc >= 1.25 else 44}.png")
            self._logo = tk.PhotoImage(file=str(arq))  # guardado no objeto: o Tk não segura a imagem sozinho
            logo = tk.Label(marca, image=self._logo, bg=LATERAL, bd=0)
        except Exception:
            logo = tk.Label(marca, text=ICONES["escudo"] if ICONE else "DP", bg=AZUL, fg="#ffffff", width=3,
                            font=(ICONE, 15) if ICONE else (FONTE, 11, "bold"), pady=6)
        logo.pack(side="left")
        txt = tk.Frame(marca, bg=LATERAL)
        txt.pack(side="left", padx=(12, 0))
        tk.Label(txt, text="DriverPrecision", bg=LATERAL, fg=TEXTO, font=(FONTE, 13, "bold")).pack(anchor="w")
        tk.Label(txt, text="Seu PC em dia", bg=LATERAL, fg=APAGADO, font=(FONTE, 8)).pack(anchor="w")

        rodape = tk.Frame(self.lado, bg=LATERAL)
        rodape.pack(side="bottom", fill="x", padx=20, pady=18)
        cor, txt_adm = (VERDE, "Administrador") if admin else (LARANJA, "Sem administrador")
        linha = tk.Frame(rodape, bg=LATERAL)
        linha.pack(anchor="w")
        tk.Label(linha, text="●", bg=LATERAL, fg=cor, font=(FONTE, 9)).pack(side="left")
        tk.Label(linha, text=" " + txt_adm, bg=LATERAL, fg=SUAVE, font=(FONTE, 9)).pack(side="left")
        tk.Label(rodape, text=f"Versão {versao}", bg=LATERAL, fg=APAGADO, font=(FONTE, 8)).pack(anchor="w", pady=(4, 0))

        self.itens: dict[str, dict] = {}
        self.paginas: dict[str, tk.Frame] = {}
        self.atual: str | None = None

    def pagina(self, chave: str, titulo: str, descricao: str) -> ttk.Frame:
        item = tk.Frame(self.lado, bg=LATERAL, cursor="hand2")
        item.pack(fill="x", padx=12, pady=3)
        barra = tk.Frame(item, bg=LATERAL, width=4)
        barra.pack(side="left", fill="y")
        corpo = tk.Frame(item, bg=LATERAL, padx=12, pady=10)
        corpo.pack(side="left", fill="both", expand=True)
        ic = tk.Label(corpo, text=ICONES.get(chave, "•") if ICONE else "•", bg=LATERAL, fg=SUAVE,
                      font=(ICONE, 16) if ICONE else (FONTE, 14), width=2)
        ic.pack(side="left")
        tx = tk.Frame(corpo, bg=LATERAL)
        tx.pack(side="left", padx=(10, 0))
        t1 = tk.Label(tx, text=titulo, bg=LATERAL, fg=SUAVE, font=(FONTE, 11, "bold"))
        t1.pack(anchor="w")
        t2 = tk.Label(tx, text=descricao, bg=LATERAL, fg=APAGADO, font=(FONTE, 8))
        t2.pack(anchor="w")
        widgets = [item, corpo, ic, tx, t1, t2]
        self.itens[chave] = {"w": widgets, "barra": barra, "ic": ic, "t1": t1}
        for w in widgets:
            w.bind("<Button-1>", lambda _e, c=chave: self.mostrar(c))
            w.bind("<Enter>", lambda _e, c=chave: self._pinta(c, hover=True))
            w.bind("<Leave>", lambda _e, c=chave: self._pinta(c))
        pg = ttk.Frame(self.area, padding=(12, 8, 12, 4))
        self.paginas[chave] = pg
        return pg

    def _pinta(self, chave: str, hover: bool = False) -> None:
        i = self.itens[chave]
        ativo = chave == self.atual
        bg = CARTAO_2 if ativo else (CARTAO if hover else LATERAL)
        for w in i["w"]:
            w.configure(bg=bg)
        i["barra"].configure(bg=AZUL if ativo else bg)
        i["ic"].configure(fg=AZUL if ativo else (TEXTO if hover else SUAVE))
        i["t1"].configure(fg=TEXTO if ativo or hover else SUAVE)

    def mostrar(self, chave: str) -> None:
        if self.atual:
            self.paginas[self.atual].pack_forget()
        self.atual = chave
        self.paginas[chave].pack(fill="both", expand=True)
        for c in self.itens:
            self._pinta(c)
