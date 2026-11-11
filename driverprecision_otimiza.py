"""
Otimização avançada para jogos.

Regras:
- Cada ajuste é um item de AJUSTES (dados), com risco, se pede reinício e explicação em português simples.
- Antes de aplicar, o valor ORIGINAL de cada chave/configuração vai para um backup em JSON.
  "Desfazer" devolve exatamente o que estava antes (inclusive apagando o que não existia).
- Aplicar duas vezes não sobrescreve o backup original.

Para adicionar um ajuste: acrescente um dict em AJUSTES. Ajustes só de registro usam a lista "reg";
os que precisam de comando (powercfg, bcdedit) ou de chaves descobertas na hora usam "tipo".
"""
from __future__ import annotations

import json
import re
import subprocess
import winreg
from pathlib import Path

import driverprecision as dp

BACKUP = dp.BASE / "otimizacao_backup.json"
DW, SZ = "DWORD", "SZ"
HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
TIPOS = {DW: winreg.REG_DWORD, SZ: winreg.REG_SZ}
TIPOS_INV = {v: k for k, v in TIPOS.items()}


# --------------------------------------------------------------------------- registro (trocável nos testes)

class Registro:
    """Acesso real ao registro, sempre na visão 64 bits."""
    F = winreg.KEY_WOW64_64KEY

    def get(self, hive: str, path: str, name: str):
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | self.F) as k:
                v, t = winreg.QueryValueEx(k, name)
                return True, TIPOS_INV.get(t, str(t)), v
        except OSError:
            return False, None, None

    def set(self, hive: str, path: str, name: str, tipo: str, valor) -> None:
        with winreg.CreateKeyEx(HIVES[hive], path, 0, winreg.KEY_SET_VALUE | self.F) as k:
            winreg.SetValueEx(k, name, 0, TIPOS[tipo], valor)

    def delete(self, hive: str, path: str, name: str) -> None:
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_SET_VALUE | self.F) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    def subkeys(self, hive: str, path: str) -> list[str]:
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | self.F) as k:
                return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
        except OSError:
            return []


REG = Registro()


def _cmd(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, timeout=120, creationflags=dp.NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace") if r.stdout else ""
    if "\ufffd" in out:  # console em cp850 (Windows PT)
        out = r.stdout.decode("cp850", "replace")
    return r.returncode, out


# --------------------------------------------------------------------------- chaves descobertas na hora

def _gpus() -> list[str]:
    try:
        out = dp.powershell("(Get-CimInstance Win32_VideoController | Where-Object { $_.PNPDeviceID -like 'PCI\\*' }).PNPDeviceID", 60)
    except Exception:
        return []
    return [l.strip() for l in out.splitlines() if l.strip()]


def _interfaces_ativas() -> list[str]:
    base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    out = []
    for g in REG.subkeys("HKLM", base):
        p = base + "\\" + g
        ip = REG.get("HKLM", p, "DhcpIPAddress")[2] or REG.get("HKLM", p, "IPAddress")[2]
        if isinstance(ip, list):
            ip = next((x for x in ip if x), "")
        if ip and ip != "0.0.0.0":
            out.append(p)
    return out


def regs_do_ajuste(a: dict) -> list[tuple]:
    t = a.get("tipo")
    if t == "msi_gpu":
        return [("HKLM", rf"SYSTEM\CurrentControlSet\Enum\{g}\Device Parameters\Interrupt Management\MessageSignaledInterruptProperties",
                 "MSISupported", DW, 1) for g in _gpus()]
    if t == "nagle":
        regs = []
        for p in _interfaces_ativas():
            regs += [("HKLM", p, "TcpAckFrequency", DW, 1), ("HKLM", p, "TCPNoDelay", DW, 1), ("HKLM", p, "TcpDelAckTicks", DW, 0)]
        return regs
    return a.get("reg", [])


# --------------------------------------------------------------------------- powercfg / bcdedit

ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
ALTO_DESEMPENHO = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def plano_ativo() -> str:
    m = re.search(GUID, _cmd(["powercfg", "/getactivescheme"])[1], re.I)
    return m.group(0).lower() if m else ""


def _plano_maximo() -> str:
    lista = _cmd(["powercfg", "/list"])[1]
    for linha in lista.splitlines():
        if re.search(r"Ultimate|Desempenho M[aá]ximo", linha, re.I):
            m = re.search(GUID, linha, re.I)
            if m:
                return m.group(0).lower()
    rc, out = _cmd(["powercfg", "-duplicatescheme", ULTIMATE])
    m = re.search(GUID, out, re.I)
    if rc == 0 and m:
        return m.group(0).lower()
    return ALTO_DESEMPENHO  # notebooks com Modern Standby não têm o Desempenho Máximo


def _pc_path(sub: str, setting: str) -> str:
    """Onde o Windows guarda o valor personalizado da configuração no plano ativo (funciona até para as ocultas)."""
    return rf"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes\{plano_ativo()}\{sub}\{setting}"


def _pc_regs(sub: str, setting: str) -> list[tuple[str, str, str]]:
    p = _pc_path(sub, setting)
    return [("HKLM", p, "ACSettingIndex"), ("HKLM", p, "DCSettingIndex")]


def _pc_set(sub: str, setting: str, ac: int, dc: int | None = None) -> None:
    _cmd(["powercfg", "/setacvalueindex", "SCHEME_CURRENT", sub, setting, str(ac)])
    if dc is not None:
        _cmd(["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", sub, setting, str(dc)])
    _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])


def bitlocker_ativo() -> bool:
    out = _cmd(["manage-bde", "-status", "C:"])[1]
    return bool(re.search(r"(Protection On|Prote[cç][aã]o Ativada|Status da Prote[cç][aã]o:\s*Ativ)", out, re.I))


def _bcd_get(nome: str) -> str | None:
    out = _cmd(["bcdedit", "/enum", "{current}"])[1]
    m = re.search(rf"^{nome}\s+(\S+)", out, re.I | re.M)
    return m.group(1) if m else None


def _bcd_restaura(nome: str, valor: str | None) -> None:
    if valor is None:
        _cmd(["bcdedit", "/deletevalue", nome])
    else:
        _cmd(["bcdedit", "/set", nome, "yes" if valor.lower() in ("yes", "sim", "on", "true") else "no"])


# --------------------------------------------------------------------------- catálogo de ajustes

SUB_PROC = "54533251-82be-4824-96c1-47b60b740d00"
CPMINCORES = "0cc5b647-c1df-4637-891a-dec35c318583"
SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
MM = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
GCS = r"System\GameConfigStore"

AJUSTES: list[dict] = [
    # ---- Energia e CPU
    {"id": "plano_max", "cat": "Energia e CPU", "nome": "Plano de energia Desempenho Máximo", "risco": "baixo",
     "tipo": "plano", "desc": "Ativa o plano escondido do Windows que tira os atrasos de economia de energia do processador. "
                               "Em notebook, use na tomada."},
    {"id": "core_parking", "cat": "Energia e CPU", "nome": "Desligar estacionamento de núcleos", "risco": "médio",
     "tipo": "powercfg", "pc": (SUB_PROC, CPMINCORES, 100, None),
     "desc": "Mantém todos os núcleos acordados (na tomada). Evita travadinhas quando o jogo pede CPU de repente."},
    {"id": "throttling", "cat": "Energia e CPU", "nome": "Desligar Power Throttling", "risco": "médio", "reboot": True,
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", DW, 1)],
     "desc": "Impede o Windows de reduzir a CPU de programas que ele acha que estão em segundo plano."},
    {"id": "prio_sep", "cat": "Energia e CPU", "nome": "Prioridade para o programa em primeiro plano", "risco": "médio",
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", DW, 0x26)],
     "desc": "Dá fatias de tempo de CPU mais curtas e com reforço para a janela ativa (o jogo)."},
    {"id": "timer", "cat": "Energia e CPU", "nome": "Timer do sistema sem 'tick' dinâmico", "risco": "alto", "reboot": True,
     "tipo": "bcd", "desc": "Desliga o tick dinâmico e remove HPET forçado. Reduz variação de frame time. "
                             "Gasta mais bateria. Bloqueado se o BitLocker estiver ativo (poderia pedir a chave de recuperação)."},
    # ---- Placa de vídeo
    {"id": "hags", "cat": "Placa de vídeo", "nome": "Agendamento de GPU acelerado por hardware", "risco": "médio", "reboot": True,
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", DW, 2)],
     "desc": "A própria placa de vídeo organiza sua fila de trabalho. Menos latência em GPUs NVIDIA 10xx+/AMD 5000+. Exigido pelo Frame Generation."},
    {"id": "msi_gpu", "cat": "Placa de vídeo", "nome": "Modo MSI na placa de vídeo", "risco": "alto", "reboot": True,
     "tipo": "msi_gpu", "desc": "Troca as interrupções antigas (compartilhadas) por interrupções por mensagem. "
                                 "Reduz latência e micro-travadas. GPUs muito antigas podem não suportar: se der tela azul, "
                                 "inicie em modo de segurança e clique em Desfazer."},
    {"id": "fso", "cat": "Placa de vídeo", "nome": "Desligar otimizações de tela cheia", "risco": "médio",
     "reg": [("HKCU", GCS, "GameDVR_FSEBehaviorMode", DW, 2), ("HKCU", GCS, "GameDVR_HonorUserFSEBehaviorMode", DW, 1),
             ("HKCU", GCS, "GameDVR_FSEBehavior", DW, 2), ("HKCU", GCS, "GameDVR_DXGIHonorFSEWindowsCompatible", DW, 1)],
     "desc": "Jogos em tela cheia exclusiva de verdade, sem o Windows tratá-los como janela. Menos input lag em DX9/DX11."},
    {"id": "game_dvr", "cat": "Placa de vídeo", "nome": "Desligar gravação em segundo plano (Game DVR)", "risco": "baixo",
     "reg": [("HKCU", GCS, "GameDVR_Enabled", DW, 0),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", DW, 0),
             ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", DW, 0)],
     "desc": "O Windows grava os últimos minutos do jogo o tempo todo. Desligar libera GPU e disco."},
    {"id": "game_mode", "cat": "Placa de vídeo", "nome": "Modo de Jogo ligado", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", DW, 1),
             ("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", DW, 1)],
     "desc": "Pausa atualizações do Windows e dá prioridade ao jogo enquanto ele roda."},
    # ---- Agendador multimídia
    {"id": "mmcss", "cat": "Agendador multimídia", "nome": "Prioridade máxima para jogos no MMCSS", "risco": "médio", "reboot": True,
     "reg": [("HKLM", MM, "SystemResponsiveness", DW, 0),
             ("HKLM", MM + r"\Tasks\Games", "GPU Priority", DW, 8), ("HKLM", MM + r"\Tasks\Games", "Priority", DW, 6),
             ("HKLM", MM + r"\Tasks\Games", "Scheduling Category", SZ, "High"),
             ("HKLM", MM + r"\Tasks\Games", "SFIO Priority", SZ, "High")],
     "desc": "Por padrão o Windows reserva 20% da CPU para tarefas de fundo. Isso zera a reserva e põe jogos na fila mais alta."},
    # ---- Rede
    {"id": "net_throttle", "cat": "Rede", "nome": "Desligar limitação de rede durante jogos", "risco": "baixo", "reboot": True,
     "reg": [("HKLM", MM, "NetworkThrottlingIndex", DW, 0xFFFFFFFF)],
     "desc": "O Windows limita pacotes de rede quando há áudio/vídeo tocando. Isso remove o limite."},
    {"id": "nagle", "cat": "Rede", "nome": "Desligar algoritmo de Nagle (menos ping)", "risco": "médio", "reboot": True,
     "tipo": "nagle", "desc": "Envia cada pacote na hora, sem juntar vários. Reduz atraso em jogos online. "
                               "Aplica nas placas de rede conectadas agora."},
    # ---- Mouse e teclado
    {"id": "mouse_accel", "cat": "Mouse e teclado", "nome": "Desligar aceleração do mouse", "risco": "baixo", "reboot": True,
     "reg": [("HKCU", r"Control Panel\Mouse", "MouseSpeed", SZ, "0"), ("HKCU", r"Control Panel\Mouse", "MouseThreshold1", SZ, "0"),
             ("HKCU", r"Control Panel\Mouse", "MouseThreshold2", SZ, "0")],
     "desc": "Mira 1:1: o cursor anda sempre a mesma distância para o mesmo movimento. Vale ao sair e entrar na conta."},
    {"id": "usb_suspend", "cat": "Mouse e teclado", "nome": "Não suspender portas USB", "risco": "baixo",
     "tipo": "powercfg", "pc": (SUB_USB, USB_SUSPEND, 0, 0),
     "desc": "Evita que mouse, teclado ou controle 'durmam' e percam o primeiro clique."},
    # ---- Windows
    {"id": "bg_apps", "cat": "Windows", "nome": "Bloquear apps em segundo plano", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", DW, 1),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BackgroundAppGlobalToggle", DW, 0)],
     "desc": "Apps da Loja param de rodar escondidos. Notificações desses apps podem atrasar."},
    {"id": "visual", "cat": "Windows", "nome": "Efeitos visuais no mínimo", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", DW, 2),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", DW, 0),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", DW, 0),
             ("HKCU", r"Control Panel\Desktop", "MenuShowDelay", SZ, "0")],
     "desc": "Tira transparências e animações do Windows. Ajuda em PC fraco."},
    {"id": "vbs", "cat": "Segurança x desempenho", "nome": "Desligar Integridade de Memória (VBS/HVCI)", "risco": "alto",
     "reboot": True, "seguranca": True,
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled", DW, 0),
             ("HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard", "EnableVirtualizationBasedSecurity", DW, 0)],
     "desc": "Ganho de 5 a 15% de FPS em muitos PCs (a própria Microsoft sugere isso para jogos). "
             "Em troca, o Windows fica menos protegido contra drivers maliciosos. Alguns jogos com anti-cheat exigem que fique LIGADO."},
]
POR_ID = {a["id"]: a for a in AJUSTES}


# --------------------------------------------------------------------------- backup

def _ler_backup() -> dict:
    try:
        return json.loads(BACKUP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _salvar_backup(b: dict) -> None:
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- estado / aplicar / desfazer

def estado(a: dict) -> str:
    """ATIVO | PADRÃO | PARCIAL | N/A"""
    t = a.get("tipo")
    if t == "plano":
        pa = plano_ativo()
        nome = _cmd(["powercfg", "/getactivescheme"])[1]
        return "ATIVO" if pa in (ULTIMATE,) or re.search(r"Ultimate|Desempenho M[aá]ximo", nome, re.I) else "PADRÃO"
    if t == "powercfg":
        sub, st, ac, _ = a["pc"]
        return "ATIVO" if REG.get("HKLM", _pc_path(sub, st), "ACSettingIndex")[2] == ac else "PADRÃO"
    if t == "bcd":
        v = _bcd_get("disabledynamictick")
        return "ATIVO" if v and v.lower() in ("yes", "sim") else "PADRÃO"
    regs = regs_do_ajuste(a)
    if not regs:
        return "N/A"
    iguais = sum(1 for h, p, n, tp, v in regs if REG.get(h, p, n)[2] == v)
    return "ATIVO" if iguais == len(regs) else ("PARCIAL" if iguais else "PADRÃO")


def aplicar(aid: str) -> str:
    a = POR_ID[aid]
    b = _ler_backup()
    orig = b.get(aid)  # já aplicado antes: mantém o original da primeira vez
    t = a.get("tipo")
    if t == "plano":
        if orig is None:
            orig = {"plano": plano_ativo()}
        g = _plano_maximo()
        _cmd(["powercfg", "/setactive", g])
        msg = "plano Desempenho Máximo ativo" if g != ALTO_DESEMPENHO else "plano Alto Desempenho ativo (Desempenho Máximo indisponível neste PC)"
    elif t == "powercfg":
        sub, st, ac, dc = a["pc"]
        if orig is None:  # guarda o valor personalizado (ou a ausência dele) do plano ativo
            orig = {"reg": [[h, p, n, *REG.get(h, p, n)] for h, p, n in _pc_regs(sub, st)], "recarregar_plano": True}
        _pc_set(sub, st, ac, dc)
        msg = "aplicado no plano de energia atual"
    elif t == "bcd":
        if bitlocker_ativo():
            raise RuntimeError("BitLocker ativo no disco C: - suspenda o BitLocker antes, ou deixe este ajuste de lado")
        if orig is None:
            orig = {"bcd": {"disabledynamictick": _bcd_get("disabledynamictick"),
                            "useplatformclock": _bcd_get("useplatformclock")}}
        _cmd(["bcdedit", "/set", "disabledynamictick", "yes"])
        _cmd(["bcdedit", "/deletevalue", "useplatformclock"])
        msg = "configuração de boot alterada"
    else:
        regs = regs_do_ajuste(a)
        if not regs:
            raise RuntimeError("nada a aplicar neste PC (sem GPU PCI ou sem rede conectada)")
        if orig is None:
            orig = {"reg": []}
            for h, p, n, tp, v in regs:
                existe, tipo, valor = REG.get(h, p, n)
                orig["reg"].append([h, p, n, existe, tipo, valor])
        for h, p, n, tp, v in regs:
            REG.set(h, p, n, tp, v)
        msg = f"{len(regs)} valor(es) do registro alterados"
    b[aid] = orig
    _salvar_backup(b)
    return msg + (" - reinicie para valer" if a.get("reboot") else "")


def desfazer(aid: str) -> str:
    a = POR_ID[aid]
    b = _ler_backup()
    orig = b.get(aid)
    if orig is None:
        return "nada a desfazer (não foi aplicado por este programa)"
    if "plano" in orig and orig["plano"]:
        _cmd(["powercfg", "/setactive", orig["plano"]])
    if "bcd" in orig:
        for nome, valor in orig["bcd"].items():
            _bcd_restaura(nome, valor)
    for h, p, n, existe, tipo, valor in orig.get("reg", []):
        if existe and tipo in TIPOS:
            REG.set(h, p, n, tipo, valor)
        else:
            REG.delete(h, p, n)
    if orig.get("recarregar_plano"):
        _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
    del b[aid]
    _salvar_backup(b)
    return "restaurado ao valor original" + (" - reinicie para valer" if a.get("reboot") else "")


def aplicados() -> list[str]:
    return list(_ler_backup().keys())


def listar() -> list[dict]:
    out = []
    for a in AJUSTES:
        try:
            st = estado(a)
        except Exception:
            st = "N/A"
        out.append({"id": a["id"], "nome": a["nome"], "cat": a["cat"], "risco": a["risco"], "estado": st,
                    "desc": a["desc"], "reboot": a.get("reboot", False), "seguranca": a.get("seguranca", False),
                    "nosso": a["id"] in aplicados()})
    return out
