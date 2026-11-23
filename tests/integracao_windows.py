"""
Teste de integração em Windows DE VERDADE (máquina descartável do GitHub Actions, como administrador).

Faz o que os testes unitários não podem: aplica e desfaz cada ajuste no registro real, instala os
componentes de jogos, roda a verificação de drivers, consulta os catálogos Lenovo/Dell/HP, baixa e
extrai um pacote real e abre a janela. NÃO rode no seu PC: ele altera o sistema.

Uso: python -X utf8 tests/integracao_windows.py [otimiza] [jogos] [drivers] [oem] [gui]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision as dp  # noqa: E402

FALHAS: list[str] = []
AVISOS: list[str] = []


def ok(m): print("  [ OK ] " + m, flush=True)
def aviso(m): AVISOS.append(m); print("  [AVISO] " + m, flush=True)
def falha(m): FALHAS.append(m); print("  [FALHA] " + m, flush=True)
def titulo(m): print(f"\n{'=' * 78}\n{m}\n{'=' * 78}", flush=True)


# ------------------------------------------------------------------ otimização
def _foto(ot, a) -> dict:
    """Tudo o que o ajuste pode alterar, lido direto do sistema."""
    t = a.get("tipo")
    if t == "plano":
        return {"plano": ot.plano_ativo()}
    if t == "powercfg":
        sub, st, _, _ = a["pc"]
        return {"pc": ot._pc_lidos(sub, st)}
    if t == "bcd":
        return {"bcd": [ot._bcd_get("disabledynamictick"), ot._bcd_get("useplatformclock")]}
    if t == "hiber":
        return {"hiber": ot.REG.get("HKLM", ot.PWR, "HibernateEnabled")[2]}
    if t == "todos_planos":
        return {"planos": {(g, st): ot._pc_lidos(sub, st, g) for g in ot.planos() for sub, st, _, _ in a["pcs"]}}
    if t == "ps":
        return {"ps": ot._ps_ler(a), "guardar": [ot.REG.get(h, p, n) for h, p, n in a.get("guardar", [])]}
    return {"reg": [ot.REG.get(h, p, n) for h, p, n, _, _ in ot.regs_do_ajuste(a)]}


def t_otimiza() -> None:
    titulo("OTIMIZAÇÃO: aplicar -> conferir -> desfazer -> conferir que voltou ao original")
    import driverprecision_otimiza as ot
    ot.BACKUP = Path(tempfile.mkdtemp()) / "bk.json"
    ot._BATERIA = True  # a máquina de teste não tem bateria: força o ajuste da tampa para testá-lo de verdade
    print("  plano ativo:", ot.plano_ativo(), "| BitLocker:", ot.bitlocker_ativo(), "| ambiente:", ot.ambiente())
    print("  Chrome:", ot.tem_chrome(), "| Firefox:", ot.tem_firefox(), "| Office:", ot.tem_office(), "| LibreOffice:", ot.tem_libreoffice())
    # o plano Desempenho Máximo tem de herdar a ação da tampa e o tempo de tela do plano anterior
    ot._cmd(["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION", "0"])
    ot._cmd(["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_VIDEO", "VIDEOIDLE", "1234"])
    ot._cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
    p0 = ot.plano_ativo()
    ot.aplicar("plano_max")
    p1 = ot.plano_ativo()
    tampa, tela = ot._pc_lidos("SUB_BUTTONS", "LIDACTION", p1), ot._pc_lidos("SUB_VIDEO", "VIDEOIDLE", p1)
    print(f"  plano {p0} -> {p1} | tampa {tampa} | tela {tela}")
    (ok if (p1 == p0 or (tampa[0] in (0, None) and tela[0] == 1234)) else falha)(
        f"plano novo herdou a tampa e o tempo de tela (tampa={tampa}, tela={tela})")
    ot.desfazer("plano_max")
    (ok if ot.plano_ativo() == p0 else falha)("desfazer voltou ao plano anterior")
    for linha in ot.listar():
        print(f"    estado inicial  {linha['id']:<14} {linha['estado']}")
    # ambientes onde o ajuste legitimamente não se aplica (VM sem GPU PCI, sem Wi-Fi...)
    # memcomp: no Windows SERVER a compressão de memória às vezes não liga na hora (o app é para Windows 10/11)
    pode_nao_aplicar = {"memcomp", "msi_gpu", "wifi_power", "pcie_aspm", "usb_suspend", "core_parking", "timer", "hibernacao", "nagle"}
    for a in ot.AJUSTES:
        aid = a["id"]
        try:
            antes = _foto(ot, a)
            est0 = ot.estado(a)
            if est0 == "N/A" or ot.bloqueado(a):
                aviso(f"{aid}: não se aplica a esta máquina ({ot.bloqueado(a) or 'recurso ausente'})")
                continue
            try:
                msg = ot.aplicar(aid)
            except RuntimeError as ex:
                (aviso if aid in pode_nao_aplicar else falha)(f"{aid}: não aplicou neste ambiente: {ex}")
                if aid in ot.aplicados():
                    falha(f"{aid}: deixou backup mesmo falhando")
                continue
            est1 = ot.estado(a)
            if est1 != "ATIVO":
                (aviso if aid in pode_nao_aplicar else falha)(f"{aid}: aplicou ({msg}) mas o estado lido é {est1}")
            ot.aplicar(aid)  # segunda vez não pode estragar o backup
            ot.desfazer(aid)
            depois = _foto(ot, a)
            if a.get("nao_desfaz") and depois != antes:
                ok(f"{aid:<14} {est0} -> {est1} -> mantido de propósito ({a['nao_desfaz'][:60]}...)")
            elif aid == "hibernacao" and antes["hiber"] is None:
                aviso(f"hibernação: esta máquina não tem hibernação configurada (antes={antes}, depois={depois})")
            elif depois != antes:
                falha(f"{aid}: desfazer NÃO restaurou. antes={antes} depois={depois}")
            elif aid in ot.aplicados():
                falha(f"{aid}: continuou no backup depois de desfazer")
            else:
                ok(f"{aid:<14} {est0} -> {est1} -> restaurado")
        except Exception:
            falha(f"{aid}: exceção\n{traceback.format_exc()}")
    # tudo de uma vez, na ordem da tela, e "desfazer tudo"
    antes = {a["id"]: _foto(ot, a) for a in ot.AJUSTES}
    aplic = []
    for a in ot.AJUSTES:
        try:
            ot.aplicar(a["id"]); aplic.append(a["id"])
        except RuntimeError:
            pass
    for aid in ot.aplicados():
        ot.desfazer(aid)
    dif = [a["id"] for a in ot.AJUSTES if _foto(ot, a) != antes[a["id"]] and not a.get("nao_desfaz")
           and not (a["id"] == "hibernacao" and antes["hibernacao"]["hiber"] is None)]
    (falha if dif else ok)(f"aplicar {len(aplic)} juntos + desfazer tudo: " + (f"NÃO restaurou {dif}" if dif else "sistema idêntico ao original"))


# ------------------------------------------------------------------ jogos
def t_jogos() -> None:
    titulo("JOGOS: verificar -> instalar tudo o que falta (links oficiais) -> verificar de novo")
    import driverprecision_jogos as jg
    antes = jg.verificar()
    for i in antes:
        print(f"    antes   {i['id']:<12} {i['status']:<14} {i['detalhe']}")
    ids = [i["id"] for i in antes if i["status"] in ("FALTA", "DESATUALIZADO") and i["instalavel"]]
    print("  instalando:", ids)
    r = jg.instalar(ids)
    for nome, msg in r["falha"]:
        falha(f"instalação de {nome}: {msg}")
    depois = {i["id"]: i for i in jg.verificar()}
    for cid in ids:
        i = depois[cid]
        if i["status"] == "OK":
            ok(f"{cid}: instalado e detectado ({i['detalhe']})")
        elif cid in ("net35", "directplay") and r["reboot"]:
            aviso(f"{cid}: instalado, mas só aparece depois de reiniciar")
        else:
            falha(f"{cid}: depois de instalar continua {i['status']} ({i['detalhe']})")
    for i in depois.values():
        if i["status"] == "INFO" and i["id"] != "vulkan":
            falha(f"{i['id']}: verificação quebrou: {i['detalhe']}")


def t_links() -> None:
    titulo("JOGOS: todos os links oficiais respondem e o arquivo tem assinatura do fabricante")
    import driverprecision_jogos as jg
    for c in jg.COMPONENTES:
        if not c.get("url"):
            continue
        try:
            arq = jg._baixar(c)
            alvo = arq
            if c.get("tipo") == "openal":
                import zipfile
                with zipfile.ZipFile(arq) as z:
                    z.extractall(arq.parent)
                alvo = next(arq.parent.rglob("oalinst.exe"))
            st, sub = dp.assinatura(alvo)
            if st == "Valid" and c["signer"].lower() in sub.lower():
                ok(f"{c['id']:<12} {arq.stat().st_size / 1e6:6.1f} MB  {sub.split(',')[0]}")
            else:
                falha(f"{c['id']}: assinatura {st} / {sub}")
        except Exception as ex:
            falha(f"{c['id']}: {type(ex).__name__}: {ex}")


# ------------------------------------------------------------------ drivers
def t_drivers() -> None:
    titulo("DRIVERS: verificação completa nesta máquina (inventário, Windows Update, Catálogo, relatório)")
    dp.OUT = Path(tempfile.mkdtemp()) / "saida com espaço"
    dp.STATE = dp.OUT / "ultimo_scan.json"
    e = dp.scan(argparse.Namespace(sem_oem=False, sem_wu=False, sem_catalogo=False, nao_abrir=True))
    (ok if len(e["devices"]) >= 5 else falha)(f"inventário: {len(e['devices'])} dispositivos")
    for k, v in e["fontes"].items():
        (falha if str(v).startswith("falhou") else ok)(f"fonte {k}: {v}")
    rel = Path(e["relatorio"])
    (ok if rel.exists() and rel.stat().st_size > 5000 else falha)(f"relatório HTML: {rel.stat().st_size} bytes")
    # leitura da versão instalada (usada para conferir a troca de driver), ANTES de instalar qualquer coisa
    com_ver = next((d for d in e["devices"] if d.get("ver") and d.get("id")), None)
    if com_ver:
        lida = dp.versao_instalada(com_ver["id"])
        (ok if dp.vcmp(lida, com_ver["ver"]) == 0 else falha)(f"leitura da versão instalada: {com_ver['name'][:40]} = {lida} (inventário: {com_ver['ver']})")
    rec = dp.recomendados(e)
    ok(f"recomendados para instalar: {len(rec)}")
    for d, b in rec[:10]:
        print(f"      {d['status']:<10} {d['name'][:50]:<50} {d.get('ver')} -> {b.get('version')} [{b['cid']}]")
    # instalar de verdade o que foi recomendado (máquina descartável)
    if rec:
        r = dp.instalar_lista([b for _, b in rec][:3])
        for c, msg in r["ok"]:
            ok(f"instalou {c['cid']}: {msg}")
        for c, msg in r["falha"]:
            aviso(f"não instalou {c['cid']}: {msg}")
    rp, msg = dp.ponto_restauracao()
    (ok if rp else aviso)(f"ponto de restauração: {'criado' if rp else msg[:150]}")


def _dev(hwid: str) -> dict:
    return {"id": hwid + "\\1", "name": hwid, "hwids": [hwid], "compat": [], "mids": [hwid], "bus": hwid.split("\\")[0],
            "cls": "SYSTEM", "inbox": False, "sem_driver": False, "ver": "1.0.0.0", "cands": []}


def t_oem() -> None:
    titulo("CATÁLOGOS DOS FABRICANTES: Lenovo, Dell e HP respondem e o formato continua o mesmo")
    base = {"build": 26100, "arch": "AMD64", "display": "24H2", "bios": "N2IET99W (1.77 )"}
    # --- Lenovo: ThinkPad T490 (20N2); os IDs dos dispositivos saem do próprio catálogo
    sistema: list[dict] = []
    devs = [_dev(r"PCI\VEN_8086&DEV_9DF0&SUBSYS_00348086&REV_30"), _dev(r"PCI\VEN_8086&DEV_3EA0&SUBSYS_229217AA&REV_02"),
            _dev(r"HDAUDIO\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2292&REV_1000"), _dev(r"ACPI\VEN_INT&DEV_34BB"),
            _dev(r"PCI\VEN_8086&DEV_15BE&SUBSYS_229217AA&REV_30")]
    r = dp.fonte_lenovo(dict(base, mfr="LENOVO", model="20N2CTO1WW"), devs, sistema)
    n = sum(len(d["cands"]) for d in devs)
    (ok if r.startswith("ok") and n else falha)(f"Lenovo 20N2: {r} | {n} candidatos nos 5 dispositivos de teste, {len(sistema)} de sistema")
    cands = [c for d in devs for c in d["cands"] if c.get("url") and c.get("sha256") and c["kind"] == "driver"]
    if cands:
        c = min(cands, key=lambda c: c["size"] or 1 << 40)
        dp.OUT = Path(tempfile.mkdtemp()) / "pasta com espaço"
        try:
            arq = dp.baixar_um(c)
            ok(f"Lenovo: baixou {arq.name} ({arq.stat().st_size / 1e6:.1f} MB), SHA-256 e assinatura conferem")
            if c.get("extract"):
                pp = dp.caminho_curto(arq.parent)
                print("      caminho:", arq.parent, "-> curto:", pp)
                rc = dp._run(c["extract"].replace("%PACKAGEPATH%", pp), arq.parent, 600)
                extras = [x for x in arq.parent.rglob("*") if x.is_file() and x != arq]
                (ok if extras else falha)(f"Lenovo: extração em pasta com espaço (código {rc}): {len(extras)} arquivos; "
                                          f"comando de instalação: {c.get('install')}")
        except Exception as ex:
            falha(f"Lenovo: download/validação: {ex}")
    # --- Dell: pega do próprio catálogo um modelo com driver para Windows 11
    try:
        root = ET.fromstring(dp.cab_xml("https://downloads.dell.com/catalog/CatalogPC.cab", "dell_CatalogPC.cab", 24))
        alvo = None
        for sc in root.iter("SoftwareComponent"):
            if sc.find("ComponentType") is not None and sc.find("ComponentType").get("value") == "DRVR" \
                    and any(o.get("osCode") in dp.DELL_OS[11] for o in sc.iter("OperatingSystem")):
                pci = next(sc.iter("PCIInfo"), None)
                mod = next(sc.iter("Model"), None)
                if pci is not None and mod is not None and pci.get("subVendorID"):
                    alvo = (mod.get("systemID").upper(), pci)
                    break
        sku, pci = alvo
        hw = f"PCI\\VEN_{pci.get('vendorID').upper()}&DEV_{pci.get('deviceID').upper()}&SUBSYS_{pci.get('subDeviceID').upper()}{pci.get('subVendorID').upper()}"
        devs, sistema = [_dev(hw + "&REV_01"), _dev(hw)], []
        r = dp.fonte_dell(dict(base, mfr="Dell Inc.", sku=sku, bios="1.0.0"), devs, sistema)
        n = sum(len(d["cands"]) for d in devs)
        (ok if r.startswith("ok") and n else falha)(f"Dell SKU {sku}: {r} | {n} candidatos, {len(sistema)} de sistema")
        c = min((c for d in devs for c in d["cands"]), key=lambda c: c["size"] or 1 << 40)
        if c["size"] < 300e6:
            arq = dp.baixar_um(c)
            ok(f"Dell: baixou {arq.name} ({arq.stat().st_size / 1e6:.1f} MB), MD5 e assinatura conferem")
    except Exception as ex:
        falha(f"Dell: {type(ex).__name__}: {ex}")
    # --- HP: pega da lista uma plataforma com Windows 11
    try:
        root = ET.fromstring(dp.cab_xml("https://hpia.hpcloud.hp.com/ref/platformList.cab", "hp_platformList.cab", 72))
        feito = tent = 0
        for p in root.iter("Platform"):
            if not any(o.findtext("IsWindows11") == "true" and o.findtext("OSReleaseIdDisplay") in ("24H2", "23H2") for o in p.findall("OS")):
                continue
            plat = (p.findtext("SystemID") or "").split(",")[0].strip().upper()
            devs, sistema = [_dev(r"PCI\VEN_8086&DEV_9DF0")], []
            r = dp.fonte_hp(dict(base, mfr="HP", bbproduct=plat, bios="T70 Ver. 01.00.00"), devs, sistema)
            if r.startswith("ok"):
                ok(f"HP plataforma {plat} ({p.findtext('ProductName')}): {r} | {len(sistema)} BIOS")
                feito += 1
                break
            print("      (tentando outra plataforma)", plat, r)
            tent += 1
            if tent > 5:
                break
        if feito < 1:
            falha("HP: nenhuma plataforma devolveu referência")
    except Exception as ex:
        falha(f"HP: {type(ex).__name__}: {ex}")


# ------------------------------------------------------------------ interface
def t_gui() -> None:
    titulo("INTERFACE: abre a janela real, troca de tela, confere fontes/ícones e tira print")
    import tkinter as tk
    from tkinter import font as tkfont
    import driverprecision_tema as tema
    import driverprecision_gui as g
    from driverprecision_abas import AbaJogos, AbaOtimizacao, AbaSaude
    saida = Path(os.environ.get("PRINTS", tempfile.gettempdir()))
    saida.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.title("DriverPrecision teste")
    root.geometry(f"{min(1180, root.winfo_screenwidth())}x{min(740, root.winfo_screenheight() - 60)}+0+0")
    tema.aplicar(root)
    fam = set(tkfont.families(root))
    print("  fonte de texto:", tema.FONTE, "| fonte de ícones:", tema.ICONE)
    (ok if tema.ICONE else falha)("fonte de ícones do Windows encontrada" if tema.ICONE else "sem Segoe Fluent Icons/MDL2")
    (ok if tema.FONTE in fam else falha)(f"fonte {tema.FONTE} existe")
    jan = tema.Janela(root, dp.VERSION, dp.is_admin())
    p1 = jan.pagina("drivers", "Drivers", "Atualizar pelo fabricante")
    p2 = jan.pagina("jogos", "Jogos", "DirectX, Visual C++ e cia.")
    p3 = jan.pagina("otimiza", "Otimização", "ajustes para jogar")
    p4 = jan.pagina("escritorio", "Escritório", "Abas, planilhas e rede")
    p5 = jan.pagina("saude", "Saúde do PC", "Segurança e reparos")
    g.App(root, p1); aj = AbaJogos(root, p2); ao = AbaOtimizacao(root, p3, "jogos")
    ae = AbaOtimizacao(root, p4, "escritorio"); asd = AbaSaude(root, p5)
    jan.mostrar("drivers")
    aj.verificar()
    fim = time.time() + 180
    while time.time() < fim and not (ao.ajustes and aj.itens and ae.ajustes and asd.itens):
        root.update(); time.sleep(0.05)
    import driverprecision_otimiza as ot
    (ok if len(ao.ajustes) == len(ot.do_perfil("jogos")) else falha)(f"tela Otimização carregou {len(ao.ajustes)} ajustes com o estado real")
    (ok if len(ae.ajustes) == len(ot.do_perfil("escritorio")) else falha)(f"tela Escritório carregou {len(ae.ajustes)} ajustes com o estado real")
    (ok if aj.itens else falha)(f"tela Jogos carregou {len(aj.itens)} componentes")
    (ok if len(asd.itens) >= 12 else falha)(f"tela Saúde do PC carregou {len(asd.itens)} itens")
    try:
        from PIL import ImageGrab
    except ImportError:
        ImageGrab = None
    for chave in ("drivers", "jogos", "otimiza", "escritorio", "saude"):
        jan.mostrar(chave)
        for _ in range(20):
            root.update(); time.sleep(0.05)
        root.lift(); root.attributes("-topmost", True); root.update()
        if ImageGrab:
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(saida / f"tela_{chave}.png")
    for aba, nome in ((ao, "Otimização"), (ae, "Escritório")):
        cx = {i for i in aba.ajustes if aba.tree.set(i, "sel") != ""}
        aba.marcar_todos(); root.update()
        (ok if aba.marcados == cx else falha)(f"{nome}: 'Marcar todos' marcou {len(aba.marcados)} de {len(cx)} com caixinha")
        aba.desmarcar_todos(); root.update()
        (ok if not aba.marcados else falha)(f"{nome}: 'Desmarcar todos' limpou a seleção")
    cxj = {i for i in aj.tree.get_children() if aj.tree.set(i, "sel") != ""}
    aj.marcar_todos(); aj.desmarcar_todos(); root.update()
    (ok if not aj.marcados else falha)(f"Jogos: marcar/desmarcar todos ({len(cxj)} com caixinha)")
    ao.recomendados()
    root.update()
    ok(f"'Marcar recomendados' marcou {len(ao.marcados)} ajustes")
    root.destroy()
    ok("janela abriu, trocou de tela e fechou sem erro")


# ------------------------------------------------------------------ peças: fabricante certo e só estável
PECAS = [  # Hardware IDs reais (o 1º é o mais específico); várias marcas e tipos de peça
    ("Wi-Fi Intel AX210 (placa avulsa)", "NET", ["PCI\\VEN_8086&DEV_2725&SUBSYS_00248086", "PCI\\VEN_8086&DEV_2725"]),
    ("Wi-Fi Intel AX201 (CNVi)", "NET", ["PCI\\VEN_8086&DEV_A0F0&SUBSYS_02448086", "PCI\\VEN_8086&DEV_A0F0"]),
    ("Wi-Fi Intel 9560 (ThinkPad T490)", "NET", ["PCI\\VEN_8086&DEV_9DF0&SUBSYS_00348086", "PCI\\VEN_8086&DEV_9DF0"]),
    ("Wi-Fi Realtek RTL8822CE", "NET", ["PCI\\VEN_10EC&DEV_C822&SUBSYS_C82210EC", "PCI\\VEN_10EC&DEV_C822"]),
    ("Rede Realtek RTL8111/8168 (ASUS)", "NET", ["PCI\\VEN_10EC&DEV_8168&SUBSYS_86771043", "PCI\\VEN_10EC&DEV_8168"]),
    ("Vídeo Intel UHD 620 (ThinkPad T490)", "DISPLAY", ["PCI\\VEN_8086&DEV_3EA0&SUBSYS_229217AA", "PCI\\VEN_8086&DEV_3EA0"]),
    ("Vídeo AMD Radeon (Ryzen 5000U, ASUS)", "DISPLAY", ["PCI\\VEN_1002&DEV_164C&SUBSYS_1E121043", "PCI\\VEN_1002&DEV_164C"]),
    ("Vídeo NVIDIA GTX 1650 Mobile", "DISPLAY", ["PCI\\VEN_10DE&DEV_1F99&SUBSYS_3A4317AA", "PCI\\VEN_10DE&DEV_1F99"]),
    ("Áudio Realtek ALC257 (ThinkPad T490)", "MEDIA", ["HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2292", "HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257"]),
    ("Bluetooth Intel (AX210)", "BLUETOOTH", ["USB\\VID_8087&PID_0032&REV_0000", "USB\\VID_8087&PID_0032"]),
    ("Bluetooth Realtek", "BLUETOOTH", ["USB\\VID_0BDA&PID_B00C&REV_0000", "USB\\VID_0BDA&PID_B00C"]),
    ("Serial IO Intel (ThinkPad T490)", "SYSTEM", ["PCI\\VEN_8086&DEV_9DE8&SUBSYS_229217AA", "PCI\\VEN_8086&DEV_9DE8"]),
    ("Controle Xbox (USB)", "XNACOMPOSITE", ["USB\\VID_045E&PID_02EA&REV_0408", "USB\\VID_045E&PID_02EA"]),
    ("Impressora HP (USB)", "PRINTER", ["USB\\VID_03F0&PID_2B2A&MI_00", "USB\\VID_03F0&PID_2B2A"]),
]


def t_pecas() -> None:
    titulo("PEÇAS: Catálogo da Microsoft ao vivo; o escolhido tem de ser do fabricante da peça, exato e estável")
    import driverprecision as dp
    devs = []
    for nome, cls, hw in PECAS:
        devs.append({"id": hw[0] + "\\1", "name": nome, "hwids": [h.upper() for h in hw], "compat": [], "mids": [h.upper() for h in hw],
                     "bus": hw[0].split("\\")[0], "cls": cls, "inbox": True, "sem_driver": True, "ver": "", "err": 28,
                     "cands": [], "pc_oem": "lenovo", "oem_consultado": True})
    print("  ", dp.fonte_catalogo({"build": 26100, "arch": "AMD64"}, devs))
    for d in devs:
        dp.avaliar(d)
        b = d["melhor"]
        peca = dp.fabricante_peca(d)
        provs = sorted({c.get("provider") or "?" for c in d["cands"]})
        print(f"    {d['name'][:38]:<38} peça={d['fabricante_peca'] or '?':<10} candidatos={len(d['cands'])} {provs}")
        if not b:
            print("      -> nenhum driver aceito (nenhum do fabricante da peça, exato e estável)")
            continue
        print(f"      -> {b.get('provider')} {b.get('version')} | {b.get('title', '')[:70]}")
        regra = (peca is None or re.search(peca[1], b.get("provider") or "", re.I)
                 or re.search(dp.PROVEDOR_OEM["lenovo"], b.get("provider") or "", re.I))
        (ok if regra else falha)(f"{d['name']}: driver de {b.get('provider')} " + ("(fabricante certo)" if regra else "NÃO é do fabricante da peça"))
        (ok if dp.estavel(b) else falha)(f"{d['name']}: versão estável")
        (ok if b.get("level") == "exato" else falha)(f"{d['name']}: Hardware ID exato na lista oficial do pacote")


# ------------------------------------------------------------------ NVIDIA ao vivo
GPUS = [("NVIDIA GeForce GTX 1650", True), ("NVIDIA GeForce RTX 3060 Laptop GPU", True), ("NVIDIA GeForce RTX 4060", False),
        ("NVIDIA GeForce RTX 3080", False), ("NVIDIA GeForce GTX 1660 SUPER", False)]


def t_nvidia() -> None:
    titulo("NVIDIA: site oficial ao vivo — produto certo, Game Ready WHQL estável, link oficial, assinatura da NVIDIA")
    import driverprecision as dp
    baixado = False
    for nome, notebook in GPUS:
        d = {"name": nome, "cls": "DISPLAY", "hwids": ["PCI\\VEN_10DE&DEV_0000"], "compat": [], "mids": [], "bus": "PCI",
             "ver": "31.0.15.0000", "inbox": False, "sem_driver": False, "cands": []}
        try:
            r = dp.fonte_nvidia({"build": 26100, "notebook": notebook}, [d])
        except Exception as ex:
            falha(f"{nome}: {type(ex).__name__}: {ex}")
            continue
        print(f"    {nome:<40} {'notebook' if notebook else 'desktop':<8} {r[:120]}")
        nv = [c for c in d["cands"] if c["source"] == "NV"]
        if not nv:
            falha(f"{nome}: nenhum driver encontrado no site da NVIDIA")
            continue
        c = nv[0]
        okv = bool(re.fullmatch(r"\d{3}\.\d{2}", c["nv_version"])) and int(c["nv_version"].split(".")[0]) >= 500
        (ok if okv and dp.estavel(c) else falha)(f"{nome}: {c['nv_version']} ({c['title'][:60]}) estável e recente")
        (ok if c["url"].startswith("https://") and "nvidia.com/" in c["url"] else falha)(f"{nome}: link oficial {c['url'][:90]}")
        if not baixado:
            dp.OUT = Path(tempfile.mkdtemp())
            t0 = time.time()
            try:
                arq = dp.baixar_um(c)
                ok(f"{nome}: baixou {arq.stat().st_size / 1e6:.0f} MB em {time.time() - t0:.0f} s, assinatura da NVIDIA confere")
                baixado = True
            except Exception as ex:
                falha(f"{nome}: download/assinatura: {ex}")
    # a assinatura tem de ser do fabricante certo: o mesmo arquivo, esperando outro assinante, é recusado
    if baixado:
        try:
            dp.baixar_um(dict(c, signer="Intel Corporation"))
            falha("arquivo da NVIDIA aceito como se fosse da Intel")
        except RuntimeError as ex:
            ok(f"assinante errado é recusado: {str(ex)[:80]}")


# ------------------------------------------------------------------ AMD ao vivo
def t_amd() -> None:
    titulo("AMD: site oficial ao vivo — só WHQL, lista de chips aceitos, link oficial, assinatura da AMD")
    import driverprecision as dp
    pacotes = dp.amd_pacotes()
    (ok if pacotes else falha)(f"{len(pacotes)} pacote(s) WHQL publicados pela AMD")
    for p in pacotes:
        print(f"    Adrenalin {p.get('externalbuildversion')} | interna {str(p.get('internalbuildversion'))[:30]} | "
              f"{len(p.get('skus') or [])} chips | {p.get('releasedate')} | {str(p.get('fullbuild'))[:90]}")
        (ok if dp.estavel({"title": p.get("edition"), "version": p.get("externalbuildversion")}) else falha)(
            f"{p.get('externalbuildversion')}: estável")
        (ok if str(p.get("fullbuild", "")).startswith("https://") and re.search(r"(amd|ati)\.com/", p["fullbuild"]) else falha)(
            f"{p.get('externalbuildversion')}: link oficial")
    if not pacotes:
        return
    sku = (pacotes[0].get("skus") or ["0000-00"])[0]
    dev_id, rev = sku.split("-")
    d = {"id": "", "name": f"AMD Radeon (chip {sku})", "cls": "DISPLAY", "hwids": [f"PCI\\VEN_1002&DEV_{dev_id}&SUBSYS_00000000&REV_{rev}"],
         "compat": [], "mids": [], "bus": "PCI", "ver": "32.0.0.0", "inbox": False, "sem_driver": False, "cands": []}
    print("   ", dp.fonte_amd({"build": 26100}, [d]))
    c = next((x for x in d["cands"] if x["source"] == "AMD"), None)
    (ok if c else falha)(f"chip {sku} da lista recebeu o pacote da AMD")
    if c:
        import urllib.request
        for rotulo, url in (("completo", c["url"]), ("leve (minimal setup)", next((p.get("minimalbuild") for p in pacotes
                                                                                   if p.get("minimalbuild")), ""))):
            if not url:
                continue
            try:  # diagnóstico: o que o servidor da AMD devolve para o download direto
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": dp.UA}), timeout=60) as r:
                    cab = r.read(512)
                    print(f"    {rotulo}: HTTP {r.status} | {r.headers.get('Content-Type')} | {r.headers.get('Content-Length')} bytes"
                          f" | começa com {cab[:2]!r} | {cab[:160]!r}")
            except Exception as ex:
                print(f"    {rotulo}: {type(ex).__name__}: {str(ex)[:160]}")
        (ok if c.get("manual") and str(c.get("pagina", "")).startswith("https://www.amd.com/") else falha)(
            f"AMD: só aviso + página oficial ({c.get('pagina', '')[:80]}); o programa não baixa o instalador")
        (ok if not dp.recomendados({"devices": [dict(d, status="ATUALIZAR", melhor=c)]}) else falha)(
            "AMD: fora da instalação automática")


# ------------------------------------------------------------------ sondagem dos sites dos fabricantes
SONDAS = [
    ("NVIDIA: tipos de produto", "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=1"),
    ("NVIDIA: séries de GeForce", "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=2&ParentID=1"),
    ("NVIDIA: sistemas", "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=4"),
    ("NVIDIA: busca de driver (GTX 1650 notebook, Win11, DCH, WHQL)",
     "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php?func=DriverManualLookup"
     "&psid=123&pfid=889&osID=135&languageCode=1033&beta=0&isWHQL=1&dch=1&upCRD=0&sort1=0&numberOfResults=2"),
    ("AMD: manifesto do Adrenalin", "https://drivers.amd.com/drivers/installer/json/version.json"),
    ("Intel: DSA", "https://dsadata.intel.com/"),
    ("Intel: centro de downloads (Wi-Fi)", "https://www.intel.com/content/www/us/en/download/19351/windows-10-and-windows-11-wi-fi-drivers-for-intel-wireless-adapters.html"),
    ("Realtek: downloads", "https://www.realtek.com/Download/List?cate_id=593"),
    ("AMD: detalhes do Adrenalin WHQL (Win11)", "https://www2.ati.com/drivers/installer/json/DrvDldDetails_Consumer_WHQL_Win11.json"),
    ("ASUS: sistemas do modelo M1502IA", "https://www.asus.com/support/api/product.asmx/GetPDOS?website=global&model=M1502IA&pdhashedid="),
    ("ASUS: drivers do M1502IA (Win11 64)", "https://www.asus.com/support/api/product.asmx/GetPDDrivers?website=global&model=M1502IA&osid=52&pdhashedid="),
    ("ASUS: BIOS do M1502IA", "https://www.asus.com/support/api/product.asmx/GetPDBIOS?website=global&model=M1502IA&pdhashedid="),
]


def t_sites() -> None:
    titulo("SONDAGEM: o que os sites oficiais dos fabricantes respondem (só leitura, para projetar as fontes)")
    import driverprecision as dp
    for nome, url in SONDAS:
        try:
            t = dp.http_get(url, timeout=40).decode("utf-8", "replace")
            print(f"  [{len(t):>8} bytes] {nome}\n      {url[:120]}\n      " + re.sub(r"\s+", " ", t)[:700 if "AMD" not in nome else 4000])
        except Exception as ex:
            print(f"  [   falhou] {nome}: {type(ex).__name__}: {str(ex)[:150]}")


# ------------------------------------------------------------------ saúde
def t_saude() -> None:
    titulo("SAÚDE DO PC: diagnóstico real e cada reparo executado de verdade")
    import driverprecision_saude as sd
    import driverprecision_otimiza as ot
    t0 = time.time()
    d = sd.diagnostico()
    print(f"  diagnóstico em {time.time() - t0:.0f} s; campos: {sorted(d)}")
    faltando = [k for k in ("ram_gb", "uptime_h", "c_livre_gb", "firewall", "update_dias", "uac", "discos", "spooler") if d.get(k) is None]
    (falha if faltando else ok)("diagnóstico leu tudo" + (f", menos {faltando}" if faltando else ""))
    for i in sd.avaliar(d, ot.ambiente()):
        print(f"    {i['status']:<9} {i['grupo'][:20]:<20} {i['nome'][:32]:<32} {i['detalhe'][:70]}")
    longos = bool(os.environ.get("REPAROS_LONGOS"))
    if not longos:
        aviso("chkdsk, SFC e DISM pulados: o código da Saúde do PC não mudou neste commit (já validados antes)")
    for rid in ("dns", "spooler", "temp") + (("chkdsk", "sfc", "dism") if longos else ()):
        t0 = time.time()
        try:
            okr, _, msg = sd.executar(rid)
        except Exception as ex:
            okr, msg = False, f"{type(ex).__name__}: {ex}"
        (ok if okr else falha)(f"reparo {rid:<8} {time.time() - t0:5.0f} s  {msg[:160]}")
    aviso("reparo rede_reset não executado aqui: derrubaria a rede da máquina de teste no meio do teste")


def main() -> None:
    if os.name != "nt" or not os.environ.get("GITHUB_ACTIONS"):
        sys.exit("Só roda no Windows descartável do GitHub Actions (este teste ALTERA o sistema).")
    print("admin:", dp.is_admin(), "| python", sys.version.split()[0], "|", os.environ.get("RUNNER_OS"), flush=True)
    quais = sys.argv[1:] or ["gui", "otimiza", "links", "jogos", "oem", "drivers", "pecas", "nvidia", "amd", "sites", "saude"]
    for q in quais:
        try:
            {"otimiza": t_otimiza, "jogos": t_jogos, "links": t_links, "drivers": t_drivers, "oem": t_oem, "gui": t_gui, "saude": t_saude, "pecas": t_pecas, "sites": t_sites, "nvidia": t_nvidia, "amd": t_amd}[q]()
        except Exception:
            falha(f"{q}: exceção não tratada\n{traceback.format_exc()}")
    titulo(f"RESULTADO: {len(FALHAS)} falha(s), {len(AVISOS)} aviso(s)")
    for m in AVISOS:
        print("  aviso:", m)
    for m in FALHAS:
        print("  FALHA:", m)
    sys.exit(1 if FALHAS else 0)


if __name__ == "__main__":
    main()
