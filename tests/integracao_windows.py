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
        return {"pc": [ot.REG.get(h, p, n) for h, p, n in ot._pc_regs(sub, st)]}
    if t == "bcd":
        return {"bcd": [ot._bcd_get("disabledynamictick"), ot._bcd_get("useplatformclock")]}
    if t == "hiber":
        return {"hiber": ot.REG.get("HKLM", ot.PWR, "HibernateEnabled")[2]}
    return {"reg": [ot.REG.get(h, p, n) for h, p, n, _, _ in ot.regs_do_ajuste(a)]}


def t_otimiza() -> None:
    titulo("OTIMIZAÇÃO: aplicar -> conferir -> desfazer -> conferir que voltou ao original")
    import driverprecision_otimiza as ot
    ot.BACKUP = Path(tempfile.mkdtemp()) / "bk.json"
    print("  plano ativo:", ot.plano_ativo(), "| BitLocker:", ot.bitlocker_ativo())
    for linha in ot.listar():
        print(f"    estado inicial  {linha['id']:<14} {linha['estado']}")
    # ambientes onde o ajuste legitimamente não se aplica (VM sem GPU PCI, sem Wi-Fi...)
    pode_nao_aplicar = {"msi_gpu", "wifi_power", "pcie_aspm", "usb_suspend", "core_parking", "timer", "hibernacao", "nagle"}
    for a in ot.AJUSTES:
        aid = a["id"]
        try:
            antes = _foto(ot, a)
            est0 = ot.estado(a)
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
            if depois != antes:
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
    dif = [a["id"] for a in ot.AJUSTES if _foto(ot, a) != antes[a["id"]]]
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
    from driverprecision_abas import AbaJogos, AbaOtimizacao
    saida = Path(os.environ.get("PRINTS", tempfile.gettempdir()))
    saida.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.title("DriverPrecision teste")
    root.geometry("1180x740+20+20")
    tema.aplicar(root)
    fam = set(tkfont.families(root))
    print("  fonte de texto:", tema.FONTE, "| fonte de ícones:", tema.ICONE)
    (ok if tema.ICONE else falha)("fonte de ícones do Windows encontrada" if tema.ICONE else "sem Segoe Fluent Icons/MDL2")
    (ok if tema.FONTE in fam else falha)(f"fonte {tema.FONTE} existe")
    jan = tema.Janela(root, dp.VERSION, dp.is_admin())
    p1 = jan.pagina("drivers", "Drivers", "Atualizar pelo fabricante")
    p2 = jan.pagina("jogos", "Jogos", "DirectX, Visual C++ e cia.")
    p3 = jan.pagina("otimiza", "Otimização", "ajustes para jogar")
    g.App(root, p1); aj = AbaJogos(root, p2); ao = AbaOtimizacao(root, p3)
    jan.mostrar("drivers")
    aj.verificar()
    fim = time.time() + 60
    while time.time() < fim and not (ao.ajustes and aj.itens):
        root.update(); time.sleep(0.05)
    (ok if len(ao.ajustes) == 30 else falha)(f"tela Otimização carregou {len(ao.ajustes)} ajustes com o estado real")
    (ok if aj.itens else falha)(f"tela Jogos carregou {len(aj.itens)} componentes")
    try:
        from PIL import ImageGrab
    except ImportError:
        ImageGrab = None
    for chave in ("drivers", "jogos", "otimiza"):
        jan.mostrar(chave)
        for _ in range(20):
            root.update(); time.sleep(0.05)
        root.lift(); root.attributes("-topmost", True); root.update()
        if ImageGrab:
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(saida / f"tela_{chave}.png")
    ao.recomendados()
    root.update()
    ok(f"'Marcar recomendados' marcou {len(ao.marcados)} ajustes")
    root.destroy()
    ok("janela abriu, trocou de tela e fechou sem erro")


def main() -> None:
    if os.name != "nt" or not os.environ.get("GITHUB_ACTIONS"):
        sys.exit("Só roda no Windows descartável do GitHub Actions (este teste ALTERA o sistema).")
    print("admin:", dp.is_admin(), "| python", sys.version.split()[0], "|", os.environ.get("RUNNER_OS"), flush=True)
    quais = sys.argv[1:] or ["gui", "otimiza", "links", "jogos", "oem", "drivers"]
    for q in quais:
        try:
            {"otimiza": t_otimiza, "jogos": t_jogos, "links": t_links, "drivers": t_drivers, "oem": t_oem, "gui": t_gui}[q]()
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
