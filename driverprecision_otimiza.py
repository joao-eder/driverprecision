"""
Motor dos ajustes do Windows: telas "Otimização" (jogos) e "Escritório".

Regras:
- Cada ajuste é um item de AJUSTES (dados), com risco, se pede reinício e explicação em português simples.
- Antes de aplicar, o valor ORIGINAL de cada chave/configuração vai para um backup em JSON.
  "Desfazer" devolve exatamente o que estava antes (inclusive apagando o que não existia).
- Aplicar duas vezes não sobrescreve o backup original.

Para adicionar um ajuste: acrescente um dict em AJUSTES. Ajustes só de registro usam a lista "reg";
os que precisam de comando (powercfg, bcdedit, PowerShell) ou de chaves descobertas na hora usam "tipo".
Campos opcionais: "perfis" (telas onde aparece; padrão só jogos), "aplica_se" (função: o PC tem o programa?),
"recomendado" (False = fora do botão Recomendados), "depois" (comandos após aplicar/desfazer, ex.: iniciar serviço).

PC de empresa (domínio, Entra ID/Azure AD ou Intune): o que a TI costuma controlar (políticas, serviços,
segurança) fica bloqueado, para o programa não brigar com a configuração da empresa.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import winreg

import driverprecision as dp

BACKUP = dp.BASE / "otimizacao_backup.json"
DW, SZ, MSZ = "DWORD", "SZ", "MULTI_SZ"
HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
TIPOS = {DW: winreg.REG_DWORD, SZ: winreg.REG_SZ, MSZ: winreg.REG_MULTI_SZ, "EXPAND_SZ": winreg.REG_EXPAND_SZ}
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


NET_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"


def _placas_rede_ativas() -> list[str]:
    """Chaves de driver das placas de rede físicas que estão com IP agora."""
    guids = {p.rsplit("\\", 1)[-1].lower() for p in _interfaces_ativas()}
    out = []
    for sk in REG.subkeys("HKLM", NET_CLASS):
        p = NET_CLASS + "\\" + sk
        inst = str(REG.get("HKLM", p, "NetCfgInstanceId")[2] or "").lower()
        if inst and inst in guids:
            out.append(p)
    return out


def regs_do_ajuste(a: dict) -> list[tuple]:
    t = a.get("tipo")
    if t == "nic_pnp":  # 24 = desmarca "O computador pode desligar este dispositivo para economizar energia"
        return [("HKLM", p, "PnPCapabilities", DW, 24) for p in _placas_rede_ativas()]
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


def _pc_lidos(sub: str, setting: str, plano: str = "SCHEME_CURRENT") -> tuple[int | None, int | None]:
    """Valores em vigor (tomada, bateria) de uma configuração do plano; (None, None) se ela não existe neste PC.
    Lê pelo powercfg: as chaves do registro dos planos são protegidas até contra administrador."""
    rc, out = _cmd(["powercfg", "/qh", plano, sub, setting])
    vals = re.findall(r":\s*0x([0-9a-fA-F]{8})\s*$", out, re.M)
    if rc != 0 or len(vals) < 2:
        return None, None
    return int(vals[-2], 16), int(vals[-1], 16)


# preferências pessoais que o plano novo herda do anterior (tampa, botões, tempo para apagar a tela e suspender)
PREFERENCIAS_PLANO = [("SUB_BUTTONS", "LIDACTION"), ("SUB_BUTTONS", "PBUTTONACTION"), ("SUB_BUTTONS", "SBUTTONACTION"),
                      ("SUB_VIDEO", "VIDEOIDLE"), ("SUB_SLEEP", "STANDBYIDLE")]


# desempenho também na bateria, aplicado no plano Desempenho Máximo (o padrão de fábrica economiza na bateria)
DESEMPENHO_NA_BATERIA = [
    ("44f3beca-a7c0-460e-9df2-bb8b99e0cba6", "3619c3f2-afb2-4afc-b0e9-e7fef372de36", 2),  # gráficos Intel: desempenho máximo
    ("9596fb26-9850-41fd-ac3e-f7c3c00afd4b", "03680956-93bc-4294-bba6-4e0f09bb717f", 1),  # compartilhando mídia: não suspender
    ("9596fb26-9850-41fd-ac3e-f7c3c00afd4b", "10778347-1370-4ee0-8bbd-33bdacaade49", 1),  # vídeo: tendência de desempenho
    ("9596fb26-9850-41fd-ac3e-f7c3c00afd4b", "34c7b99f-9a6d-4b3c-8dc7-b6693b78cef4", 0),  # vídeo: otimizar qualidade
]


def _desempenho_na_bateria(plano: str) -> None:
    for sub, st, v in DESEMPENHO_NA_BATERIA:  # configuração que o PC não tem (ex.: sem Intel) é ignorada
        _cmd(["powercfg", "/setacvalueindex", plano, sub, st, str(v)])
        _cmd(["powercfg", "/setdcvalueindex", plano, sub, st, str(v)])


def _levar_ajustes_de_energia(plano: str, backup: dict) -> None:
    """Ajustes de energia que o programa já aplicou (Wi-Fi, PCIe, USB, núcleos) valem por plano:
    ao trocar para o plano novo, aplica neles também, senão voltam ao padrão de fábrica."""
    for aid in backup:
        a = POR_ID.get(aid)
        if not a or a.get("tipo") != "powercfg":
            continue
        sub, st, ac, dc = a["pc"]
        _cmd(["powercfg", "/setacvalueindex", plano, sub, st, str(ac)])
        if dc is not None:
            _cmd(["powercfg", "/setdcvalueindex", plano, sub, st, str(dc)])


def _herdar_preferencias(de: str, para: str) -> list[str]:
    """Copia para o plano novo o que a pessoa escolheu no plano antigo. Devolve o que foi copiado."""
    copiados = []
    if not de or de == para:
        return copiados
    for sub, st in PREFERENCIAS_PLANO:
        ac, dc = _pc_lidos(sub, st, de)
        if ac is None:
            continue
        if _cmd(["powercfg", "/setacvalueindex", para, sub, st, str(ac)])[0] == 0:
            _cmd(["powercfg", "/setdcvalueindex", para, sub, st, str(dc)])
            copiados.append(st)
    return copiados


def planos() -> list[str]:
    """GUIDs de todos os planos de energia do PC."""
    return [m.lower() for m in dict.fromkeys(re.findall(GUID, _cmd(["powercfg", "/list"])[1], re.I))]


_BATERIA: bool | None = None


def tem_bateria() -> bool:
    """Notebook (tem bateria e, portanto, tampa)."""
    global _BATERIA
    if _BATERIA is None:
        try:
            _BATERIA = dp.powershell("[bool](Get-CimInstance Win32_Battery)", 60).strip().lower() == "true"
        except Exception:
            _BATERIA = False
    return _BATERIA


def _pc_set(sub: str, setting: str, ac: int, dc: int | None = None) -> None:
    rc, out = _cmd(["powercfg", "/setacvalueindex", "SCHEME_CURRENT", sub, setting, str(ac)])
    if rc != 0:  # a configuração não existe neste PC (ex.: Wi-Fi em desktop sem placa Wi-Fi)
        raise RuntimeError("este PC não tem essa configuração de energia" + (f" ({out.strip()[:120]})" if out.strip() else ""))
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


# --------------------------------------------------------------------------- ajustes via PowerShell

def _ps_ler(a: dict) -> str | None:
    """Valor atual de um ajuste "ps" como texto; None se o recurso não existe neste PC."""
    try:
        out = dp.powershell("$ErrorActionPreference='Stop';" + a["ps"]["ler"], 180).strip()
    except Exception:
        return None
    return out.splitlines()[-1].strip() if out else None


def _ps_ativo(a: dict, v: str | None) -> bool:
    ok = a["ps"].get("ok") or [a["ps"]["alvo"]]
    return v is not None and v.lower() in {x.lower() for x in ok}


def _ps_gravar(a: dict, v: str) -> None:
    script = "$ErrorActionPreference='Stop';" + a["ps"]["gravar"].replace("{v}", v)
    try:
        dp.powershell(script, 900)
    except Exception as ex:
        raise RuntimeError(str(ex).split(" At line:")[0][:300]) from None


def _depois(a: dict) -> None:
    for c in a.get("depois", []):
        try:
            _cmd(c)
        except Exception:
            pass


# --------------------------------------------------------------------------- PC de empresa

_AMBIENTE: dict | None = None
PS_AMBIENTE = r"""
$cs=Get-CimInstance Win32_ComputerSystem
$ds=(& "$env:SystemRoot\System32\dsregcmd.exe" /status 2>$null) -join "`n"
$mdm=@(Get-ChildItem HKLM:\SOFTWARE\Microsoft\Enrollments -ErrorAction SilentlyContinue | Where-Object {
  (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).ProviderID -eq 'MS DM Server' }).Count -gt 0
[pscustomobject]@{dominio=[bool]$cs.PartOfDomain; nome_dominio=[string]$cs.Domain
  entra=[bool]($ds -match 'AzureAdJoined\s*:\s*YES'); mdm=[bool]$mdm} | ConvertTo-Json -Compress
"""


def ambiente() -> dict:
    """{dominio, entra, mdm, gerenciado, descricao}. Lido uma vez por execução."""
    global _AMBIENTE
    if _AMBIENTE is None:
        try:
            d = json.loads(dp.powershell(PS_AMBIENTE, 60))
        except Exception:
            d = {}
        d = {"dominio": bool(d.get("dominio")), "entra": bool(d.get("entra")), "mdm": bool(d.get("mdm")),
             "nome_dominio": d.get("nome_dominio") or ""}
        partes = ([f"domínio {d['nome_dominio']}"] if d["dominio"] else []) + (["Entra ID (Azure AD)"] if d["entra"] else []) \
            + (["Intune/MDM"] if d["mdm"] else [])
        d["gerenciado"] = bool(partes)
        d["descricao"] = ", ".join(partes)
        _AMBIENTE = d
    return _AMBIENTE


def controlado_pela_ti(a: dict) -> bool:
    """Áreas que a TI de uma empresa costuma gerenciar: políticas, serviços e segurança."""
    if a.get("ti") is not None:
        return bool(a["ti"])
    if a.get("tipo") in ("ps", "bcd", "msi_gpu", "plano", "powercfg", "hiber", "todos_planos"):  # segurança, boot e energia
        return True
    return any("\\policies\\" in p.lower() or "\\services\\" in p.lower() for _, p, *_ in a.get("reg", []))


def bloqueado(a: dict) -> str:
    """Motivo pelo qual o ajuste não pode ser aplicado neste PC ('' = pode)."""
    if a.get("aplica_se") and not a["aplica_se"]():
        return a.get("requisito", "não se aplica a este PC")
    amb = ambiente()
    if amb["gerenciado"] and controlado_pela_ti(a):
        return f"PC gerenciado pela empresa ({amb['descricao']}): a TI controla esta configuração"
    return ""


# --------------------------------------------------------------------------- programas instalados

def _tem_chave(*chaves: tuple[str, str]) -> bool:
    return any(REG.subkeys(h, p) or REG.get(h, p, "")[0] for h, p in chaves)


def tem_chrome() -> bool:
    ap = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    return _tem_chave(("HKLM", ap), ("HKCU", ap))


def tem_firefox() -> bool:
    ap = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
    return _tem_chave(("HKLM", ap), ("HKCU", ap), ("HKLM", r"SOFTWARE\Mozilla\Mozilla Firefox"))


def tem_office() -> bool:
    return _tem_chave(("HKLM", r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration"),
                      ("HKLM", r"SOFTWARE\Microsoft\Office\16.0\Excel\InstallRoot"),
                      ("HKCU", r"Software\Microsoft\Office\16.0\Excel"))


def tem_libreoffice() -> bool:
    return _tem_chave(("HKLM", r"SOFTWARE\LibreOffice"), ("HKLM", r"SOFTWARE\WOW6432Node\LibreOffice"))


# --------------------------------------------------------------------------- catálogo de ajustes

SUB_PROC = "54533251-82be-4824-96c1-47b60b740d00"
CPMINCORES = "0cc5b647-c1df-4637-891a-dec35c318583"
SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
SUB_WIFI = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
WIFI_POWER = "12bbebe6-58d6-4636-95bb-3217ef867c1a"
SUB_PCIE = "501a4d13-42af-4429-9fd1-a8218c268e20"
PCIE_ASPM = "ee12f906-d277-404b-b6da-e5fa1a576df5"
MM = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
GCS = r"System\GameConfigStore"
CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
FS = r"SYSTEM\CurrentControlSet\Control\FileSystem"
PWR = r"SYSTEM\CurrentControlSet\Control\Power"

AJUSTES: list[dict] = [
    # ---- Energia e CPU
    {"id": "plano_max", "cat": "Energia e CPU", "nome": "Plano de energia Desempenho Máximo", "risco": "baixo",
     "tipo": "plano", "desc": "Ativa o plano escondido do Windows que tira os atrasos de economia de energia do processador. "
                               "Também na bateria: gráficos Intel no máximo e vídeo em qualidade máxima (gasta mais bateria). "
                               "O que você escolheu para a tampa, os botões e o tempo para apagar a tela é copiado do seu plano atual."},
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
    {"id": "usb_suspend", "perfis": ("jogos", "escritorio"), "cat": "Mouse e teclado", "nome": "Não suspender portas USB", "risco": "baixo",
     "tipo": "powercfg", "pc": (SUB_USB, USB_SUSPEND, 0, 0),
     "desc": "Evita que mouse, teclado ou controle 'durmam' e percam o primeiro clique."},
    # ---- Windows
    {"id": "bg_apps", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Bloquear apps em segundo plano", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", DW, 1),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BackgroundAppGlobalToggle", DW, 0)],
     "desc": "Apps da Loja param de rodar escondidos. Notificações desses apps podem atrasar."},
    {"id": "visual", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Efeitos visuais no mínimo", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", DW, 2),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", DW, 0),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", DW, 0),
             ("HKCU", r"Control Panel\Desktop", "MenuShowDelay", SZ, "0"),
             ("HKCU", r"Control Panel\Desktop", "FontSmoothing", SZ, "2"),       # letras continuam nítidas (ClearType)
             ("HKCU", r"Control Panel\Desktop", "FontSmoothingType", DW, 2)],
     "desc": "Tira transparências e animações do Windows. Ajuda em PC fraco. O ClearType (letras suaves) continua ligado."},
    {"id": "fast_startup", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Desligar Inicialização rápida", "risco": "baixo", "reboot": True,
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", DW, 0)],
     "desc": "Com ela ligada, 'Desligar' na verdade hiberna o núcleo do Windows e os drivers nunca reiniciam do zero. "
             "Desligar resolve driver travado em estado ruim. O boot pode ficar alguns segundos mais lento."},
    {"id": "telemetria", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Desligar telemetria do Windows", "risco": "baixo", "reboot": True,
     "reg": [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", DW, 0),
             ("HKLM", r"SYSTEM\CurrentControlSet\Services\DiagTrack", "Start", DW, 4)],
     "desc": "Para o serviço que envia dados de uso para a Microsoft o tempo todo. Menos processo, disco e rede em segundo plano. "
             "No Windows Home/Pro fica no nível mínimo permitido."},
    {"id": "anuncios", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Desligar anúncios, dicas e apps sugeridos", "risco": "baixo",
     "reg": [("HKCU", CDM, "SilentInstalledAppsEnabled", DW, 0), ("HKCU", CDM, "SystemPaneSuggestionsEnabled", DW, 0),
             ("HKCU", CDM, "SoftLandingEnabled", DW, 0), ("HKCU", CDM, "SubscribedContent-338388Enabled", DW, 0),
             ("HKCU", CDM, "SubscribedContent-338389Enabled", DW, 0), ("HKCU", CDM, "SubscribedContent-310093Enabled", DW, 0),
             ("HKCU", CDM, "SubscribedContent-353694Enabled", DW, 0), ("HKCU", CDM, "SubscribedContent-353696Enabled", DW, 0)],
     "desc": "Impede o Windows de instalar apps 'sugeridos' sozinho e tira dicas e propagandas do Menu Iniciar e das Configurações."},
    {"id": "bing", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Desligar busca na web (Bing) no Menu Iniciar", "risco": "baixo", "reboot": True,
     "reg": [("HKCU", r"Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", DW, 1),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", DW, 0)],
     "desc": "A pesquisa do Menu Iniciar procura só no PC, sem consultar a internet a cada letra. Fica mais rápida."},
    {"id": "startup_delay", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Tirar o atraso dos programas de inicialização", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", DW, 0),
             ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "WaitForIdleState", DW, 0)],
     "desc": "O Windows espera alguns segundos antes de abrir os programas da inicialização. Isso tira a espera."},
    {"id": "hibernacao", "cat": "Windows", "nome": "Desligar hibernação", "risco": "baixo", "tipo": "hiber",
     "desc": "Apaga o arquivo hiberfil.sys e libera vários GB no disco C:. Some a opção 'Hibernar' e a Inicialização rápida "
             "deixa de funcionar. Suspender continua normal."},
    # ---- Disco
    {"id": "trim", "perfis": ("jogos", "escritorio"), "cat": "Disco", "nome": "Garantir TRIM do SSD ligado", "risco": "baixo",
     "reg": [("HKLM", FS, "DisableDeleteNotification", DW, 0)],
     "desc": "O TRIM avisa o SSD quais blocos foram apagados, mantendo a velocidade de gravação com o tempo. "
             "Normalmente já está ligado; aqui só garante."},
    {"id": "last_access", "perfis": ("jogos", "escritorio"), "cat": "Disco", "nome": "Desligar registro de 'último acesso' dos arquivos", "risco": "baixo",
     "reboot": True, "reg": [("HKLM", FS, "NtfsDisableLastAccessUpdate", DW, 0x80000001)],
     "desc": "O Windows grava a data em que cada arquivo foi aberto. Desligar evita milhares de gravações pequenas no disco "
             "(ao carregar jogos, por exemplo)."},
    # ---- Rede (energia)
    {"id": "wu_sem_drivers", "perfis": ("jogos", "escritorio"), "cat": "Windows", "nome": "Windows Update não troca drivers sozinho",
     "risco": "baixo", "recomendado": False,
     "reg": [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate", "ExcludeWUDriversInQualityUpdate", DW, 1)],
     "desc": "O Windows Update para de instalar e trocar drivers por conta própria (ex.: pôr o áudio genérico da Realtek por cima "
             "do adaptado pelo fabricante do notebook). Os drivers ficam com o DriverPrecision, que passa a buscá-los no Catálogo "
             "da Microsoft. As atualizações de segurança do Windows continuam normalmente."},
    {"id": "delivery_p2p", "perfis": ("jogos", "escritorio"), "cat": "Rede", "nome": "Não compartilhar atualizações com outros PCs", "risco": "baixo",
     "reg": [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", DW, 0)],
     "desc": "Por padrão o Windows usa sua internet para enviar atualizações a outros PCs. Isso desliga o envio "
             "(as atualizações continuam chegando normalmente)."},
    {"id": "wifi_power", "perfis": ("jogos", "escritorio"), "cat": "Rede", "nome": "Desligar economia de energia do Wi-Fi", "risco": "médio",
     "tipo": "powercfg", "pc": (SUB_WIFI, WIFI_POWER, 0, 0),
     "desc": "A placa Wi-Fi para de 'cochilar' entre pacotes. Ping mais estável em notebook; gasta um pouco mais de bateria."},
    {"id": "pcie_aspm", "cat": "Placa de vídeo", "nome": "Desligar economia de energia do PCIe (ASPM)", "risco": "médio",
     "tipo": "powercfg", "pc": (SUB_PCIE, PCIE_ASPM, 0, 0),
     "desc": "Placa de vídeo e SSD NVMe não entram em economia de energia entre um quadro e outro. Menos travadinhas. "
             "Vale na tomada e na bateria (gasta mais bateria)."},
    # ---- Mouse e teclado
    {"id": "teclado", "cat": "Mouse e teclado", "nome": "Repetição do teclado mais rápida", "risco": "baixo", "reboot": True,
     "reg": [("HKCU", r"Control Panel\Keyboard", "KeyboardDelay", SZ, "0"),
             ("HKCU", r"Control Panel\Keyboard", "KeyboardSpeed", SZ, "31")],
     "desc": "Tecla segurada começa a repetir mais cedo e mais rápido. Vale ao sair e entrar na conta."},
    {"id": "vbs", "cat": "Segurança x desempenho", "nome": "Desligar Integridade de Memória (VBS/HVCI)", "risco": "alto",
     "reboot": True, "seguranca": True,
     "reg": [("HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled", DW, 0),
             ("HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard", "EnableVirtualizationBasedSecurity", DW, 0)],
     "desc": "Ganho de 5 a 15% de FPS em muitos PCs (a própria Microsoft sugere isso para jogos). "
             "Em troca, o Windows fica menos protegido contra drivers maliciosos. Alguns jogos com anti-cheat exigem que fique LIGADO."},
]

# ---------------------------------------------------------------- Escritório
MEM = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
CHROME = r"SOFTWARE\Policies\Google\Chrome"
FIREFOX = r"SOFTWARE\Policies\Mozilla\Firefox"
OFF_GFX = r"Software\Microsoft\Office\16.0\Common\Graphics"
SVC = r"SYSTEM\CurrentControlSet\Services"
ESC = ("escritorio",)

AJUSTES += [
    # ---- Memória e muitas abas
    {"id": "memcomp", "perfis": ESC, "cat": "Memória e muitas abas", "nome": "Compressão de memória ligada", "risco": "baixo",
     "reboot": True, "tipo": "ps", "ps": {"ler": "(Get-MMAgent).MemoryCompression", "alvo": "True",
                                          "gravar": "if('{v}' -eq 'True'){Enable-MMAgent -MemoryCompression; Start-Sleep 2; "
                                                    "if(-not (Get-MMAgent).MemoryCompression){Enable-MMAgent -MemoryCompression}}"
                                                    "else{Disable-MMAgent -MemoryCompression}"},
     "desc": "O Windows compacta na própria RAM o que está parado (abas, planilhas abertas) em vez de jogar no disco. "
             "Com dezenas de abas, o PC demora muito mais para ficar lento. Vem ligada; muitos 'otimizadores' desligam."},
    {"id": "pagefile", "perfis": ESC, "cat": "Memória e muitas abas", "nome": "Arquivo de paginação gerenciado pelo Windows",
     "risco": "baixo", "reboot": True, "tipo": "ps", "guardar": [("HKLM", MEM, "PagingFiles")],
     "ps": {"ler": "(Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile", "alvo": "True",
            "gravar": "$c=Get-CimInstance Win32_ComputerSystem; Set-CimInstance -InputObject $c -Property @{AutomaticManagedPagefile=[bool]::Parse('{v}')}"},
     "desc": "Paginação desligada ou pequena demais faz o Chrome mostrar 'Sem memória' e o Excel fechar com planilhas grandes. "
             "Deixa o Windows ajustar o tamanho sozinho, que é o recomendado pela Microsoft."},
    {"id": "sysmain", "perfis": ESC, "cat": "Memória e muitas abas", "nome": "SysMain (pré-carregamento) ligado", "risco": "baixo",
     "reg": [("HKLM", SVC + r"\SysMain", "Start", DW, 2)], "depois": [["sc.exe", "start", "SysMain"]],
     "desc": "Serviço do Windows que deixa pré-carregados os programas que você mais usa (Excel, navegador). "
             "Vem ligado; 'otimizadores' costumam desligar e o Excel passa a abrir mais devagar."},
    # ---- Navegadores
    {"id": "chrome_memoria", "perfis": ESC, "cat": "Navegadores", "nome": "Chrome: Economia de memória ligada", "risco": "baixo",
     "aplica_se": lambda: tem_chrome(), "requisito": "Google Chrome não instalado",
     "reg": [("HKLM", CHROME, "HighEfficiencyModeEnabled", DW, 1), ("HKLM", CHROME, "MemorySaverModeSavings", DW, 1)],
     "desc": "Abas paradas há algum tempo saem da memória e recarregam quando você clica nelas (nível equilibrado). "
             "Com muitas abas, o PC todo fica mais leve. Enquanto ativo, a opção fica travada nas configurações do Chrome; "
             "Desfazer devolve o controle. Vale ao reabrir o Chrome."},
    {"id": "chrome_fundo", "perfis": ESC, "cat": "Navegadores", "nome": "Chrome: fechar de verdade ao fechar a janela", "risco": "baixo",
     "aplica_se": lambda: tem_chrome(), "requisito": "Google Chrome não instalado",
     "reg": [("HKLM", CHROME, "BackgroundModeEnabled", DW, 0)],
     "desc": "Por padrão o Chrome continua rodando escondido depois de fechado (extensões e apps). Isso libera essa memória."},
    {"id": "firefox_fundo", "perfis": ESC, "cat": "Navegadores", "nome": "Firefox: sem tarefas em segundo plano", "risco": "baixo",
     "aplica_se": lambda: tem_firefox(), "requisito": "Firefox não instalado",
     "reg": [("HKLM", FIREFOX, "DisableDefaultBrowserAgent", DW, 1), ("HKLM", FIREFOX, "DisableTelemetry", DW, 1)],
     "desc": "Desliga o agente que roda todo dia pelo Agendador do Windows e o envio de telemetria. "
             "O Firefox já tira da memória as abas paradas quando a RAM aperta; isso vem ligado de fábrica."},
    # ---- Excel e Office
    {"id": "office_animacoes", "perfis": ESC, "cat": "Excel e Office", "nome": "Office sem animações", "risco": "baixo",
     "aplica_se": lambda: tem_office(), "requisito": "Microsoft Office/365 não instalado",
     "reg": [("HKCU", OFF_GFX, "DisableAnimations", DW, 1)],
     "desc": "Tira as animações de células, menus e rolagem do Excel, Word e Outlook. Em planilhas grandes, "
             "a navegação fica mais rápida e sem 'arrasto'. Vale ao reabrir o Office."},
    {"id": "office_gpu", "perfis": ESC, "cat": "Excel e Office", "nome": "Office sem aceleração gráfica (só se tiver problema)",
     "risco": "médio", "recomendado": False,
     "aplica_se": lambda: tem_office(), "requisito": "Microsoft Office/365 não instalado",
     "reg": [("HKCU", OFF_GFX, "DisableHardwareAcceleration", DW, 1)],
     "desc": "Use só se o Excel ou o Word piscam, ficam com áreas pretas ou travam ao rolar: é sinal de problema no driver de vídeo. "
             "Em PC sem esses sintomas, deixe como está (a aceleração ajuda)."},
    {"id": "libreoffice_cache", "perfis": ESC, "cat": "Excel e Office", "nome": "LibreOffice: cache de imagens maior", "risco": "baixo",
     "aplica_se": lambda: tem_libreoffice(), "requisito": "LibreOffice não instalado",
     "reg": [("HKCU", r"Software\Policies\LibreOffice\org.openoffice.Office.Common\Cache\GraphicManager\GraphicMemoryLimit",
              "Value", SZ, "600000000")],
     "desc": "Dobra a memória que o LibreOffice usa para imagens e gráficos (300 MB → 600 MB). Documentos e planilhas "
             "com muitas imagens ou gráficos rolam sem recarregar. O cálculo em vários núcleos já vem ligado."},
    # ---- Rede
    {"id": "rede_descoberta", "perfis": ESC, "cat": "Rede", "nome": "Outros PCs e pastas aparecem em 'Rede'", "risco": "baixo",
     "reg": [("HKLM", SVC + r"\fdPHost", "Start", DW, 2), ("HKLM", SVC + r"\FDResPub", "Start", DW, 2),
             ("HKLM", SVC + r"\FDResPub", "DelayedAutostart", DW, 1)],
     "depois": [["sc.exe", "start", "fdPHost"], ["sc.exe", "start", "FDResPub"]],
     "desc": "Liga os serviços de descoberta que o Windows deixa parados: este PC passa a aparecer para os outros e vice-versa. "
             "Só funciona com a rede marcada como Particular (veja Saúde do PC)."},
    {"id": "unidades_admin", "perfis": ESC, "cat": "Rede", "nome": "Unidades de rede visíveis em programas de administrador",
     "risco": "baixo", "reboot": True,
     "reg": [("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "EnableLinkedConnections", DW, 1)],
     "desc": "Corrige o caso clássico: a unidade mapeada (ex.: Z:) aparece no Explorador, mas some na hora de abrir ou salvar "
             "num programa que roda como administrador (sistemas de gestão, instaladores)."},
    {"id": "impressora_padrao", "perfis": ESC, "cat": "Rede", "nome": "Windows não troca a impressora padrão sozinho",
     "risco": "baixo", "reg": [("HKCU", r"Software\Microsoft\Windows NT\CurrentVersion\Windows", "LegacyDefaultPrinterMode", DW, 1)],
     "desc": "Por padrão o Windows muda a impressora padrão para a última usada e a impressão vai parar na impressora errada. "
             "Isso fixa a que você escolher."},
    {"id": "nic_energia", "perfis": ESC, "cat": "Rede", "nome": "Placa de rede não desliga para economizar energia",
     "risco": "médio", "reboot": True, "tipo": "nic_pnp",
     "desc": "O Windows pode desligar a placa de rede/Wi-Fi para poupar energia, derrubando VPN, Área de Trabalho Remota "
             "e arquivos abertos da rede. Aplica nas placas conectadas agora. Gasta um pouco mais de bateria."},
    {"id": "vpn_dns", "perfis": ESC, "cat": "Rede", "nome": "VPN: nomes da rede da empresa resolvem pela VPN", "risco": "médio",
     "recomendado": False, "reg": [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows NT\DNSClient", "DisableSmartNameResolution", DW, 1)],
     "desc": "Com VPN ligada, o Windows pergunta os nomes a todas as redes ao mesmo tempo e às vezes usa a resposta errada "
             "('servidor não encontrado', sistema interno que não abre). Isso faz ele seguir a ordem das conexões. Só para quem usa VPN."},
    # ---- Segurança
    {"id": "extensoes", "perfis": ESC, "cat": "Segurança", "nome": "Mostrar a extensão dos arquivos", "risco": "baixo",
     "reg": [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "HideFileExt", DW, 0)],
     "desc": "Mostra 'boleto.pdf.exe' em vez de 'boleto.pdf': o golpe mais comum por e-mail fica visível. Vale nas janelas novas do Explorador."},
    {"id": "pua", "perfis": ESC, "cat": "Segurança", "nome": "Defender bloqueia programas indesejados (PUA)", "risco": "baixo",
     "tipo": "ps", "ps": {"ler": "[int](Get-MpPreference).PUAProtection", "alvo": "1", "gravar": "Set-MpPreference -PUAProtection {v}"},
     "desc": "Bloqueia instaladores com 'brindes' (barras de navegador, mineradores, adwares) que vêm junto de programas gratuitos. "
             "Não se aplica se o PC usa outro antivírus."},
    {"id": "smb1_off", "perfis": ESC, "cat": "Segurança", "nome": "Desligar SMB1 (protocolo de rede antigo)", "risco": "médio",
     "reboot": True, "tipo": "ps",
     "ps": {"ler": "[string](Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol).State", "alvo": "Disabled",
            "ok": ["Disabled", "DisabledWithPayloadRemoved"],
            "gravar": "if('{v}' -eq 'Enabled'){Enable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -All -NoRestart | Out-Null}"
                      "else{Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -NoRestart | Out-Null}"},
     "desc": "Porta usada pelo WannaCry. Atenção: NAS e impressoras multifuncionais muito antigas (escanear para pasta) podem "
             "precisar dele. Se pararem de funcionar, use Desfazer."},
    # Proteção do sistema: o programa NÃO liga nem desliga (decisão do usuário). Fica fora das telas; a Saúde do PC
    # só verifica e sugere. Mantido aqui apenas para desfazer, se alguém aplicou numa versão antiga.
    {"id": "restauracao", "perfis": (), "cat": "Segurança", "nome": "Proteção do sistema (pontos de restauração) ligada",
     "risco": "baixo", "tipo": "ps",
     "ps": {"ler": "[int](Get-CimInstance -Namespace root/default -ClassName SystemRestoreConfig).RPSessionInterval", "alvo": "1",
            "gravar": "if('{v}' -eq '1'){Enable-ComputerRestore -Drive \"$env:SystemDrive\\\"}"},
     "nao_desfaz": "a Proteção do sistema continua ligada (desligar apagaria os pontos de restauração; se quiser, desligue em "
                   "Painel de Controle > Sistema > Proteção do sistema)",
     "desc": "Sem ela, não existe 'voltar no tempo' depois de uma atualização ou instalação que deu errado. "
             "Usa até alguns GB do disco C:."},
]

CAT_ENERGIA = "Tampa, botões e tela"
AJUSTES += [
    {"id": "tampa_nada", "perfis": ("jogos", "escritorio"), "cat": CAT_ENERGIA, "nome": "Fechar a tampa não suspende nem desliga",
     "risco": "baixo", "tipo": "todos_planos", "pcs": [("SUB_BUTTONS", "LIDACTION", 0, 0)],
     "aplica_se": lambda: tem_bateria(), "requisito": "só para notebook",
     "desc": "Ao fechar ou baixar a tampa, só a tela do notebook apaga: programas, downloads, VPN, chamada e monitor externo "
             "continuam funcionando. Evita o monitor ligado em hub USB-C voltar com resolução errada depois de suspender. "
             "Vale na bateria e na tomada, em todos os planos de energia. Para suspender, use o menu Iniciar."},
    {"id": "botoes_nada", "perfis": ("jogos", "escritorio"), "cat": CAT_ENERGIA,
     "nome": "Botão de energia e de suspensão não fazem nada", "risco": "baixo", "recomendado": False,
     "tipo": "todos_planos", "pcs": [("SUB_BUTTONS", "PBUTTONACTION", 0, 0), ("SUB_BUTTONS", "SBUTTONACTION", 0, 0)],
     "desc": "Um toque sem querer no botão de energia (ou na tecla de suspender) não derruba o jogo, a chamada ou o trabalho. "
             "Para desligar, use o menu Iniciar. Se o PC travar, segurar o botão por uns 5 segundos continua desligando."},
    {"id": "tela_sempre", "perfis": ("jogos", "escritorio"), "cat": CAT_ENERGIA,
     "nome": "Tela e PC nunca apagam nem suspendem sozinhos", "risco": "baixo", "recomendado": False,
     "tipo": "todos_planos", "pcs": [("SUB_VIDEO", "VIDEOIDLE", 0, 0), ("SUB_SLEEP", "STANDBYIDLE", 0, 0)],
     "desc": "Downloads, renderizações, partidas e chamadas não são interrompidos por inatividade, nem na bateria. "
             "Gasta mais energia. A tela continua bloqueando se o Windows estiver configurado para isso; Windows + L bloqueia na hora."},
]

ORDEM_CATS = {"jogos": [CAT_ENERGIA, "Energia e CPU", "Placa de vídeo", "Agendador multimídia", "Rede", "Mouse e teclado", "Windows",
                        "Disco", "Segurança x desempenho"],
              "escritorio": [CAT_ENERGIA, "Memória e muitas abas", "Navegadores", "Excel e Office", "Rede", "Segurança", "Windows", "Disco",
                             "Mouse e teclado"]}
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
        return "ATIVO" if pa in (ULTIMATE, ALTO_DESEMPENHO) or re.search(r"Ultimate|Desempenho M[aá]ximo", nome, re.I) else "PADRÃO"
    if t == "powercfg":  # confere tomada E bateria (quando o ajuste define a bateria)
        sub, st, ac, dc = a["pc"]
        at_ac, at_dc = _pc_lidos(sub, st)
        if at_ac is None:
            return "N/A"
        certos = [at_ac == ac] + ([at_dc == dc] if dc is not None else [])
        return "ATIVO" if all(certos) else ("PARCIAL" if any(certos) else "PADRÃO")
    if t == "bcd":
        v = _bcd_get("disabledynamictick")
        return "ATIVO" if v and v.lower() in ("yes", "sim") else "PADRÃO"
    if t == "hiber":
        return "ATIVO" if REG.get("HKLM", PWR, "HibernateEnabled")[2] == 0 else "PADRÃO"
    if a.get("aplica_se") and not a["aplica_se"]():
        return "N/A"
    if t == "todos_planos":
        vals = [(_pc_lidos(sub, st, g), (ac, dc)) for g in planos() for sub, st, ac, dc in a["pcs"]]
        vals = [(v, alvo) for v, alvo in vals if v[0] is not None]
        if not vals:
            return "N/A"
        iguais = sum(1 for v, alvo in vals if v == alvo)
        return "ATIVO" if iguais == len(vals) else ("PARCIAL" if iguais else "PADRÃO")
    if t == "ps":
        v = _ps_ler(a)
        return "N/A" if v is None else ("ATIVO" if _ps_ativo(a, v) else "PADRÃO")
    regs = regs_do_ajuste(a)
    if not regs:
        return "N/A"
    iguais = sum(1 for h, p, n, tp, v in regs if REG.get(h, p, n)[2] == v)
    return "ATIVO" if iguais == len(regs) else ("PARCIAL" if iguais else "PADRÃO")


def aplicar(aid: str) -> str:
    a = POR_ID[aid]
    motivo = bloqueado(a)
    if motivo:
        raise RuntimeError(motivo)
    b = _ler_backup()
    orig = b.get(aid)  # já aplicado antes: mantém o original da primeira vez
    t = a.get("tipo")
    if t == "todos_planos":
        gs = planos()
        atuais = [(g, sub, st, ac, dc, _pc_lidos(sub, st, g)) for g in gs for sub, st, ac, dc in a["pcs"]]
        atuais = [x for x in atuais if x[5][0] is not None]
        if not atuais:
            raise RuntimeError("este PC não tem essa configuração de energia")
        if orig is None:
            orig = {"todos_planos": [[g, sub, st, v[0], v[1]] for g, sub, st, _, _, v in atuais]}
        for g, sub, st, ac, dc, _ in atuais:
            _cmd(["powercfg", "/setacvalueindex", g, sub, st, str(ac)])
            _cmd(["powercfg", "/setdcvalueindex", g, sub, st, str(dc)])
        _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
        msg = f"aplicado em {len(gs)} plano(s) de energia"
    elif t == "ps":
        v = _ps_ler(a)
        if v is None:
            raise RuntimeError("recurso não disponível neste Windows")
        if orig is None:
            orig = {"ps": v, "reg": [[h, p, n, *REG.get(h, p, n)] for h, p, n in a.get("guardar", [])]}
        if not _ps_ativo(a, v):
            _ps_gravar(a, a["ps"]["alvo"])
            for espera in (0, 1, 2, 3, 4):  # alguns recursos (ex.: compressão de memória) demoram a refletir a mudança
                time.sleep(espera)
                if _ps_ativo(a, _ps_ler(a)):
                    break
            else:
                raise RuntimeError("o Windows não aceitou a alteração")
        msg = "aplicado"
    elif t == "plano":
        if orig is None:
            orig = {"plano": plano_ativo()}
        g = _plano_maximo()
        anterior = plano_ativo()
        _herdar_preferencias(anterior, g)
        _desempenho_na_bateria(g)
        _levar_ajustes_de_energia(g, b)
        rc, out = _cmd(["powercfg", "/setactive", g])
        if rc != 0 and g != ALTO_DESEMPENHO:  # Modern Standby: tenta o Alto Desempenho
            g = ALTO_DESEMPENHO
            _herdar_preferencias(anterior, g)
            _desempenho_na_bateria(g)
            _levar_ajustes_de_energia(g, b)
            rc, out = _cmd(["powercfg", "/setactive", g])
        if rc != 0:
            raise RuntimeError("o Windows não aceitou trocar o plano de energia: " + out.strip()[:160])
        msg = "plano Desempenho Máximo ativo" if g != ALTO_DESEMPENHO else "plano Alto Desempenho ativo (Desempenho Máximo indisponível neste PC)"
    elif t == "powercfg":
        sub, st, ac, dc = a["pc"]
        ac0, dc0 = _pc_lidos(sub, st)
        if ac0 is None:
            raise RuntimeError("este PC não tem essa configuração de energia")
        if orig is None:  # valores em vigor no plano ativo, para devolver pelo próprio powercfg
            orig = {"pc": [plano_ativo(), sub, st, ac0, dc0]}
        _pc_set(sub, st, ac, dc)
        msg = "aplicado no plano de energia atual"
    elif t == "bcd":
        if bitlocker_ativo():
            raise RuntimeError("BitLocker ativo no disco C: - suspenda o BitLocker antes, ou deixe este ajuste de lado")
        if orig is None:
            orig = {"bcd": {"disabledynamictick": _bcd_get("disabledynamictick"),
                            "useplatformclock": _bcd_get("useplatformclock")}}
        rc, out = _cmd(["bcdedit", "/set", "disabledynamictick", "yes"])
        if rc != 0:
            raise RuntimeError("bcdedit recusou a alteração: " + out.strip()[:160])
        _cmd(["bcdedit", "/deletevalue", "useplatformclock"])
        msg = "configuração de boot alterada"
    elif t == "hiber":
        if orig is None:
            orig = {"hiber": REG.get("HKLM", PWR, "HibernateEnabled")[2] != 0}
        rc, out = _cmd(["powercfg", "/hibernate", "off"])
        if rc != 0:
            raise RuntimeError("powercfg recusou desligar a hibernação: " + out.strip()[:200])
        msg = "hibernação desligada (hiberfil.sys removido)"
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
    _depois(a)
    b[aid] = orig
    _salvar_backup(b)
    _marca_reinicio(a)
    return msg + (" - reinicie para valer" if a.get("reboot") else "")


def desfazer(aid: str) -> str:
    a = POR_ID[aid]
    b = _ler_backup()
    orig = b.get(aid)
    if orig is None:
        return "nada a desfazer (não foi aplicado por este programa)"
    aviso = ""
    if "ps" in orig:
        if a.get("nao_desfaz"):
            aviso = " - " + a["nao_desfaz"]
        elif not _ps_ativo(a, orig["ps"]) or orig["ps"].lower() != a["ps"]["alvo"].lower():
            _ps_gravar(a, orig["ps"])
    if "plano" in orig and orig["plano"]:
        _cmd(["powercfg", "/setactive", orig["plano"]])
    if "bcd" in orig:
        for nome, valor in orig["bcd"].items():
            _bcd_restaura(nome, valor)
    if orig.get("hiber"):  # só religa se estava ligada antes
        _cmd(["powercfg", "/hibernate", "on"])
    for g, sub, st, ac0, dc0 in orig.get("todos_planos", []):
        _cmd(["powercfg", "/setacvalueindex", g, sub, st, str(ac0)])
        _cmd(["powercfg", "/setdcvalueindex", g, sub, st, str(dc0)])
    if orig.get("todos_planos"):
        _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
    if "pc" in orig:
        plano, sub, st, ac0, dc0 = orig["pc"]
        rc, out = _cmd(["powercfg", "/setacvalueindex", plano, sub, st, str(ac0)])
        if rc != 0:
            raise RuntimeError("o Windows não aceitou devolver a configuração de energia: " + out.strip()[:160])
        _cmd(["powercfg", "/setdcvalueindex", plano, sub, st, str(dc0)])
        _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
    for h, p, n, existe, tipo, valor in orig.get("reg", []):
        m = re.search(rf"PowerSchemes\\({GUID})\\({GUID})\\({GUID})$", p, re.I)
        if m:  # backup de versão antiga (até 1.3.0) guardava a chave do plano, que o Windows não deixa regravar
            if existe:
                _cmd(["powercfg", "/setacvalueindex" if n.upper().startswith("AC") else "/setdcvalueindex", *m.groups(), str(valor)])
            continue
        if existe and tipo in TIPOS:
            REG.set(h, p, n, tipo, valor)
        else:
            REG.delete(h, p, n)
    if orig.get("recarregar_plano"):
        _cmd(["powercfg", "/setactive", "SCHEME_CURRENT"])
    _depois(a)
    del b[aid]
    _salvar_backup(b)
    _marca_reinicio(a)
    return ("restaurado ao valor original" if not aviso else "removido da lista de aplicados") + aviso + \
        (" - reinicie para valer" if a.get("reboot") else "")


# --------------------------------------------------------------------------- reinício pendente

def _arq_reinicio():
    return BACKUP.with_name("otimizacao_reinicio.json")


def ligado_desde() -> float:
    """Momento em que o Windows iniciou de verdade (com a Inicialização rápida, 'Desligar' não conta)."""
    try:
        import ctypes
        f = ctypes.windll.kernel32.GetTickCount64
        f.restype = ctypes.c_ulonglong
        return time.time() - f() / 1000
    except Exception:
        return 0.0


def _marca_reinicio(a: dict) -> None:
    if not a.get("reboot"):
        return
    try:
        d = json.loads(_arq_reinicio().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d[a["id"]] = time.time()
    try:
        _arq_reinicio().write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def aguardando_reinicio() -> set[str]:
    """Ajustes alterados por este programa depois da última inicialização: só valem ao reiniciar."""
    try:
        d = json.loads(_arq_reinicio().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    desde = ligado_desde()
    return {k for k, quando in d.items() if quando > desde}


def aplicados() -> list[str]:
    return list(_ler_backup().keys())


def do_perfil(perfil: str | None) -> list[dict]:
    """Ajustes de uma tela, na ordem das categorias dela."""
    if perfil is None:
        return list(AJUSTES)
    lista = [a for a in AJUSTES if perfil in a.get("perfis", ("jogos",))]
    ordem = ORDEM_CATS.get(perfil, [])
    return sorted(lista, key=lambda a: ordem.index(a["cat"]) if a["cat"] in ordem else len(ordem))


def listar(perfil: str | None = None) -> list[dict]:
    out = []
    pend = aguardando_reinicio()
    nossos = aplicados()
    for a in do_perfil(perfil):
        try:
            st = estado(a)
        except Exception:
            st = "N/A"
        try:
            bl = bloqueado(a)
        except Exception:
            bl = ""
        out.append({"id": a["id"], "nome": a["nome"], "cat": a["cat"], "risco": a["risco"], "estado": st,
                    "desc": a["desc"], "reboot": a.get("reboot", False), "seguranca": a.get("seguranca", False),
                    "nosso": a["id"] in nossos, "reiniciar": a["id"] in pend, "bloqueado": bl,
                    "recomendado": a.get("recomendado", True)})
    return out
