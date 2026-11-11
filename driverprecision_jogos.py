"""
Componentes que os jogos precisam para abrir, independente da potência do hardware.

Cada item sabe se verificar (registro/arquivos do Windows) e se instalar a partir do link
oficial do fabricante, com assinatura digital conferida antes de executar.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.request
import winreg
import zipfile
from pathlib import Path

import driverprecision as dp

WIN = Path(os.environ.get("SystemRoot", r"C:\Windows"))
# processo 32 bits enxerga SysWOW64 em System32: Sysnative dá acesso ao System32 real
SYS64 = WIN / "Sysnative" if (WIN / "Sysnative").exists() else WIN / "System32"
SYS32 = WIN / "SysWOW64"
PF = Path(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files"))
PF86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
DL = dp.BASE / "componentes"
RC_OK = {0, 1638, 1641, 3010, 5100}  # 1638 = versão igual/mais nova já instalada


# --------------------------------------------------------------------------- leitura do sistema

def reg(hive, path: str, name: str | None = None):
    """Lê valor (ou só testa a chave se name=None) sempre na visão 64 bits."""
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return True if name is None else winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_valores(hive, path: str) -> list[str]:
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return [winreg.EnumValue(k, i)[0] for i in range(winreg.QueryInfoKey(k)[1])]
    except OSError:
        return []


def desinstaladores() -> list[str]:
    nomes = []
    for base in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    n = reg(winreg.HKEY_LOCAL_MACHINE, base + "\\" + winreg.EnumKey(k, i), "DisplayName")
                    if n:
                        nomes.append(str(n))
        except OSError:
            pass
    return nomes


def arquivos(pasta: Path, nomes: list[str]) -> list[str]:
    return [n for n in nomes if not (pasta / n).exists()]


def versoes_dir(p: Path) -> list[str]:
    return sorted((d.name for d in p.iterdir() if d.is_dir()), key=dp.vtuple) if p.exists() else []


# --------------------------------------------------------------------------- verificações
# cada check devolve (status, detalhe): status em OK | FALTA | DESATUALIZADO | INFO

def _vc14(arch: str):
    base = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\\" + arch
    for p in (base, base.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\")):
        if reg(winreg.HKEY_LOCAL_MACHINE, p, "Installed") == 1:
            maj = reg(winreg.HKEY_LOCAL_MACHINE, p, "Major") or 14
            mi = reg(winreg.HKEY_LOCAL_MACHINE, p, "Minor") or 0
            bld = reg(winreg.HKEY_LOCAL_MACHINE, p, "Bld") or 0
            v = f"{maj}.{mi}.{bld}"
            # jogos compilados com VS 2022 17.10+ fecham sozinhos com runtime < 14.40
            if (maj, mi) < (14, 40):
                return "DESATUALIZADO", f"{v} (jogos novos exigem 14.40+)"
            return "OK", v
    return "FALTA", "não instalado"


def _dll(pasta: Path, *nomes: str):
    falta = arquivos(pasta, list(nomes))
    return ("OK", "presente") if not falta else ("FALTA", ", ".join(falta) + " ausente")


def _desinst(rx: str):
    return ("OK", "instalado") if any(re.search(rx, n, re.I) for n in desinstaladores()) else ("FALTA", "não instalado")


def _directx():
    nomes = ["d3dx9_43.dll", "d3dx10_43.dll", "d3dx11_43.dll", "d3dcompiler_43.dll", "xinput1_3.dll", "xaudio2_7.dll"]
    falta = arquivos(SYS64, nomes) + [n + " (32 bits)" for n in arquivos(SYS32, nomes)]
    return ("OK", "DirectX 9/10/11 legado presente") if not falta else ("FALTA", ", ".join(falta[:4]) + ("..." if len(falta) > 4 else ""))


def _net35():
    return ("OK", "ativo") if reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5", "Install") == 1 \
        else ("FALTA", "recurso do Windows desativado")


def _net48():
    rel = reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release") or 0
    return ("OK", f"release {rel}") if rel >= 528040 else ("FALTA", f"release {rel or 'ausente'}")


def _desktop(maj: int, x86: bool):
    p = (PF86 if x86 else PF) / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"
    vs = [v for v in versoes_dir(p) if v.split(".")[0] == str(maj)]
    return ("OK", vs[-1]) if vs else ("FALTA", "não instalado")


def _xna():
    return ("OK", "instalado") if reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\XNA\Framework\v4.0", "Installed") == 1 \
        else ("FALTA", "não instalado")


def _openal():
    falta = arquivos(SYS64, ["OpenAL32.dll"]) + arquivos(SYS32, ["OpenAL32.dll"])
    return ("OK", "presente") if not falta else ("FALTA", "OpenAL32.dll ausente")


def _webview2():
    g = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    v = reg(winreg.HKEY_LOCAL_MACHINE, g, "pv") or reg(winreg.HKEY_CURRENT_USER, g.replace("WOW6432Node\\", ""), "pv")
    return ("OK", v) if v and v != "0.0.0.0" else ("FALTA", "não instalado")


def _vulkan():
    return ("OK", "presente") if (SYS64 / "vulkan-1.dll").exists() else \
        ("INFO", "ausente: vem junto com o driver de vídeo (aba Drivers)")


def _directplay():
    try:
        out = dp.powershell("(Get-WindowsOptionalFeature -Online -FeatureName DirectPlay).State", 120)
    except Exception:
        out = ""
    return ("OK", "ativo") if "Enabled" in out else ("FALTA", "recurso do Windows desativado")


# --------------------------------------------------------------------------- catálogo de componentes

MS = "Microsoft"
VC_ARGS = "/install /quiet /norestart"
COMPONENTES: list[dict] = [
    {"id": "vc2022x64", "nome": "Visual C++ 2015-2022 (64 bits)", "grupo": "Visual C++", "check": lambda: _vc14("x64"),
     "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe", "args": VC_ARGS, "signer": MS,
     "desc": "Exigido por praticamente todo jogo atual. Versão antiga faz jogo novo fechar ao abrir."},
    {"id": "vc2022x86", "nome": "Visual C++ 2015-2022 (32 bits)", "grupo": "Visual C++", "check": lambda: _vc14("x86"),
     "url": "https://aka.ms/vs/17/release/vc_redist.x86.exe", "args": VC_ARGS, "signer": MS,
     "desc": "Launchers e jogos 32 bits precisam dele mesmo em Windows 64 bits."},
    {"id": "vc2013x64", "nome": "Visual C++ 2013 (64 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS64, "msvcr120.dll", "msvcp120.dll"),
     "url": "https://aka.ms/highdpimfc2013x64enu", "args": VC_ARGS, "signer": MS, "desc": "Jogos de 2013-2016."},
    {"id": "vc2013x86", "nome": "Visual C++ 2013 (32 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS32, "msvcr120.dll", "msvcp120.dll"),
     "url": "https://aka.ms/highdpimfc2013x86enu", "args": VC_ARGS, "signer": MS, "desc": "Jogos de 2013-2016."},
    {"id": "vc2012x64", "nome": "Visual C++ 2012 (64 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS64, "msvcr110.dll", "msvcp110.dll"),
     "url": "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/VSU_4/vcredist_x64.exe",
     "args": VC_ARGS, "signer": MS, "desc": "Jogos de 2012-2015."},
    {"id": "vc2012x86", "nome": "Visual C++ 2012 (32 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS32, "msvcr110.dll", "msvcp110.dll"),
     "url": "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/VSU_4/vcredist_x86.exe",
     "args": VC_ARGS, "signer": MS, "desc": "Jogos de 2012-2015."},
    {"id": "vc2010x64", "nome": "Visual C++ 2010 (64 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS64, "msvcr100.dll", "msvcp100.dll"),
     "url": "https://download.microsoft.com/download/1/6/5/165255E7-1014-4D0A-B094-B6A430A6BFFC/vcredist_x64.exe",
     "args": "/q /norestart", "signer": MS, "desc": "Jogos de 2010-2013."},
    {"id": "vc2010x86", "nome": "Visual C++ 2010 (32 bits)", "grupo": "Visual C++", "check": lambda: _dll(SYS32, "msvcr100.dll", "msvcp100.dll"),
     "url": "https://download.microsoft.com/download/1/6/5/165255E7-1014-4D0A-B094-B6A430A6BFFC/vcredist_x86.exe",
     "args": "/q /norestart", "signer": MS, "desc": "Jogos de 2010-2013."},
    {"id": "vc2008x64", "nome": "Visual C++ 2008 (64 bits)", "grupo": "Visual C++",
     "check": lambda: _desinst(r"Visual C\+\+ 2008 .*x64"),
     "url": "https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x64.exe",
     "args": "/q", "signer": MS, "desc": "Jogos antigos (2008-2011)."},
    {"id": "vc2008x86", "nome": "Visual C++ 2008 (32 bits)", "grupo": "Visual C++",
     "check": lambda: _desinst(r"Visual C\+\+ 2008 .*x86"),
     "url": "https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x86.exe",
     "args": "/q", "signer": MS, "desc": "Jogos antigos (2008-2011)."},
    {"id": "vc2005x64", "nome": "Visual C++ 2005 (64 bits)", "grupo": "Visual C++",
     "check": lambda: _desinst(r"Visual C\+\+ 2005 .*\(x64\)"),
     "url": "https://download.microsoft.com/download/8/B/4/8B42259F-5D70-43F4-AC2E-4B208FD8D66A/vcredist_x64.EXE",
     "args": "/q", "signer": MS, "desc": "Jogos clássicos (2005-2009)."},
    {"id": "vc2005x86", "nome": "Visual C++ 2005 (32 bits)", "grupo": "Visual C++",
     "check": lambda: _desinst(r"Visual C\+\+ 2005 Redistributable$|Visual C\+\+ 2005 .*x86"),
     "url": "https://download.microsoft.com/download/8/B/4/8B42259F-5D70-43F4-AC2E-4B208FD8D66A/vcredist_x86.EXE",
     "args": "/q", "signer": MS, "desc": "Jogos clássicos (2005-2009)."},
    {"id": "directx", "nome": "DirectX 9/10/11 legado (junho 2010)", "grupo": "DirectX", "check": _directx,
     "url": "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe",
     "tipo": "directx", "signer": MS,
     "desc": "O Windows 10/11 NÃO traz d3dx9, XInput 1.3 e XAudio 2.7. Sem eles: erro 'd3dx9_43.dll não encontrado' e controle que não funciona."},
    {"id": "net35", "nome": ".NET Framework 3.5", "grupo": ".NET", "check": _net35, "tipo": "dism",
     "feature": "NetFx3", "desc": "Jogos e ferramentas mais antigos. Ativado pelo Windows Update."},
    {"id": "net48", "nome": ".NET Framework 4.8", "grupo": ".NET", "check": _net48,
     "url": "https://go.microsoft.com/fwlink/?linkid=2088631", "args": "/q /norestart", "signer": MS,
     "desc": "Launchers e mods."},
    {"id": "wdr8x64", "nome": ".NET Desktop Runtime 8 (64 bits)", "grupo": ".NET", "check": lambda: _desktop(8, False),
     "url": "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe", "args": VC_ARGS, "signer": MS,
     "desc": "Launchers, ferramentas de mod e alguns jogos indie."},
    {"id": "wdr8x86", "nome": ".NET Desktop Runtime 8 (32 bits)", "grupo": ".NET", "check": lambda: _desktop(8, True),
     "url": "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x86.exe", "args": VC_ARGS, "signer": MS,
     "desc": "Versão 32 bits do anterior."},
    {"id": "wdr10x64", "nome": ".NET Desktop Runtime 10 (64 bits)", "grupo": ".NET", "check": lambda: _desktop(10, False),
     "url": "https://aka.ms/dotnet/10.0/windowsdesktop-runtime-win-x64.exe", "args": VC_ARGS, "signer": MS,
     "desc": "Versão atual (LTS), usada por apps novos."},
    {"id": "xna40", "nome": "XNA Framework 4.0", "grupo": "Outros", "check": _xna, "tipo": "msi",
     "url": "https://download.microsoft.com/download/A/C/2/AC2C903B-E6E8-42C2-9FD7-BEBAC362A930/xnafx40_redist.msi",
     "signer": MS, "desc": "Terraria, Stardew Valley (versões antigas), Fez e outros indies."},
    {"id": "openal", "nome": "OpenAL", "grupo": "Outros", "check": _openal, "tipo": "openal",
     "url": "https://www.openal.org/downloads/oalinst.zip", "signer": "Creative",
     "desc": "Áudio 3D de vários jogos clássicos e emuladores."},
    {"id": "webview2", "nome": "Microsoft Edge WebView2", "grupo": "Outros", "check": _webview2,
     "url": "https://go.microsoft.com/fwlink/p/?LinkId=2124703", "args": "/silent /install", "signer": MS,
     "desc": "Launchers modernos (EA app, Battle.net, Riot...) mostram tela em branco sem ele."},
    {"id": "directplay", "nome": "DirectPlay", "grupo": "Outros", "check": _directplay, "tipo": "dism",
     "feature": "DirectPlay", "opcional": True, "desc": "Só para jogos muito antigos (anos 2000) com multiplayer."},
    {"id": "vulkan", "nome": "Vulkan", "grupo": "Outros", "check": _vulkan, "tipo": "info",
     "desc": "Instalado pelo driver de vídeo. Se faltar, atualize o driver da placa de vídeo."},
]
POR_ID = {c["id"]: c for c in COMPONENTES}


def verificar() -> list[dict]:
    out = []
    for c in COMPONENTES:
        try:
            st, det = c["check"]()
        except Exception as ex:
            st, det = "INFO", f"não foi possível verificar: {ex}"
        out.append({"id": c["id"], "nome": c["nome"], "grupo": c["grupo"], "status": st, "detalhe": det,
                    "desc": c["desc"], "opcional": c.get("opcional", False),
                    "instalavel": c.get("tipo") != "info"})
    return out


# --------------------------------------------------------------------------- instalação

def _baixar(c: dict) -> Path:
    DL.mkdir(parents=True, exist_ok=True)
    pasta = DL / c["id"]
    if pasta.exists():
        shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir()
    req = urllib.request.Request(c["url"], headers={"User-Agent": dp.UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        nome = Path(urllib.request.urlparse(r.geturl()).path).name or (c["id"] + ".exe")
        if "." not in nome:
            nome += ".exe"
        arq = pasta / nome
        with arq.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    return arq


def _assinatura_ok(arq: Path, signer: str) -> None:
    st, sub = dp.assinatura(arq)
    if st != "Valid" or signer.lower() not in sub.lower():
        arq.unlink(missing_ok=True)
        raise RuntimeError(f"assinatura não confere ({st}, {sub or 'sem assinante'}) - arquivo apagado")
    dp.log(f"  assinatura válida: {sub.split(',')[0]}")


def _exec(cmd: list[str] | str, cwd: Path | None = None) -> int:
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                       timeout=3600, creationflags=dp.NO_WINDOW)
    return r.returncode


def instalar_um(cid: str) -> tuple[bool, bool, str]:
    c = POR_ID[cid]
    tipo = c.get("tipo", "exe")
    if tipo == "info":
        return False, False, "não instalável por aqui"
    if tipo == "dism":
        rc = _exec(["dism.exe", "/Online", "/Enable-Feature", f"/FeatureName:{c['feature']}", "/All", "/NoRestart", "/Quiet"])
        if cid == "directplay" and rc not in RC_OK:  # DirectPlay depende de LegacyComponents
            _exec(["dism.exe", "/Online", "/Enable-Feature", "/FeatureName:LegacyComponents", "/All", "/NoRestart", "/Quiet"])
            rc = _exec(["dism.exe", "/Online", "/Enable-Feature", f"/FeatureName:{c['feature']}", "/All", "/NoRestart", "/Quiet"])
        return rc in RC_OK, rc in (3010, 1641), f"DISM código {rc}"
    dp.log(f"  baixando {c['url']}")
    arq = _baixar(c)
    if tipo == "openal":
        with zipfile.ZipFile(arq) as z:
            z.extractall(arq.parent)
        exe = next(arq.parent.rglob("oalinst.exe"))
        _assinatura_ok(exe, c["signer"])
        rc = _exec([str(exe), "/s"], exe.parent)
        return rc in RC_OK, False, f"código {rc}"
    _assinatura_ok(arq, c["signer"])
    if tipo == "msi":
        rc = _exec(["msiexec.exe", "/i", str(arq), "/qn", "/norestart"])
    elif tipo == "directx":
        x = arq.parent / "x"
        x.mkdir(exist_ok=True)
        _exec(f'"{arq}" /Q /T:"{x}"')
        setup = x / "DXSETUP.exe"
        if not setup.exists():
            return False, False, "falha ao extrair o DirectX"
        _assinatura_ok(setup, MS)
        rc = _exec([str(setup), "/silent"], x)
    else:
        rc = _exec(f'"{arq}" {c.get("args", "")}', arq.parent)
    return rc in RC_OK, rc in (3010, 1641), f"código {rc}"


def instalar(ids: list[str], progresso=None) -> dict:
    res = {"ok": [], "falha": [], "reboot": False}
    for n, cid in enumerate(ids, 1):
        c = POR_ID[cid]
        if progresso:
            progresso(n, len(ids), c["nome"])
        dp.log(f"\n[{n}/{len(ids)}] {c['nome']}")
        try:
            ok, rb, msg = instalar_um(cid)
        except Exception as ex:
            ok, rb, msg = False, False, str(ex)
        dp.log(("  OK: " if ok else "  FALHOU: ") + msg)
        res["ok" if ok else "falha"].append((c["nome"], msg))
        res["reboot"] = res["reboot"] or rb
    return res


def pendentes(itens: list[dict]) -> list[str]:
    """O que o botão 'Instalar o que falta' instala (opcionais ficam de fora)."""
    return [i["id"] for i in itens if i["status"] in ("FALTA", "DESATUALIZADO") and i["instalavel"] and not i["opcional"]]
