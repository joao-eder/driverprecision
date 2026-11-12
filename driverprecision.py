#!/usr/bin/env python3
"""
DriverPrecision - identifica o hardware e localiza o driver CORRETO para cada dispositivo.

Fontes, em ordem de confiança:
  1. Catálogo oficial do fabricante do computador (Lenovo, Dell, HP), filtrado pelo
     modelo exato (MT / SystemSKU / Platform ID), pelo Windows instalado e pelo Hardware ID.
  2. Windows Update (API do Windows Update Agent): drivers publicados pelo fabricante do
     dispositivo que o próprio Windows casou com o Hardware ID desta máquina.
  3. Microsoft Update Catalog, consultado pelo Hardware ID mais específico do dispositivo
     (com SUBSYS / VID&PID). Resultado só por VEN&DEV (chip genérico) NÃO é recomendado.

Só Python 3 (stdlib) + ferramentas nativas do Windows (PowerShell, expand.exe, pnputil).

Uso:
  python driverprecision.py scan                 # somente leitura: inventário + busca + relatório
  python driverprecision.py baixar ID [ID ...]   # baixa e valida hash/assinatura (não instala)
  python driverprecision.py instalar ID [ID ...] # instala (admin, confirmação, ponto de restauração)
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import datetime as dt
import fnmatch
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "1.2.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DriverPrecision/" + VERSION
BASE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DriverPrecision"
CACHE = BASE / "cache"
OUT = Path.cwd() / "DriverPrecision_saida"
STATE = OUT / "ultimo_scan.json"
SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

# Barramentos físicos (dispositivos reais). Software/ROOT só entra se estiver com erro.
PHYS_BUS = {"PCI", "USB", "HDAUDIO", "INTELAUDIO", "ACPI", "HID", "SD", "UEFI", "BTH",
            "BTHENUM", "DISPLAY", "SCSI", "NVME", "USBSTOR", "MEDIA"}
# Classes onde um driver genérico (inbox) significa perda de função/desempenho.
CLASSES_CRITICAS = {"DISPLAY", "NET", "MEDIA", "BLUETOOTH", "CAMERA", "IMAGE", "BIOMETRIC",
                    "SMARTCARDREADER", "SDHOST", "SENSOR", "MTD", "SCSIADAPTER"}
# Classes de hardware padronizadas: o driver de classe do Windows É o driver correto
# (o fabricante não publica outro). Verificado nos Hardware IDs e Compatible IDs.
CLASS_DRIVER_OK = [re.compile(p, re.I) for p in (
    r"^USB\\CLASS_", r"^USB\\COMPOSITE", r"^USB\\ROOT_HUB", r"^HID\\", r"^HID_DEVICE",
    r"^PCI\\CC_06", r"^PCI\\CC_0C03", r"^PCI\\CC_0108", r"^PCI\\CC_0106", r"^PCI\\CC_0500",
    r"^ACPI\\(VEN_)?PNP", r"^ACPI\\(VEN_)?ACPI", r"^\*PNP", r"^ACPI\\(VEN_MSFT|MSFT)",
    r"^ACPI\\(FIXEDBUTTON|THERMALZONE|GENUINEINTEL|AUTHENTICAMD)", r"^ACPI\\VEN_(GENUINEINTEL|AUTHENTICAMD)",
    r"^SCSI\\DISK", r"^USBSTOR\\", r"^DISPLAY\\", r"^MONITOR\\")]


def driver_de_classe(d: dict) -> bool:
    return any(p.match(i) for i in d["hwids"] + d["compat"] for p in CLASS_DRIVER_OK)

PRIORIDADE = {"OEM": 0, "WU": 1, "CAT": 2}

# --------------------------------------------------------------------------- utilidades


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sem janelas piscando na interface gráfica
_LOG_FN = None


def set_logger(fn) -> None:
    """A interface gráfica redireciona o log para a janela."""
    global _LOG_FN
    _LOG_FN = fn


def log(msg: str) -> None:
    if _LOG_FN:
        _LOG_FN(msg)
    elif sys.stdout:
        print(msg, flush=True)


def vtuple(v: str | None) -> tuple:
    if not v:
        return ()
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:4]]
    while nums and nums[-1] == 0 and len(nums) > 1:
        nums.pop()
    return tuple(nums)


def vcmp(a: str | None, b: str | None) -> int | None:
    ta, tb = vtuple(a), vtuple(b)
    if not ta or not tb:
        return None
    n = max(len(ta), len(tb))
    ta, tb = ta + (0,) * (n - len(ta)), tb + (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def limpa_ver(v: str | None, instalada: str | None = None) -> str:
    """Normaliza versões de catálogo: 'a^b' (faixa Lenovo) -> a; 'x/y/z' -> a de mesma família da instalada."""
    if not v:
        return ""
    partes = [p.split("^")[0].strip() for p in re.split(r"[/,;]", v) if p.strip()]
    partes = [p for p in partes if vtuple(p)]
    if not partes:
        return v
    ti = vtuple(instalada)
    if ti:
        for p in partes:
            if vtuple(p)[:1] == ti[:1]:
                return p
    return partes[0]


def http_get(url: str, timeout: int = 60, data: bytes | None = None, headers: dict | None = None) -> bytes:
    h = {"User-Agent": UA}
    h.update(headers or {})
    last = None
    for tentativa in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # rede instável: tenta de novo
            last = e
        time.sleep(1.5 * (tentativa + 1))
    raise last  # type: ignore[misc]


def cached(url: str, name: str, ttl_h: float = 24, timeout: int = 90) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if p.exists() and time.time() - p.stat().st_mtime < ttl_h * 3600:
        return p.read_bytes()
    b = http_get(url, timeout=timeout)
    p.write_bytes(b)
    return b


def expand_cab(cab: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(SYS32 / "expand.exe"), "-F:*", str(cab), str(dest)],
                   capture_output=True, check=False, creationflags=NO_WINDOW)
    return [p for p in dest.rglob("*") if p.is_file()]


def cab_xml(url: str, name: str, ttl_h: float = 24) -> bytes:
    """Baixa um .cab (com cache), extrai e devolve o XML de dentro."""
    raw = cached(url, name, ttl_h, timeout=180)
    cab = CACHE / name
    dest = CACHE / (name + "_x")
    xmlp = dest / "conteudo.xml"
    if xmlp.exists() and xmlp.stat().st_mtime >= cab.stat().st_mtime:
        return xmlp.read_bytes()
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    files = expand_cab(cab, dest)
    if not files:
        raise RuntimeError(f"não consegui extrair {name}")
    data = max(files, key=lambda p: p.stat().st_size).read_bytes()
    xmlp.write_bytes(data)
    _ = raw
    return data


def powershell(script: str, timeout: int = 600) -> str:
    pre = "$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    enc = base64.b64encode((pre + script).encode("utf-16-le")).decode()
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-EncodedCommand", enc], capture_output=True, timeout=timeout,
                       creationflags=NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode != 0 and not out:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-800:])
    return out


def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def id_match(dev_ids: list[str], pkg_id: str) -> str | None:
    """Casa um ID do pacote com os Hardware IDs do dispositivo (aceita curinga '*')."""
    pid = pkg_id.strip().upper()
    if not pid:
        return None
    for d in dev_ids:
        if d == pid or (("*" in pid or "?" in pid) and fnmatch.fnmatchcase(d, pid)):
            return d
    if "\\" not in pid:
        # Lenovo usa IDs sem barramento (ex.: VEN_10EC&DEV_0257): casa como trecho completo
        rx = re.compile(r"[\\&]" + re.escape(pid) + r"(&|$)")
        for d in dev_ids:
            if rx.search(d):
                return d
    return None


def especificidade(hwid: str) -> str:
    """'exato' = identifica o produto/placa (SUBSYS, VID&PID, ID ACPI do fabricante)."""
    u = hwid.upper()
    if u.startswith(("PCI\\", "HDAUDIO\\", "INTELAUDIO\\")):
        return "exato" if "SUBSYS_" in u else "chip"
    if u.startswith(("USB\\", "HID\\", "BTH")):
        return "exato" if (("VID_" in u and "PID_" in u) or ("VEN_" in u and "DEV_" in u)) else "chip"
    if u.startswith("ACPI\\"):
        return "chip" if re.match(r"ACPI\\(PNP|ACPI)", u) else "exato"
    return "chip"


# --------------------------------------------------------------------------- inventário

PS_INVENTARIO = r"""
$ErrorActionPreference='SilentlyContinue'
$cs=Get-CimInstance Win32_ComputerSystem; $bios=Get-CimInstance Win32_BIOS
$os=Get-CimInstance Win32_OperatingSystem; $bb=Get-CimInstance Win32_BaseBoard
$prod=Get-CimInstance Win32_ComputerSystemProduct
$cv=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$drv=@{}
Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceID } | ForEach-Object { $drv[$_.DeviceID]=$_ }
$devs=Get-CimInstance Win32_PnPEntity | ForEach-Object {
  $d=$drv[$_.DeviceID]
  [pscustomobject]@{
    id=$_.DeviceID; name=$_.Name; cls=$_.PNPClass; mfr=$_.Manufacturer
    hwids=@($_.HardwareID); compat=@($_.CompatibleID); err=[int]$_.ConfigManagerErrorCode
    present=$_.Present; ver=$d.DriverVersion
    date=$(if($d.DriverDate){$d.DriverDate.ToString('yyyy-MM-dd')}else{$null})
    provider=$d.DriverProviderName; inf=$d.InfName; signer=$d.Signer; devname=$d.DeviceName
  }
}
[pscustomobject]@{
  system=[pscustomobject]@{
    mfr=$cs.Manufacturer; model=$cs.Model; sku=$cs.SystemSKUNumber; family=$cs.SystemFamily
    version=$prod.Version; serial=$bios.SerialNumber; bios=$bios.SMBIOSBIOSVersion
    biosmajor=$bios.SystemBiosMajorVersion; biosminor=$bios.SystemBiosMinorVersion
    bbmfr=$bb.Manufacturer; bbproduct=$bb.Product
    os=$os.Caption; build=[int]$os.BuildNumber; ubr=$cv.UBR; display=$cv.DisplayVersion
    arch=$env:PROCESSOR_ARCHITECTURE; computer=$env:COMPUTERNAME
  }
  devices=@($devs)
} | ConvertTo-Json -Depth 5 -Compress
"""


def inventario() -> tuple[dict, list[dict]]:
    data = json.loads(powershell(PS_INVENTARIO))
    sysinfo = data["system"]
    devs = []
    for d in data["devices"]:
        did = d.get("id") or ""
        bus = did.split("\\")[0].upper()
        if d.get("present") is False:
            continue
        hw = [h.upper() for h in (d.get("hwids") or []) if h]
        if bus not in PHYS_BUS and not d.get("err"):
            continue
        if not hw and not d.get("err"):
            continue
        d["hwids"] = hw
        d["compat"] = [c.upper() for c in (d.get("compat") or []) if c]
        # IDs usados no casamento: Hardware IDs + Compatible IDs que ainda identificam o
        # fabricante/chip (VEN&DEV, VID&PID). IDs só de classe (PCI\CC_, USB\CLASS_) ficam fora.
        d["mids"] = hw + [c for c in d["compat"] if re.search(r"(VEN|VID)_[0-9A-Z]{3,4}", c) and c not in hw]
        d["bus"] = bus
        d["name"] = d.get("name") or d.get("devname") or did
        d["cls"] = (d.get("cls") or "").upper()
        inf = (d.get("inf") or "").lower()
        d["inbox"] = bool(inf) and not inf.startswith("oem")
        d["sem_driver"] = d.get("err") in (1, 18, 28, 31, 37, 39, 52) or not inf
        d["cands"] = []
        devs.append(d)
    return sysinfo, devs


def win_major(sysinfo: dict) -> int:
    return 11 if int(sysinfo.get("build") or 0) >= 22000 else 10


def x64(sysinfo: dict) -> bool:
    return (sysinfo.get("arch") or "").upper() in ("AMD64", "X64")


# --------------------------------------------------------------------------- fonte: Lenovo


def _txt(el, path, default=""):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else default


def fonte_lenovo(sysinfo: dict, devs: list[dict], sistema: list[dict]) -> str:
    model = (sysinfo.get("model") or "").strip().upper()
    mt = model[:4]
    if not re.fullmatch(r"[0-9A-Z]{4}", mt):
        return "modelo sem Machine Type reconhecível"
    wins = ["Win11", "Win10"] if win_major(sysinfo) == 11 else ["Win10"]
    cat = None
    for w in wins:
        try:
            cat = cached(f"https://download.lenovo.com/catalog/{mt}_{w}.xml", f"lenovo_{mt}_{w}.xml")
            osu = w
            break
        except urllib.error.HTTPError:
            continue
    if cat is None:
        return f"Lenovo não publica catálogo para MT {mt} (linha consumer?)"
    root = ET.fromstring(cat.decode("utf-8-sig", "replace").encode())
    pkgs = [(p.findtext("location"), p.findtext("category"), (p.find("checksum").text if p.find("checksum") is not None else ""))
            for p in root.findall("package")]

    def baixa(item):
        loc, catg, chk = item
        b = cached(loc, "lenovo_pkg_" + loc.rsplit("/", 1)[-1], 72)
        if chk and hashlib.sha256(b).hexdigest().lower() != chk.lower():
            CACHE.joinpath("lenovo_pkg_" + loc.rsplit("/", 1)[-1]).unlink(missing_ok=True)
            b = http_get(loc)
            if hashlib.sha256(b).hexdigest().lower() != chk.lower():
                raise RuntimeError("checksum do descritor não confere: " + loc)
        return loc, catg, b

    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda i: _safe(baixa, i), pkgs))
    bios_atual = (sysinfo.get("bios") or "").upper()
    n = 0
    for r in res:
        if not r:
            continue
        loc, catg, b = r
        try:
            p = ET.fromstring(re.sub(rb"<\?pcdDescriptor[^>]*\?>", b"", b.lstrip(b"\xef\xbb\xbf")))
        except ET.ParseError:
            continue
        pid = p.get("id")
        title = _txt(p, "Title/Desc")
        pver = p.get("version")
        rel = _txt(p, "ReleaseDate")
        base = loc.rsplit("/", 1)[0]
        inst = p.find("Files/Installer/File")
        fname = _txt(inst, "Name") if inst is not None else ""
        cand_base = {
            "cid": f"LEN:{pid}", "source": "OEM", "source_name": f"Lenovo ({mt}, {osu})",
            "title": title, "pkg_version": pver, "date": rel, "category": catg,
            "url": f"{base}/{fname}" if fname else "", "file": fname,
            "sha256": _txt(inst, "CRC").upper() if inst is not None else "",
            "size": int(_txt(inst, "Size", "0") or 0) if inst is not None else 0,
            "extract": _txt(p, "ExtractCommand"), "install": _txt(p, "Install/Cmdline"),
            "install_rc": (p.find("Install").get("rc") if p.find("Install") is not None else "0") or "0",
            "readme": f"{base}/{_txt(p, 'Files/Readme/File/Name')}" if p.find("Files/Readme/File") is not None else "",
            "kind": "firmware" if re.search(r"BIOS|Firmware", catg or "", re.I) else "driver",
        }
        # IDs de hardware do pacote e versão do driver que ele instala
        drv_ver: dict[str, str] = {}
        ids: set[str] = set()
        for drvel in p.iter("_Driver"):
            hid = _txt(drvel, "HardwareID").upper()
            if hid:
                ids.add(hid)
                drv_ver[hid] = _txt(drvel, "Version").rstrip("^")
        for pn in p.iter("_PnPID"):
            if pn.text:
                ids.add(pn.text.strip().upper())
        if not ids:
            # pacote de sistema (BIOS, firmware, utilitário): avalia pela BIOS atual
            if catg and "Software" in catg:
                continue
            levels = [lv.text.strip().upper() for lv in p.iter("Level") if lv.text]
            dep_levels = [lv.text.strip().upper() for lv in p.findall("Dependencies//_Bios/Level") if lv.text]
            det_levels = [lv.text.strip().upper() for lv in p.findall("DetectInstall//_Bios/Level") if lv.text]
            if not levels:
                continue
            aplica = any(fnmatch.fnmatchcase(bios_atual, lv) for lv in dep_levels) if dep_levels else True
            instalado = any(fnmatch.fnmatchcase(bios_atual, lv) for lv in det_levels)
            if not aplica and not instalado:
                continue
            c = dict(cand_base, version=pver, match_id="BIOS " + (sysinfo.get("bios") or ""), level="exato",
                     status="OK" if instalado or not aplica else "ATUALIZAR",
                     note="BIOS/firmware: instale manualmente, com carregador conectado")
            sistema.append(c)
            n += 1
            continue
        for d in devs:
            hits = [(h, i) for i in ids for h in [id_match(d["mids"], i)] if h]
            if not hits:
                continue
            # o ID mais específico do aparelho que o pacote cobre
            hits.sort(key=lambda x: (len(x[0]), bool(drv_ver.get(x[1]))), reverse=True)
            hit, key = hits[0]
            v = drv_ver.get(key) or next((drv_ver[i] for _, i in hits if drv_ver.get(i)), "")
            d["cands"].append(dict(cand_base, version=limpa_ver(v or pver, d.get("ver")), version_is_pkg=not v,
                                   match_id=hit, level="exato" if hit in d["hwids"] else "modelo"))
            n += 1
    return f"ok - {len(pkgs)} pacotes do modelo, {n} associações"


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log(f"   aviso: {e}")
        return None


# --------------------------------------------------------------------------- fonte: Dell

DELL_OS = {11: ("W21P4", "W11TM"), 10: ("W10P4", "WT64A")}


def fonte_dell(sysinfo: dict, devs: list[dict], sistema: list[dict]) -> str:
    sku = (sysinfo.get("sku") or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{4}", sku):
        return f"SystemSKU '{sku}' não é um System ID Dell"
    xml = cab_xml("https://downloads.dell.com/catalog/CatalogPC.cab", "dell_CatalogPC.cab", 24)
    root = ET.fromstring(xml)
    oscodes = DELL_OS[win_major(sysinfo)]
    n = tot = 0
    bios_atual = sysinfo.get("bios") or ""
    for sc in root.iter("SoftwareComponent"):
        if not any((m.get("systemID") or "").upper() == sku for m in sc.iter("Model")):
            continue
        if not any(o.get("osCode") in oscodes for o in sc.iter("OperatingSystem")):
            continue
        ctype = sc.find("ComponentType").get("value") if sc.find("ComponentType") is not None else ""
        if ctype not in ("DRVR", "BIOS", "FRMW"):
            continue
        tot += 1
        name = (sc.findtext("Name/Display") or "").strip()
        catg = (sc.findtext("Category/Display") or "").strip()
        rel = sc.get("releaseDate") or ""
        try:
            rel = dt.datetime.strptime(rel, "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
        path = sc.get("path") or ""
        cand_base = {
            "cid": f"DELL:{sc.get('releaseID')}", "source": "OEM", "source_name": f"Dell (SKU {sku})",
            "title": name, "pkg_version": f"{sc.get('vendorVersion')} ({sc.get('dellVersion')})",
            "version": sc.get("vendorVersion"), "date": rel, "category": catg,
            "url": f"https://downloads.dell.com/{path}", "file": path.rsplit("/", 1)[-1],
            "md5": (sc.get("hashMD5") or "").upper(), "size": int(sc.get("size") or 0),
            "kind": "firmware" if ctype in ("BIOS", "FRMW") else "driver",
            "readme": (sc.find("ImportantInfo").get("URL") if sc.find("ImportantInfo") is not None else ""),
        }
        pcis = []
        for pi in sc.iter("PCIInfo"):
            ven, dev = (pi.get("vendorID") or "").upper(), (pi.get("deviceID") or "").upper()
            sv, sd = (pi.get("subVendorID") or "").upper(), (pi.get("subDeviceID") or "").upper()
            if ven and dev:
                pcis.append(f"PCI\\VEN_{ven}&DEV_{dev}" + (f"&SUBSYS_{sd}{sv}" if sv and sd else ""))
        if ctype == "BIOS":
            cmpv = vcmp(sc.get("vendorVersion"), bios_atual)
            sistema.append(dict(cand_base, match_id="BIOS " + bios_atual, level="exato",
                                status="ATUALIZAR" if cmpv and cmpv > 0 else "OK",
                                note="BIOS: instale manualmente, com carregador conectado"))
            n += 1
            continue
        casou = False
        for d in devs:
            for pid in pcis:
                hit = id_match(d["mids"], pid)
                if hit:
                    d["cands"].append(dict(cand_base, match_id=hit, level="exato" if "SUBSYS" in pid else "modelo"))
                    casou = True
                    n += 1
                    break
        if not casou and not pcis:
            # Dell não informa HWID para este pacote: aplicável ao modelo, conferir pelo nome
            sistema.append(dict(cand_base, match_id=f"modelo {sku}", level="modelo", status="VERIFICAR",
                                note="Dell não publica Hardware ID deste pacote; compare pelo nome"))
    return f"ok - {tot} pacotes para o SKU {sku}, {n} associações"


# --------------------------------------------------------------------------- fonte: HP


def fonte_hp(sysinfo: dict, devs: list[dict], sistema: list[dict]) -> str:
    plat = (sysinfo.get("bbproduct") or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{4}", plat):
        return f"BaseBoard '{plat}' não é um Platform ID HP"
    pl = cab_xml("https://hpia.hpcloud.hp.com/ref/platformList.cab", "hp_platformList.cab", 72)
    root = ET.fromstring(pl)
    alvo = None
    for p in root.iter("Platform"):
        ids = [s.strip().upper() for s in (p.findtext("SystemID") or "").split(",")]
        if plat in ids:
            alvo = p
            break
    if alvo is None:
        return f"Platform ID {plat} não consta na lista da HP"
    w11 = win_major(sysinfo) == 11
    disp = (sysinfo.get("display") or "").upper()
    oss = []
    for o in alvo.findall("OS"):
        if (o.findtext("IsWindows11") == "true") != w11 or o.findtext("OSArchitecture") != "64":
            continue
        oss.append(((o.findtext("OSReleaseIdDisplay") or "").upper() == disp, int(o.findtext("OSBuildId") or 0),
                    o.findtext("OSVersion"), o.findtext("OSReleaseIdFilename")))
    if not oss:
        return f"HP não tem referência de Windows {11 if w11 else 10} para {plat}"
    oss.sort(reverse=True)
    pl_low = plat.lower()
    ref = None
    # a lista da HP às vezes cita versões cujo arquivo de referência não existe: tenta em ordem
    for _, _, osv, rid in oss:
        for r_ in dict.fromkeys([rid, (rid or "").lower(), (rid or "").upper()]):
            url = f"https://hpia.hpcloud.hp.com/ref/{pl_low}/{pl_low}_64_{osv}.{r_}.cab"
            try:
                ref = ET.fromstring(cab_xml(url, f"hp_{pl_low}_{osv}.{r_}.cab", 24))
                rid = r_
                break
            except urllib.error.HTTPError:
                continue
        if ref is not None:
            break
    if ref is None:
        return f"HP não publica arquivo de referência para {plat} neste Windows"
    sp = {}
    for ui in ref.findall("Solutions/UpdateInfo"):
        sp[ui.findtext("Id")] = ui
    modelo = alvo.findtext("ProductName") or plat
    n = 0
    vistos = set()
    bios_atual = sysinfo.get("bios") or ""

    def cand(ui, spid):
        catg = ui.findtext("Category") or ""
        return {
            "cid": f"HP:{spid}", "source": "OEM", "source_name": f"HP ({modelo}, {osv}.{rid})",
            "title": ui.findtext("Name"), "pkg_version": ui.findtext("Version"),
            "version": ui.findtext("Version"), "version_is_pkg": True, "date": ui.findtext("DateReleased"),
            "category": catg, "url": "https://" + (ui.findtext("Url") or "").split("://")[-1],
            "file": (ui.findtext("Url") or "").rsplit("/", 1)[-1], "sha256": (ui.findtext("SHA256") or "").upper(),
            "size": int(ui.findtext("Size") or 0),
            "readme": "https://" + (ui.findtext("ReleaseNotesUrl") or "").split("://")[-1],
            "kind": "firmware" if re.search(r"BIOS|Firmware", catg, re.I) else "driver",
        }

    for dv in ref.iter("Device"):
        hid = (dv.findtext("HardwareId") or "").strip().upper()
        if not hid:  # algumas referências só trazem DeviceId (ID + instância)
            hid = "\\".join((dv.findtext("DeviceId") or "").strip().upper().split("\\")[:2])
        refs = [u.get("IdRef") for u in dv.findall("Solutions/UpdateInfo")]
        if not hid or not refs:
            continue
        for d in devs:
            hit = id_match(d["mids"], hid)
            if not hit:
                continue
            for r in refs:
                if r in sp and (d["id"], r) not in vistos:
                    vistos.add((d["id"], r))
                    d["cands"].append(dict(cand(sp[r], r), match_id=hit, level=especificidade(hit)))
                    n += 1
    for spid, ui in sp.items():
        if re.search(r"^BIOS", ui.findtext("Category") or "", re.I):
            c = cand(ui, spid)
            cmpv = vcmp(c["version"], re.sub(r"^.*?Ver\.?\s*", "", bios_atual))
            sistema.append(dict(c, match_id="BIOS " + bios_atual, level="exato",
                                status="ATUALIZAR" if cmpv and cmpv > 0 else "OK",
                                note="BIOS: instale manualmente, com carregador conectado"))
    return f"ok - {len(sp)} softpaqs na referência {osv}.{rid}, {n} associações"


# --------------------------------------------------------------------------- fonte: Windows Update

PS_WU = r"""
$ErrorActionPreference='Stop'
$s=New-Object -ComObject Microsoft.Update.Session
$q=$s.CreateUpdateSearcher()
$mu=(New-Object -ComObject Microsoft.Update.ServiceManager).Services | Where-Object { $_.ServiceID -eq '7971f918-a847-4430-9279-4a52d1efe18d' }
if($mu){ $q.ServerSelection=3; $q.ServiceID=$mu.ServiceID }
$r=$q.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
@($r.Updates | ForEach-Object {
  [pscustomobject]@{ id=$_.Identity.UpdateID; title=$_.Title; hwid=$_.DriverHardwareID
    mfr=$_.DriverManufacturer; provider=$_.DriverProvider; model=$_.DriverModel; cls=$_.DriverClass
    date=$(if($_.DriverVerDate){$_.DriverVerDate.ToString('yyyy-MM-dd')}else{$null})
    size=[int64]$_.MaxDownloadSize }
}) | ConvertTo-Json -Depth 3 -Compress
"""


def fonte_wu(sysinfo: dict, devs: list[dict]) -> str:
    out = powershell(PS_WU, timeout=900)
    if not out:
        return "ok - nenhum driver pendente"
    itens = json.loads(out)
    if isinstance(itens, dict):
        itens = [itens]
    n = 0
    for u in itens:
        hid = (u.get("hwid") or "").upper()
        prov = (u.get("provider") or u.get("mfr") or "")
        vm = re.findall(r"\d+(?:\.\d+){2,3}", u.get("title") or "")
        for d in devs:
            hit = id_match(d["mids"], hid)
            if hit:
                d["cands"].append({
                    "cid": f"WU:{u['id']}", "source": "WU", "source_name": "Windows Update",
                    "title": u.get("title"), "version": vm[-1] if vm else "", "date": u.get("date"),
                    "provider": prov, "match_id": hit, "level": especificidade(hit),
                    "size": u.get("size") or 0, "kind": "driver", "category": u.get("cls"),
                    "url": f"https://www.catalog.update.microsoft.com/Search.aspx?q={urllib.parse.quote(hid)}",
                })
                n += 1
    return f"ok - {len(itens)} drivers oferecidos, {n} associados a dispositivos"


# --------------------------------------------------------------------------- fonte: MS Update Catalog

CAT_SEARCH = "https://www.catalog.update.microsoft.com/Search.aspx?q="
ROW = re.compile(r'<tr id="([0-9a-f-]{36})_R\d+".*?</tr>', re.S | re.I)


def _cell(row: str, uid: str, c: int) -> str:
    m = re.search(rf'id="{uid}_C{c}_R\d+"[^>]*>(.*?)</td>', row, re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def catalogo_busca(q: str) -> list[dict]:
    key = hashlib.sha1(q.encode()).hexdigest()[:16]
    b = cached(CAT_SEARCH + urllib.parse.quote(q), f"mucat_{key}.html", 24, timeout=45)
    t = b.decode("utf-8", "replace")
    rows = []
    for m in ROW.finditer(t):
        uid, row = m.group(1), m.group(0)
        size = re.search(rf'id="{uid}_originalSize">(\d+)<', row)
        rows.append({"id": uid, "title": re.sub(r"\s+", " ", _cell(row, uid, 1)),
                     "products": re.sub(r"\s+", " ", _cell(row, uid, 2)), "classif": _cell(row, uid, 3),
                     "date": _cell(row, uid, 4), "version": _cell(row, uid, 5),
                     "size": int(size.group(1)) if size else 0})
    return rows


def catalogo_detalhe(uid: str) -> dict:
    """Página oficial do update: lista 'Supported Hardware IDs', provedor e versão reais."""
    b = cached(f"https://www.catalog.update.microsoft.com/ScopedViewInline.aspx?updateid={uid}",
               f"mucat_det_{uid}.html", 24 * 7, timeout=45)
    t = b.decode("utf-8", "replace")
    hw = set()
    i = t.find('id="driverhwIDs"')
    if i >= 0:
        j = t.find("</div>\r\n            </div>", i)
        bloco = t[i:j if j > 0 else i + 2_000_000]
        hw = {html.unescape(x).strip().upper() for x in re.findall(r'<div style="padding-bottom: 0.3em;">\s*(.*?)\s*</div>', bloco, re.S)}
    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))

    def campo(rot):
        m = re.search(rot + r":\s*(.*?)\s+(?:Driver |Version|More information|Support Url|Company)", txt)
        return m.group(1).strip() if m else ""
    ver = re.search(r"Driver Provider:.*?Version:\s*(\S+)", txt)
    return {"hwids": hw, "provider": campo("Driver Provider"), "manufacturer": campo("Driver Manufacturer"),
            "model": campo("Driver Model"), "version": ver.group(1) if ver else ""}


def _alvo_catalogo(d: dict) -> bool:
    if d["bus"] not in {"PCI", "USB", "HDAUDIO", "INTELAUDIO", "ACPI", "BTH", "SD", "HID"}:
        return False
    if d["sem_driver"]:
        return True
    if any(c["source"] == "OEM" for c in d["cands"]):
        return False
    if d["inbox"] and driver_de_classe(d):
        return False
    return not d["inbox"] or d["cls"] in CLASSES_CRITICAS or d["bus"] in ("PCI", "ACPI", "HDAUDIO", "INTELAUDIO")


def fonte_catalogo(sysinfo: dict, devs: list[dict], limite: int = 150) -> str:
    alvo = [d for d in devs if _alvo_catalogo(d)]
    w = win_major(sysinfo)
    stats = {"buscas": 0, "rejeitados": 0, "aceitos": 0}

    def busca_dev(d):
        tentados = 0
        meus = set(d["hwids"])
        for hid in d["hwids"]:
            if tentados >= 3 or stats["buscas"] >= limite:
                break
            if hid.count("&") == 0 and d["bus"] in ("PCI", "HDAUDIO", "INTELAUDIO"):
                break
            tentados += 1
            stats["buscas"] += 1
            rows = _safe(catalogo_busca, hid) or []
            ok = []
            for r in rows:
                txt = (r["title"] + " " + r["products"]).upper()
                if x64(sysinfo) and "ARM64" in txt and "X64" not in txt and "AMD64" not in txt:
                    continue
                if f"WINDOWS {w}" in txt:
                    r["os_score"] = 2
                elif "WINDOWS 10" in txt or "WINDOWS 11" in txt:
                    r["os_score"] = 1
                else:
                    continue
                if not vtuple(r["version"]) or r["version"].lower() == "n/a":
                    vm = re.findall(r"\d+(?:\.\d+){2,3}", r["title"])
                    r["version"] = vm[-1] if vm else ""
                ok.append(r)
            ok.sort(key=lambda r: (r["os_score"], vtuple(r["version"])), reverse=True)
            aceitos = 0
            for r in ok[:6]:
                det = _safe(catalogo_detalhe, r["id"])
                if not det:
                    continue
                # a busca do Catalog é textual: só aceita se o Hardware ID do aparelho
                # estiver literalmente na lista oficial do pacote
                casados = [h for h in d["mids"] if h in det["hwids"]] if det["hwids"] else []
                if not casados or re.fullmatch(r"microsoft( corporation)?", det["provider"], re.I):
                    stats["rejeitados"] += 1
                    continue
                m = casados[0]
                aceitos += 1
                stats["aceitos"] += 1
                d["cands"].append({
                    "cid": f"CAT:{r['id']}", "source": "CAT", "source_name": "Microsoft Update Catalog",
                    "title": r["title"], "version": det["version"] or r["version"], "date": r["date"],
                    "size": r["size"], "match_id": m, "level": especificidade(m), "kind": "driver",
                    "category": r["classif"], "products": r["products"], "uid": r["id"],
                    "provider": det["provider"], "model": det["model"],
                    "url": f"https://www.catalog.update.microsoft.com/ScopedViewInline.aspx?updateid={r['id']}",
                })
                if aceitos >= 2:
                    break
            if aceitos:
                return
        _ = meus

    with cf.ThreadPoolExecutor(6) as ex:
        list(ex.map(busca_dev, alvo))
    return (f"ok - {len(alvo)} dispositivos, {stats['buscas']} buscas; {stats['aceitos']} pacotes confirmados "
            f"pela lista oficial de Hardware IDs, {stats['rejeitados']} rejeitados (ID não confere ou genérico Microsoft)")


# --------------------------------------------------------------------------- análise


def avaliar(d: dict) -> None:
    validos = [c for c in d["cands"] if c["source"] != "CAT" or c["level"] == "exato"]
    # nada de genérico: drivers Microsoft só valem quando são o próprio driver de classe
    validos = [c for c in validos if not (c["source"] == "WU" and re.fullmatch(r"microsoft", c.get("provider") or "", re.I))]
    validos.sort(key=lambda c: (PRIORIDADE[c["source"]], 0 if c["level"] == "exato" else 1,
                                tuple(-x for x in vtuple(c.get("version")))))
    d["melhor"] = validos[0] if validos else None
    d["alternativas"] = [c for c in d["cands"] if c is not d["melhor"]]
    atual = d.get("ver")
    b = d["melhor"]
    if d["sem_driver"]:
        d["status"] = "INSTALAR" if b else "SEM DRIVER"
        d["motivo"] = f"erro {d.get('err')} no Gerenciador de Dispositivos" if d.get("err") else "sem driver instalado"
        if d["bus"] in ("ROOT", "SWD") and not b:
            d["motivo"] += " - componente de software do Windows (não é hardware); resolve por Windows Update/Recursos opcionais"
    elif b is None:
        if d["inbox"] and d["cls"] in CLASSES_CRITICAS and not driver_de_classe(d):
            d["status"] = "GENÉRICO"
            d["motivo"] = "driver inbox da Microsoft e nenhuma fonte publica driver específico para este Hardware ID"
        else:
            d["status"] = "OK"
            d["motivo"] = "driver de classe do Windows (correto para este tipo de dispositivo)" if d["inbox"] else "nenhuma versão mais nova nas fontes"
    else:
        c = vcmp(b.get("version"), atual)
        if d["inbox"]:
            d["status"] = "SUBSTITUIR"
            d["motivo"] = "driver genérico (inbox) em uso; existe driver específico para este hardware"
        elif c is None:
            d["status"] = "VERIFICAR"
            d["motivo"] = "fonte não informa versão comparável"
        elif c > 0 and b.get("version_is_pkg"):
            d["status"] = "VERIFICAR"
            d["motivo"] = (f"fabricante informa só a versão do pacote ({b.get('version')}), não a do driver "
                           f"({atual}); confira nas notas antes de instalar")
        elif c > 0:
            d["status"] = "ATUALIZAR"
            d["motivo"] = f"{atual} → {b.get('version')}"
        else:
            d["status"] = "OK"
            d["motivo"] = "instalado é igual ou mais novo que o da fonte"
    # alternativa mais nova não validada pelo OEM
    if b and b["source"] == "OEM":
        mais_novo = [a for a in d["alternativas"] if a["source"] != "OEM" and a.get("level") == "exato"
                     and vcmp(a.get("version"), b.get("version")) == 1]
        d["alt_nova"] = max(mais_novo, key=lambda a: vtuple(a.get("version")), default=None)


ORDEM = {"SEM DRIVER": 0, "INSTALAR": 1, "SUBSTITUIR": 2, "ATUALIZAR": 3, "GENÉRICO": 4, "VERIFICAR": 5, "OK": 6}


def fabricante(sysinfo: dict) -> str:
    m = (sysinfo.get("mfr") or "").upper()
    if "LENOVO" in m:
        return "lenovo"
    if "DELL" in m or "ALIENWARE" in m:
        return "dell"
    if m.startswith("HP") or "HEWLETT" in m:
        return "hp"
    return ""


def links_oem(sysinfo: dict) -> list[tuple[str, str]]:
    f = fabricante(sysinfo)
    links = []
    if f == "lenovo":
        links.append(("Suporte Lenovo do modelo", f"https://pcsupport.lenovo.com/products/{(sysinfo.get('model') or '')[:4]}/downloads"))
    elif f == "dell":
        links.append(("Suporte Dell (pela etiqueta)", "https://www.dell.com/support/home/product-support/servicetag/"
                      + urllib.parse.quote((sysinfo.get("serial") or "").strip()) + "/drivers"))
    elif f == "hp":
        links.append(("Suporte HP", "https://support.hp.com/drivers"))
    else:
        bb = f"{sysinfo.get('bbmfr') or ''} {sysinfo.get('bbproduct') or ''}".strip()
        if bb:
            links.append((f"Placa-mãe: {bb} (busque no site do fabricante da placa)",
                          "https://www.google.com/search?q=" + urllib.parse.quote(bb + " drivers support")))
    return links


def scan(args) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log("[1/5] Lendo hardware (WMI/PnP)...")
    sysinfo, devs = inventario()
    log(f"      {sysinfo.get('mfr')} {sysinfo.get('model')} | SKU {sysinfo.get('sku')} | placa {sysinfo.get('bbproduct')}"
        f" | BIOS {sysinfo.get('bios')} | {sysinfo.get('os')} build {sysinfo.get('build')}.{sysinfo.get('ubr')}")
    log(f"      {len(devs)} dispositivos físicos")
    fontes = {}
    sistema: list[dict] = []
    f = fabricante(sysinfo)
    log("[2/5] Catálogo oficial do fabricante...")
    if f and not args.sem_oem:
        fn = {"lenovo": fonte_lenovo, "dell": fonte_dell, "hp": fonte_hp}[f]
        try:
            fontes["OEM " + f.upper()] = fn(sysinfo, devs, sistema)
        except Exception as e:
            fontes["OEM " + f.upper()] = f"falhou: {e}"
    else:
        fontes["OEM"] = "fabricante sem catálogo público (PC montado ou marca não suportada) - usando WU e Catálogo por Hardware ID"
    log("      " + list(fontes.values())[-1])
    log("[3/5] Windows Update (só busca, nada é instalado)...")
    if not args.sem_wu:
        try:
            fontes["Windows Update"] = fonte_wu(sysinfo, devs)
        except Exception as e:
            fontes["Windows Update"] = f"falhou: {str(e)[:200]}"
        log("      " + fontes["Windows Update"])
    log("[4/5] Microsoft Update Catalog por Hardware ID...")
    if not args.sem_catalogo:
        try:
            fontes["MS Update Catalog"] = fonte_catalogo(sysinfo, devs)
        except Exception as e:
            fontes["MS Update Catalog"] = f"falhou: {e}"
        log("      " + fontes["MS Update Catalog"])
    log("[5/5] Analisando...")
    for d in devs:
        avaliar(d)
    devs.sort(key=lambda d: (ORDEM[d["status"]], d["cls"], d["name"]))
    estado = {"gerado": dt.datetime.now().isoformat(timespec="seconds"), "versao": VERSION, "system": sysinfo,
              "fontes": fontes, "devices": devs, "sistema": sistema, "links": links_oem(sysinfo),
              "duracao_s": round(time.time() - t0, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    rel = OUT / f"relatorio_{(sysinfo.get('computer') or 'pc')}_{dt.datetime.now():%Y%m%d_%H%M}.html"
    estado["relatorio"] = str(rel)
    STATE.write_text(json.dumps(estado, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    rel.write_text(relatorio_html(estado), encoding="utf-8")
    resumo_console(estado)
    log(f"\nRelatório: {rel}\nEstado:    {STATE}")
    if not args.nao_abrir:
        os.startfile(rel)  # type: ignore[attr-defined]
    return estado


def resumo_console(e: dict) -> None:
    cont: dict[str, int] = {}
    for d in e["devices"]:
        cont[d["status"]] = cont.get(d["status"], 0) + 1
    log("\nResumo: " + " | ".join(f"{k}: {v}" for k, v in sorted(cont.items(), key=lambda x: ORDEM[x[0]])))
    acao = [d for d in e["devices"] if d["status"] in ("SEM DRIVER", "INSTALAR", "SUBSTITUIR", "ATUALIZAR", "GENÉRICO")]
    for d in acao:
        b = d.get("melhor")
        log(f"  [{d['status']:<10}] {d['name'][:55]:<55} {d.get('ver') or '-':>16} -> "
            f"{(b or {}).get('version') or '-':<16} {(b or {}).get('cid', '')}")
    for s in e["sistema"]:
        if s.get("status") == "ATUALIZAR":
            log(f"  [FIRMWARE  ] {s['title'][:55]:<55} -> {s.get('version')}  {s['cid']}")


# --------------------------------------------------------------------------- relatório HTML


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def relatorio_html(e: dict) -> str:
    s = e["system"]
    cont: dict[str, int] = {}
    for d in e["devices"]:
        cont[d["status"]] = cont.get(d["status"], 0) + 1
    cards = "".join(f'<div class="card st-{_e(k).replace(" ", "")}"><b>{v}</b><span>{_e(k)}</span></div>'
                    for k, v in sorted(cont.items(), key=lambda x: ORDEM[x[0]]))
    fontes = "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in e["fontes"].items())
    links = "".join(f'<li><a href="{_e(u)}" target="_blank" rel="noopener">{_e(t)}</a></li>' for t, u in e["links"])

    def cand_html(c, principal=False):
        if not c:
            return '<span class="mut">—</span>'
        lvl = {"exato": "HWID exato", "modelo": "modelo", "chip": "só chip"}.get(c.get("level"), c.get("level"))
        link = f' <a href="{_e(c.get("url"))}" target="_blank" rel="noopener">abrir</a>' if c.get("url") else ""
        return (f'<div class="{"best" if principal else "alt"}"><span class="src src-{_e(c["source"])}">{_e(c["source_name"])}</span> '
                f'<b>{_e(c.get("version") or c.get("pkg_version") or "?")}</b> <span class="mut">{_e(c.get("date"))} · {_e(lvl)}</span><br>'
                f'{_e(c.get("title"))}{link}<br><code>{_e(c["cid"])}</code></div>')

    linhas = []
    for d in e["devices"]:
        alts = d.get("alternativas") or []
        alt_html = "".join(cand_html(a) for a in alts[:4])
        extra = ""
        if d.get("alt_nova"):
            extra = f'<div class="warn">Há versão mais nova fora do OEM ({_e(d["alt_nova"]["version"])}), não validada pelo fabricante do PC.</div>'
        linhas.append(
            f'<tr class="row st-{_e(d["status"]).replace(" ", "")}" data-st="{_e(d["status"])}">'
            f'<td><span class="pill st-{_e(d["status"]).replace(" ", "")}">{_e(d["status"])}</span></td>'
            f'<td><b>{_e(d["name"])}</b><br><span class="mut">{_e(d["cls"])} · {_e(d.get("mfr"))}</span>'
            f'<details><summary>Hardware IDs</summary><code>{"<br>".join(_e(h) for h in d["hwids"][:6])}</code></details></td>'
            f'<td>{_e(d.get("ver") or "—")}<br><span class="mut">{_e(d.get("date"))} · {_e(d.get("provider"))}<br>{_e(d.get("inf"))}'
            f'{" (inbox)" if d.get("inbox") else ""}</span></td>'
            f'<td>{cand_html(d.get("melhor"), True)}{extra}'
            f'{"<details><summary>" + str(len(alts)) + " outras fontes</summary>" + alt_html + "</details>" if alts else ""}</td>'
            f'<td class="mut">{_e(d.get("motivo"))}</td></tr>')
    sist = "".join(
        f'<tr><td><span class="pill st-{_e(x.get("status"))}">{_e(x.get("status"))}</span></td><td>{_e(x["title"])}<br>'
        f'<span class="mut">{_e(x.get("category"))}</span></td><td>{_e(x.get("version") or x.get("pkg_version"))}<br>'
        f'<span class="mut">{_e(x.get("date"))}</span></td><td><a href="{_e(x.get("url"))}" target="_blank" rel="noopener">pacote</a>'
        f'{" · <a href=" + chr(34) + _e(x.get("readme")) + chr(34) + " target=_blank rel=noopener>notas</a>" if x.get("readme") else ""}'
        f'<br><code>{_e(x["cid"])}</code></td><td class="mut">{_e(x.get("note"))}</td></tr>'
        for x in e["sistema"])
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Drivers - {_e(s.get('computer'))}</title>
<style>
:root{{--bg:#f6f7f9;--fg:#1b1f24;--mut:#667085;--card:#fff;--line:#e3e6ea;--acc:#2457d6;
--red:#c62828;--ora:#d9730d;--yel:#a67c00;--grn:#2e7d32;--blu:#2457d6;--gry:#667085}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121417;--fg:#e7e9ec;--mut:#98a2b3;--card:#1b1e22;--line:#2b3036;
--acc:#7aa2ff;--red:#ef6b6b;--ora:#f2994a;--yel:#e2c044;--grn:#5cc971;--blu:#7aa2ff;--gry:#98a2b3}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 "Segoe UI",system-ui,sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:20px 16px}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:28px 0 8px}}
.mut{{color:var(--mut);font-size:12px}}code{{font:11px Consolas,monospace;word-break:break-all}}a{{color:var(--acc)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}
.box ul{{margin:4px 0;padding-left:18px}}.cards{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--gry);border-radius:8px;padding:8px 14px;cursor:pointer;min-width:110px}}
.card b{{display:block;font-size:22px}}.card span{{font-size:12px;color:var(--mut)}}
.tw{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;min-width:900px}}th,td{{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}}
th{{font-size:12px;color:var(--mut);font-weight:600}}.pill{{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;border:1px solid currentColor;white-space:nowrap}}
.st-SEMDRIVER{{color:var(--red);border-left-color:var(--red)}}.st-INSTALAR{{color:var(--red);border-left-color:var(--red)}}
.st-SUBSTITUIR{{color:var(--ora);border-left-color:var(--ora)}}.st-ATUALIZAR{{color:var(--blu);border-left-color:var(--blu)}}
.st-GENÉRICO{{color:var(--yel);border-left-color:var(--yel)}}.st-VERIFICAR{{color:var(--yel);border-left-color:var(--yel)}}
.st-OK{{color:var(--grn);border-left-color:var(--grn)}}tr.row{{color:var(--fg)}}
.src{{font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;background:var(--bg);border:1px solid var(--line)}}
.best{{margin-bottom:4px}}.alt{{border-top:1px dashed var(--line);padding-top:4px;margin-top:4px;font-size:12px}}
.warn{{font-size:12px;color:var(--ora);margin-top:4px}}details summary{{cursor:pointer;font-size:12px;color:var(--mut)}}
.flt{{margin:8px 0}}.flt label{{margin-right:12px;font-size:13px}}
</style></head><body><main>
<h1>Relatório de drivers — {_e(s.get('mfr'))} {_e(s.get('model'))}</h1>
<div class="mut">Gerado em {_e(e['gerado'])} · DriverPrecision {_e(e['versao'])} · {e['duracao_s']} s</div>
<div class="grid" style="margin-top:14px">
<div class="box"><b>Sistema</b><ul><li>Fabricante/Modelo: {_e(s.get('mfr'))} {_e(s.get('model'))}</li>
<li>SKU: {_e(s.get('sku'))} · Família: {_e(s.get('family'))} {_e(s.get('version'))}</li>
<li>Placa-mãe: {_e(s.get('bbmfr'))} {_e(s.get('bbproduct'))}</li><li>BIOS: {_e(s.get('bios'))}</li>
<li>{_e(s.get('os'))} {_e(s.get('display'))} · build {_e(s.get('build'))}.{_e(s.get('ubr'))} · {_e(s.get('arch'))}</li></ul></div>
<div class="box"><b>Fontes consultadas</b><ul>{fontes}</ul></div>
<div class="box"><b>Suporte do fabricante</b><ul>{links or '<li class="mut">—</li>'}</ul>
<div class="mut">Prioridade: catálogo do fabricante do PC → Windows Update → MS Catalog (só HWID exato).</div></div>
</div>
<div class="cards">{cards}</div>
<div class="flt"><label><input type="checkbox" id="soAcao" checked> mostrar só o que exige ação</label></div>
<h2>Dispositivos</h2>
<div class="tw"><table><thead><tr><th>Status</th><th>Dispositivo</th><th>Instalado</th><th>Driver correto encontrado</th><th>Motivo</th></tr></thead>
<tbody id="tb">{''.join(linhas)}</tbody></table></div>
<h2>BIOS, firmware e pacotes do modelo sem Hardware ID</h2>
<div class="tw"><table><thead><tr><th>Status</th><th>Pacote</th><th>Versão</th><th>Download</th><th>Obs.</th></tr></thead>
<tbody>{sist or '<tr><td colspan=5 class="mut">Nenhum.</td></tr>'}</tbody></table></div>
<p class="mut">Baixar e validar: <code>python driverprecision.py baixar &lt;ID&gt;</code> · Instalar: <code>python driverprecision.py instalar &lt;ID&gt;</code> (admin).</p>
</main><script>
const cb=document.getElementById('soAcao');
function f(){{document.querySelectorAll('#tb tr').forEach(r=>{{r.style.display=(cb.checked&&r.dataset.st==='OK')?'none':''}})}}
cb.addEventListener('change',f);f();
document.querySelectorAll('.card').forEach(c=>c.addEventListener('click',()=>{{const st=c.querySelector('span').textContent;
cb.checked=false;document.querySelectorAll('#tb tr').forEach(r=>{{r.style.display=r.dataset.st===st?'':'none'}})}}));
</script></body></html>"""


# --------------------------------------------------------------------------- baixar / instalar


def carregar_estado() -> dict:
    if not STATE.exists():
        sys.exit("Rode 'scan' primeiro (não há ultimo_scan.json nesta pasta).")
    return json.loads(STATE.read_text(encoding="utf-8"))


def achar_cands(e: dict, ids: list[str]) -> list[dict]:
    todos = {}
    for d in e["devices"]:
        for c in d["cands"]:
            todos.setdefault(c["cid"].upper(), c)
    for c in e["sistema"]:
        todos.setdefault(c["cid"].upper(), c)
    out = []
    for i in ids:
        c = todos.get(i.upper())
        if not c:
            sys.exit(f"ID não encontrado no último scan: {i}")
        out.append(c)
    return out


def assinatura(p: Path) -> tuple[str, str]:
    ps = (f"$s=Get-AuthenticodeSignature -LiteralPath '{str(p).replace(chr(39), chr(39) * 2)}';"
          "[pscustomobject]@{st=[string]$s.Status;sub=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress")
    r = json.loads(powershell(ps, 120))
    return r.get("st") or "", r.get("sub") or ""


def url_download_catalogo(uid: str) -> str:
    body = urllib.parse.urlencode({"updateIDs": json.dumps([{"size": 0, "languages": "", "uidInfo": uid, "updateID": uid}])}).encode()
    t = http_get("https://www.catalog.update.microsoft.com/DownloadDialog.aspx", data=body,
                 headers={"Content-Type": "application/x-www-form-urlencoded"}).decode("utf-8", "replace")
    urls = re.findall(r"\.url\s*=\s*'([^']+)'", t)
    if not urls:
        raise RuntimeError("Catálogo não retornou link de download")
    return urls[0]


def baixar_um(c: dict) -> Path | None:
    if c["source"] == "WU":
        log(f"  {c['cid']}: Windows Update baixa e valida sozinho na instalação.")
        return None
    url = url_download_catalogo(c["uid"]) if c["source"] == "CAT" else c["url"]
    dest = OUT / "drivers" / re.sub(r"[^\w.-]", "_", c["cid"])
    dest.mkdir(parents=True, exist_ok=True)
    arq = dest / (c.get("file") or url.rsplit("/", 1)[-1].split("?")[0])
    if not arq.exists():
        log(f"  baixando {url}")
        tmp = arq.with_suffix(arq.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.replace(arq)
    if c.get("sha256"):
        h = sha256_file(arq)
        if h != c["sha256"].upper():
            arq.unlink()
            raise RuntimeError(f"SHA-256 não confere ({h}) - arquivo apagado")
        log("  SHA-256 confere com o catálogo do fabricante")
    elif c.get("md5"):
        h = md5_file(arq)
        if h != c["md5"].upper():
            arq.unlink()
            raise RuntimeError(f"MD5 não confere ({h}) - arquivo apagado")
        log("  MD5 confere com o catálogo do fabricante")
    st, sub = assinatura(arq)
    if st != "Valid":
        raise RuntimeError(f"assinatura digital inválida ({st}) - não use este arquivo")
    log(f"  Assinatura válida: {sub}")
    return arq


def cmd_baixar(args) -> None:
    e = carregar_estado()
    for c in achar_cands(e, args.ids):
        log(f"\n{c['cid']} - {c['title']}")
        try:
            p = baixar_um(c)
            if p:
                log(f"  OK: {p}")
        except Exception as ex:
            log(f"  FALHOU: {ex}")


PS_WU_INSTALL = r"""
$ErrorActionPreference='Stop'
$ids=@(%IDS%)
$s=New-Object -ComObject Microsoft.Update.Session; $q=$s.CreateUpdateSearcher()
$mu=(New-Object -ComObject Microsoft.Update.ServiceManager).Services | Where-Object { $_.ServiceID -eq '7971f918-a847-4430-9279-4a52d1efe18d' }
if($mu){ $q.ServerSelection=3; $q.ServiceID=$mu.ServiceID }
$r=$q.Search("IsInstalled=0 and Type='Driver'")
$col=New-Object -ComObject Microsoft.Update.UpdateColl
foreach($u in $r.Updates){ if($ids -contains $u.Identity.UpdateID){ [void]$col.Add($u) } }
if($col.Count -eq 0){ 'nenhum'; exit }
$d=$s.CreateUpdateDownloader(); $d.Updates=$col; [void]$d.Download()
$i=$s.CreateUpdateInstaller(); $i.Updates=$col; $res=$i.Install()
"resultado=$($res.ResultCode) reboot=$($res.RebootRequired)"
"""


RC_OK = {0, 3010, 1641}
RC_REBOOT = {3010, 1641}


def _run(cmd, cwd: Path, timeout: int = 3600) -> int:
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                       timeout=timeout, creationflags=NO_WINDOW)
    saida = (r.stdout or "") + (r.stderr or "")
    if saida.strip():
        log("  " + saida.strip()[-800:])
    return r.returncode


def instalar_um(c: dict) -> tuple[bool, bool, str]:
    """Instala um candidato. Devolve (sucesso, precisa_reiniciar, mensagem curta)."""
    if c.get("kind") == "firmware":
        return False, False, "BIOS/firmware não é instalado automaticamente"
    if c["source"] == "WU":
        out = powershell(PS_WU_INSTALL.replace("%IDS%", "'" + c["cid"].split(":", 1)[1] + "'"), 3600)
        m = re.search(r"resultado=(\d+) reboot=(\w+)", out or "")
        ok = bool(m) and m.group(1) in ("2", "3")  # 2=sucesso, 3=sucesso com erros
        return ok, bool(m) and m.group(2).lower() == "true", "Windows Update: " + (out or "sem resposta")
    arq = baixar_um(c)
    assert arq
    pasta = arq.parent
    if c["source"] == "CAT":
        x = pasta / "extraido"
        expand_cab(arq, x)
        if not list(x.rglob("*.inf")):
            return False, False, "pacote do Catalog sem .inf"
        rc = _run(["pnputil.exe", "/add-driver", str(x / "*.inf"), "/subdirs", "/install"], pasta)
        return rc in RC_OK, rc in RC_REBOOT, f"pnputil código {rc}"
    if c["cid"].startswith("LEN:"):
        if c.get("extract"):
            _run(c["extract"].replace("%PACKAGEPATH%", str(pasta)), pasta)
        cmd = (c.get("install") or "").replace("%PACKAGEPATH%", str(pasta))
        oks = {int(x) for x in re.findall(r"-?\d+", c.get("install_rc") or "0")} | RC_OK
    elif c["cid"].startswith("DELL:"):
        cmd, oks = f'"{arq}" /s /l="{pasta / "dup.log"}"', {0, 2} | RC_OK
    else:  # HP softpaq
        cmd, oks = f'"{arq}" /s', RC_OK
    if not cmd:
        return False, False, "descritor sem comando de instalação"
    log(f"  executando: {cmd}")
    rc = _run(cmd, pasta)
    return rc in oks, rc in RC_REBOOT or (c["cid"].startswith("DELL:") and rc == 2), f"código de saída {rc}"


def ponto_restauracao() -> tuple[bool, str]:
    try:
        out = powershell("$ErrorActionPreference='Stop';Checkpoint-Computer -Description 'DriverPrecision' "
                         "-RestorePointType MODIFY_SETTINGS; 'ok'", 600)
        return "ok" in (out or ""), out or ""
    except Exception as ex:
        return False, str(ex)[:300]


def recomendados(e: dict) -> list[tuple[dict, dict]]:
    """O que o modo automático instala: só driver com correspondência confiável e versão comprovadamente melhor."""
    out = []
    for d in e["devices"]:
        b = d.get("melhor")
        if not b or b.get("kind") == "firmware":
            continue
        if d["status"] in ("INSTALAR", "SUBSTITUIR", "ATUALIZAR"):
            out.append((d, b))
    # um pacote pode atender vários dispositivos: instala uma vez só
    vistos, unicos = set(), []
    for d, b in out:
        if b["cid"] not in vistos:
            vistos.add(b["cid"])
            unicos.append((d, b))
    return unicos


def instalar_lista(cs: list[dict], progresso=None) -> dict:
    """Instala em sequência, sem perguntas (quem chama já confirmou). Devolve resumo."""
    res = {"ok": [], "falha": [], "reboot": False}
    for n, c in enumerate(cs, 1):
        if progresso:
            progresso(n, len(cs), c)
        log(f"\n[{n}/{len(cs)}] {c['title']}  ({c['cid']})")
        try:
            ok, rb, msg = instalar_um(c)
        except Exception as ex:
            ok, rb, msg = False, False, str(ex)
        log(("  OK: " if ok else "  FALHOU: ") + msg)
        res["ok" if ok else "falha"].append((c, msg))
        res["reboot"] = res["reboot"] or rb
    return res


def cmd_instalar(args) -> None:
    if not is_admin():
        sys.exit("Instalar exige terminal como Administrador.")
    e = carregar_estado()
    cs = achar_cands(e, args.ids) if args.ids else [b for _, b in recomendados(e)]
    if not cs:
        sys.exit("Nada recomendado para instalar.")
    log("Será instalado:")
    for c in cs:
        log(f"  - {c['cid']}  {c['title']}  v{c.get('version') or c.get('pkg_version')}  [{c['source_name']}]")
    if not args.sim and input("\nDigite SIM para continuar: ").strip().upper() != "SIM":
        sys.exit("Cancelado.")
    log("Criando ponto de restauração...")
    ok, msg = ponto_restauracao()
    log("  " + ("criado" if ok else f"não foi possível: {msg}"))
    if not ok and not args.sim and input("Continuar sem ponto de restauração? (SIM/não): ").strip().upper() != "SIM":
        sys.exit("Cancelado.")
    r = instalar_lista(cs)
    log(f"\nConcluído: {len(r['ok'])} instalados, {len(r['falha'])} com falha."
        + (" Reinicie o computador." if r["reboot"] else ""))


# --------------------------------------------------------------------------- main


def main() -> None:
    if os.name != "nt":
        sys.exit("Somente Windows.")
    ap = argparse.ArgumentParser(prog="driverprecision", description="Identifica o hardware e localiza o driver correto.")
    ap.add_argument("--version", action="version", version=f"DriverPrecision {VERSION}")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("scan", help="inventário + busca nas fontes + relatório (somente leitura)")
    s.add_argument("--sem-oem", action="store_true")
    s.add_argument("--sem-wu", action="store_true")
    s.add_argument("--sem-catalogo", action="store_true")
    s.add_argument("--nao-abrir", action="store_true", help="não abrir o relatório ao final")
    b = sub.add_parser("baixar", help="baixa e valida (hash + assinatura) sem instalar")
    b.add_argument("ids", nargs="+")
    i = sub.add_parser("instalar", help="instala os IDs dados, ou todos os recomendados se nenhum for dado (admin)")
    i.add_argument("ids", nargs="*")
    i.add_argument("--sim", action="store_true", help="não perguntar (para uso em script)")
    sub.add_parser("auto", help="verifica, baixa e instala os recomendados sem perguntas (admin)")
    argv = [x for x in sys.argv[1:] if x != "--sem-elevar"]  # marcador interno da reabertura via UAC
    a = ap.parse_args(argv)
    if a.cmd is None:
        # sem argumentos (duplo clique): interface gráfica para usuário comum
        from driverprecision_gui import run_gui
        run_gui()
    elif a.cmd == "scan":
        scan(a)
    elif a.cmd == "auto":
        if not is_admin():
            sys.exit("O modo auto exige terminal como Administrador.")
        scan(s.parse_args(["--nao-abrir"]))
        cmd_instalar(argparse.Namespace(ids=[], sim=True))
    elif a.cmd == "baixar":
        cmd_baixar(a)
    else:
        cmd_instalar(a)


if __name__ == "__main__":
    main()
