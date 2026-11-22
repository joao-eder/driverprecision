"""
Saúde do PC: segurança, integridade do sistema, memória e rede.

diagnostico() lê tudo numa chamada de PowerShell (só leitura) e avaliar() transforma em itens
com situação OK / ATENÇÃO / PROBLEMA / INFO e uma dica em português simples.
REPAROS são ações pontuais (limpar fila de impressão, SFC, DISM...) que o usuário dispara.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import driverprecision as dp

OK, ATENCAO, PROBLEMA, INFO = "OK", "ATENÇÃO", "PROBLEMA", "INFO"

PS_DIAG = r"""
$ErrorActionPreference='SilentlyContinue'
$o=[ordered]@{}
$cs=Get-CimInstance Win32_ComputerSystem; $os=Get-CimInstance Win32_OperatingSystem
$o.ram_gb=[math]::Round($cs.TotalPhysicalMemory/1GB,1)
$o.ram_livre_gb=[math]::Round($os.FreePhysicalMemory/1MB,1)
$o.uptime_h=[math]::Round(((Get-Date)-$os.LastBootUpTime).TotalHours,1)
$o.pagefile_auto=[bool]$cs.AutomaticManagedPagefile
$o.notebook=[bool](Get-CimInstance Win32_Battery)
$c=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$env:SystemDrive'"
$o.c_livre_gb=[math]::Round($c.FreeSpace/1GB,1); $o.c_total_gb=[math]::Round($c.Size/1GB,1)
$o.discos=@(Get-PhysicalDisk | ForEach-Object { [pscustomobject]@{nome=$_.FriendlyName; saude=[string]$_.HealthStatus} })
$o.antivirus=@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | ForEach-Object {
  [pscustomobject]@{nome=$_.displayName; estado=[int64]$_.productState} })
$mp=Get-MpComputerStatus
if($mp){ $o.defender_rt=[bool]$mp.RealTimeProtectionEnabled; $o.defender_assin_dias=[int]$mp.AntivirusSignatureAge }
$o.firewall=@(Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{perfil=[string]$_.Name; ligado=[bool]$_.Enabled} })
$hf=Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1
if($hf){ $o.update_dias=[int]((Get-Date)-$hf.InstalledOn).TotalDays }
$bl=Get-BitLockerVolume -MountPoint $env:SystemDrive
if($bl){ $o.bitlocker=[string]$bl.ProtectionStatus }
try { $o.secureboot=[bool](Confirm-SecureBootUEFI) } catch { }
$t=Get-Tpm; if($t){ $o.tpm=[bool]($t.TpmPresent -and $t.TpmReady) }
$o.uac=(Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System).EnableLUA
$f=Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol; if($f){ $o.smb1=[string]$f.State }
$rc=Get-CimInstance -Namespace root/default -ClassName SystemRestoreConfig
if($rc){ $o.restauracao_ligada=([int]$rc.RPSessionInterval -eq 1) }
$rp=Get-ComputerRestorePoint | Select-Object -Last 1
if($rp){ $o.restauracao_dias=[int]((Get-Date)-[Management.ManagementDateTimeConverter]::ToDateTime($rp.CreationTime)).TotalDays }
$o.redes=@(Get-NetConnectionProfile | ForEach-Object { [pscustomobject]@{nome=[string]$_.Name; categoria=[string]$_.NetworkCategory
  internet=[string]$_.IPv4Connectivity} })
$o.spooler=[string](Get-Service Spooler).Status
$o.office_plataforma=[string](Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration).Platform
$o.inicializacao=@(Get-CimInstance Win32_StartupCommand | ForEach-Object { [string]$_.Name } | Sort-Object -Unique)
$o | ConvertTo-Json -Depth 4 -Compress
"""


def diagnostico() -> dict:
    return json.loads(dp.powershell(PS_DIAG, 300) or "{}")


def _lista(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def avaliar(d: dict, amb: dict | None = None) -> list[dict]:
    """Itens da tela Saúde do PC, já com situação e dica. Função pura (testável sem Windows)."""
    out: list[dict] = []

    def item(grupo, iid, nome, st, detalhe, dica="", reparo=None, ajuste=None):
        out.append({"grupo": grupo, "id": iid, "nome": nome, "status": st, "detalhe": detalhe, "dica": dica,
                    "reparo": reparo, "ajuste": ajuste})

    # ------------------------------------------------ Segurança
    g = "Segurança"
    avs = _lista(d.get("antivirus"))
    ativos = [a["nome"] for a in avs if (int(a.get("estado") or 0) >> 12) & 0xF == 1]
    if ativos:
        item(g, "antivirus", "Antivírus", OK, ", ".join(ativos) + " ativo")
    elif d.get("defender_rt"):
        item(g, "antivirus", "Antivírus", OK, "Microsoft Defender com proteção em tempo real")
    elif avs or "defender_rt" in d:
        item(g, "antivirus", "Antivírus", PROBLEMA, "nenhum antivírus com proteção em tempo real ligada",
             "Abra Segurança do Windows > Proteção contra vírus e ameaças e ligue a proteção em tempo real.")
    else:
        item(g, "antivirus", "Antivírus", INFO, "não foi possível ler o estado do antivírus")
    dias = d.get("defender_assin_dias")
    if d.get("defender_rt") and dias is not None:
        item(g, "assinaturas", "Vacinas do Defender", OK if dias <= 3 else ATENCAO,
             f"atualizadas há {dias} dia(s)", "" if dias <= 3 else "Rode o Windows Update: o antivírus está sem as vacinas recentes.")
    fw = _lista(d.get("firewall"))
    off = [f["perfil"] for f in fw if not f.get("ligado")]
    if fw:
        item(g, "firewall", "Firewall", PROBLEMA if off else OK,
             ("desligado em: " + ", ".join(off)) if off else "ligado em todas as redes",
             "Ligue em Segurança do Windows > Firewall e proteção de rede." if off else "")
    up = d.get("update_dias")
    if up is None:
        item(g, "update", "Atualizações do Windows", INFO, "data da última atualização indisponível")
    else:
        st = OK if up <= 40 else (ATENCAO if up <= 90 else PROBLEMA)
        item(g, "update", "Atualizações do Windows", st, f"última instalada há {up} dia(s)",
             "" if st == OK else "Abra Configurações > Windows Update e instale o que estiver pendente. "
                                 "PC sem atualização é a principal porta de entrada de vírus e golpes.")
    if d.get("uac") is not None:
        item(g, "uac", "Controle de Conta (UAC)", OK if d["uac"] == 1 else PROBLEMA,
             "ligado" if d["uac"] == 1 else "desligado: qualquer programa ganha acesso total ao PC",
             "" if d["uac"] == 1 else "Ligue em Painel de Controle > Contas de Usuário > Alterar configurações de Controle de Conta.")
    smb1 = d.get("smb1")
    if smb1:
        item(g, "smb1", "SMB1 (rede antiga)", ATENCAO if smb1 == "Enabled" else OK,
             "ligado" if smb1 == "Enabled" else "desligado",
             "Usado pelo WannaCry. Desligue em Escritório > Segurança, a não ser que um NAS ou impressora antigos dependam dele."
             if smb1 == "Enabled" else "", ajuste="smb1_off" if smb1 == "Enabled" else None)
    bl = d.get("bitlocker")
    if bl == "On":
        item(g, "bitlocker", "BitLocker (criptografia)", OK, "ligada",
             "Guarde a chave de recuperação (conta Microsoft ou impressa): sem ela, uma troca de placa-mãe trava o acesso aos dados.")
    elif bl is not None:
        item(g, "bitlocker", "BitLocker (criptografia)", ATENCAO if d.get("notebook") else INFO, "desligada",
             "Em notebook, ligue: se ele for roubado, os arquivos ficam ilegíveis. Painel de Controle > Criptografia de Unidade de Disco BitLocker."
             if d.get("notebook") else "")
    else:
        item(g, "bitlocker", "BitLocker (criptografia)", INFO, "não disponível nesta edição do Windows")
    if d.get("secureboot") is not None or d.get("tpm") is not None:
        partes = []
        if d.get("secureboot") is not None:
            partes.append("Inicialização Segura " + ("ligada" if d["secureboot"] else "desligada"))
        if d.get("tpm") is not None:
            partes.append("TPM " + ("pronto" if d["tpm"] else "indisponível"))
        bom = d.get("secureboot") is not False and d.get("tpm") is not False
        item(g, "firmware", "Proteção na inicialização", OK if bom else INFO, ", ".join(partes),
             "" if bom else "Inicialização Segura e TPM se ligam no setup (BIOS/UEFI) do PC; exigidos pelo Windows 11.")

    # ------------------------------------------------ Integridade
    g = "Integridade do sistema"
    rl = d.get("restauracao_ligada")
    if rl is False:
        item(g, "restauracao", "Pontos de restauração", ATENCAO, "Proteção do sistema desligada",
             "Sugestão: ligue em Painel de Controle > Sistema > Proteção do sistema (disco C: > Configurar > Ativar). "
             "É o 'voltar no tempo' quando uma atualização ou programa estraga o Windows. O DriverPrecision não muda isso.")
    elif rl:
        rd = d.get("restauracao_dias")
        item(g, "restauracao", "Pontos de restauração", OK if rd is not None and rd <= 30 else INFO,
             f"último criado há {rd} dia(s)" if rd is not None else "ligada, nenhum ponto criado ainda",
             "" if rd is not None and rd <= 30 else "O Windows cria pontos sozinho antes de atualizações; este programa cria antes de cada instalação.")
    for disco in _lista(d.get("discos")):
        s = disco.get("saude") or ""
        item(g, "disco_" + (disco.get("nome") or "?"), f"Disco {disco.get('nome') or ''}".strip(),
             OK if s == "Healthy" else (PROBLEMA if s in ("Unhealthy", "Warning") else INFO),
             {"Healthy": "saudável", "Warning": "com alerta (SMART)", "Unhealthy": "com falha"}.get(s, s or "desconhecido"),
             "" if s == "Healthy" else "Faça backup dos arquivos importantes AGORA e troque o disco." if s in ("Unhealthy", "Warning") else "")
    livre, total = d.get("c_livre_gb"), d.get("c_total_gb")
    if livre is not None and total:
        pct = livre / total * 100
        st = OK if pct >= 15 else (ATENCAO if pct >= 8 else PROBLEMA)
        item(g, "espaco", "Espaço livre no disco C:", st, f"{livre:.0f} GB livres de {total:.0f} GB ({pct:.0f}%)",
             "" if st == OK else "Com pouco espaço, o Windows não consegue se atualizar e fica lento. Use 'Limpar temporários' "
                                 "e apague downloads antigos.", reparo=None if st == OK else "temp")
    item(g, "arquivos_sistema", "Arquivos do sistema", INFO, "verificação demora (10 a 30 min)",
         "Se o Windows trava, dá tela azul ou programas fecham sem motivo, rode 'Reparar sistema' e depois "
         "'Reparar imagem'.", reparo="sfc")

    # ------------------------------------------------ Memória e desempenho
    g = "Memória e desempenho"
    ram, livre_ram = d.get("ram_gb"), d.get("ram_livre_gb")
    if ram:
        uso = (1 - (livre_ram or 0) / ram) * 100
        st = OK if ram >= 15 else (ATENCAO if ram >= 7.5 else PROBLEMA)
        item(g, "ram", "Memória RAM", st, f"{ram:.0f} GB, {uso:.0f}% em uso agora",
             "" if st == OK else "Para muitas abas e planilhas, 8 GB é o mínimo e 16 GB o confortável. Memória é a "
                                 "melhoria mais barata para esse uso.")
    up = d.get("uptime_h")
    if up is not None:
        dias_l = up / 24
        item(g, "uptime", "Tempo ligado sem reiniciar", OK if dias_l < 7 else ATENCAO,
             f"{dias_l:.0f} dia(s)" if dias_l >= 1 else f"{up:.0f} hora(s)",
             "" if dias_l < 7 else "Reinicie (não só desligue): libera memória presa e conclui atualizações pendentes.")
    if d.get("pagefile_auto") is False:
        item(g, "pagefile", "Arquivo de paginação", ATENCAO, "configurado manualmente",
             "Tamanho fixo ou desligado faz o navegador mostrar 'Sem memória'. Corrija em Escritório > Memória.", ajuste="pagefile")
    ini = _lista(d.get("inicializacao"))
    if ini:
        item(g, "inicializacao", "Programas que abrem com o Windows", OK if len(ini) <= 10 else ATENCAO,
             f"{len(ini)}: " + ", ".join(ini[:8]) + ("..." if len(ini) > 8 else ""),
             "" if len(ini) <= 10 else "Desative os que você não usa todo dia em Gerenciador de Tarefas > Aplicativos de inicialização.")
    plat = (d.get("office_plataforma") or "").lower()
    if plat:
        item(g, "office_bits", "Microsoft Office", OK if plat == "x64" else ATENCAO,
             "64 bits" if plat == "x64" else "32 bits",
             "" if plat == "x64" else "Excel 32 bits usa no máximo 2 GB de memória: planilhas grandes travam ou dão 'Sem recursos'. "
                                      "Reinstale o Office na versão 64 bits (portal da Microsoft 365).")

    # ------------------------------------------------ Rede
    g = "Rede"
    for r in _lista(d.get("redes")):
        cat, nome = r.get("categoria"), r.get("nome") or "rede"
        net = (r.get("internet") or "") == "Internet"
        if cat == "Public":
            item(g, "rede_" + nome, f"Conexão '{nome}'", INFO, "rede Pública" + (", com internet" if net else ", sem internet"),
                 "Em rede Pública o Windows esconde este PC e não mostra pastas nem impressoras da rede. Se esta é a rede do "
                 "escritório ou de casa, mude para Particular em Configurações > Rede e Internet > propriedades da conexão.")
        else:
            item(g, "rede_" + nome, f"Conexão '{nome}'", OK if net else ATENCAO,
                 {"Private": "Particular", "DomainAuthenticated": "Domínio da empresa"}.get(cat, cat or "") +
                 (", com internet" if net else ", sem internet"),
                 "" if net else "Sem internet: tente 'Limpar DNS'; se continuar, 'Redefinir rede'.",
                 reparo=None if net else "dns")
    sp = d.get("spooler")
    if sp:
        item(g, "spooler", "Serviço de impressão", OK if sp == "Running" else PROBLEMA,
             "funcionando" if sp == "Running" else "parado: nada imprime",
             "" if sp == "Running" else "Use 'Destravar impressão'.", reparo=None if sp == "Running" else "spooler")

    # ------------------------------------------------ Ambiente
    if amb and amb.get("gerenciado"):
        item("Empresa", "ambiente", "PC gerenciado pela empresa", INFO, amb.get("descricao") or "",
             "Ajustes que a TI controla (políticas, serviços, segurança) ficam bloqueados nas telas de ajustes, "
             "para o programa não brigar com a configuração da empresa.")
    return out


# --------------------------------------------------------------------------- reparos

REPAROS: list[dict] = [
    {"id": "dns", "nome": "Limpar DNS", "tempo": "segundos", "reboot": False,
     "desc": "Site ou sistema interno que 'não abre' mas abre no celular: costuma ser endereço velho guardado no PC."},
    {"id": "spooler", "nome": "Destravar impressão", "tempo": "segundos", "reboot": False,
     "desc": "Para o serviço de impressão, apaga a fila travada (documentos presos) e liga de novo."},
    {"id": "temp", "nome": "Limpar temporários", "tempo": "até 1 minuto", "reboot": False,
     "desc": "Apaga arquivos temporários com mais de 1 dia, do usuário e do Windows. Não mexe em documentos, downloads ou senhas."},
    {"id": "chkdsk", "nome": "Verificar disco", "tempo": "1 a 5 minutos", "reboot": False,
     "desc": "Procura erros no sistema de arquivos sem interromper o uso (chkdsk /scan)."},
    {"id": "sfc", "nome": "Reparar sistema", "tempo": "10 a 30 minutos", "reboot": True,
     "desc": "Confere todos os arquivos do Windows e troca os corrompidos por cópias boas (sfc /scannow)."},
    {"id": "dism", "nome": "Reparar imagem", "tempo": "10 a 40 minutos, precisa de internet", "reboot": True,
     "desc": "Conserta a base que o SFC usa para reparar, baixando peças do Windows Update (DISM /RestoreHealth). "
             "Use se o SFC disser que não conseguiu reparar tudo."},
    {"id": "rede_reset", "nome": "Redefinir rede", "tempo": "segundos + reiniciar", "reboot": True,
     "desc": "Último recurso para internet que não volta: refaz as configurações de rede do Windows (Winsock e TCP/IP). "
             "Senhas de Wi-Fi ficam. Algumas VPNs podem precisar ser reinstaladas."},
]
REP_ID = {r["id"]: r for r in REPAROS}


def _exec(args: list[str], timeout: int = 3600) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=dp.NO_WINDOW)
    return r.returncode, dp._dec(r.stdout) + dp._dec(r.stderr)


def _ultima_frase(out: str) -> str:
    """Última linha útil da saída (sem barras de progresso como '[====  59.1%  ]')."""
    linhas = [l.strip() for l in out.replace("\r", "\n").splitlines()]
    linhas = [l for l in linhas if l and "%" not in l and not set(l) <= set("=[]-. ")]
    return linhas[-1][:300] if linhas else ""


def _limpa_temp(dias: float = 1) -> tuple[int, int]:
    limite = time.time() - dias * 86400
    pastas = {Path(os.environ.get("TEMP", "")), Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"}
    n = tam = 0
    for base in pastas:
        if not base.is_dir() or len(base.parts) < 3:  # nunca a raiz de um disco
            continue
        for raiz, dirs, arqs in os.walk(base, topdown=False):
            for a in arqs:
                p = Path(raiz) / a
                try:
                    st = p.stat()
                    if st.st_mtime < limite:
                        p.unlink()
                        n += 1
                        tam += st.st_size
                except OSError:
                    pass  # em uso: fica
            for dd in dirs:
                try:
                    (Path(raiz) / dd).rmdir()  # só some se ficou vazia
                except OSError:
                    pass
    return n, tam


def executar(rid: str) -> tuple[bool, bool, str]:
    """(sucesso, precisa_reiniciar, mensagem)."""
    w = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    if rid == "dns":
        rc, out = _exec([str(w / "ipconfig.exe"), "/flushdns"], 60)
        return rc == 0, False, "cache de DNS limpo" if rc == 0 else out.strip()[-300:]
    if rid == "spooler":
        out = dp.powershell("Stop-Service Spooler -Force -ErrorAction SilentlyContinue; Start-Sleep 2;"
                            "Remove-Item \"$env:SystemRoot\\System32\\spool\\PRINTERS\\*\" -Force -ErrorAction SilentlyContinue;"
                            "Start-Service Spooler; (Get-Service Spooler).Status", 120)
        ok = out.strip().endswith("Running")
        return ok, False, "fila de impressão limpa, serviço funcionando" if ok else "o serviço de impressão não voltou: " + out[-200:]
    if rid == "temp":
        n, tam = _limpa_temp()
        return True, False, f"{n} arquivo(s) apagado(s), {tam / 1e6:.0f} MB liberados"
    if rid == "chkdsk":
        rc, out = _exec([str(w / "chkdsk.exe"), os.environ.get("SystemDrive", "C:"), "/scan"], 3600)
        if rc == 0:
            return True, False, "nenhum erro encontrado no disco"
        return False, False, (f"chkdsk encontrou problemas (código {rc}). Para corrigir, abra o Prompt como administrador, "
                              "rode 'chkdsk C: /f' e reinicie.")
    if rid == "sfc":
        rc, out = _exec([str(w / "sfc.exe"), "/scannow"], 5400)
        return rc == 0, rc == 0, _ultima_frase(out) or f"terminou com código {rc}"
    if rid == "dism":
        rc, out = _exec([str(w / "Dism.exe"), "/Online", "/Cleanup-Image", "/RestoreHealth"], 5400)
        return rc == 0, rc == 0, ("imagem do Windows reparada/íntegra. " if rc == 0 else f"DISM falhou (código {rc}). ") + _ultima_frase(out)
    if rid == "rede_reset":
        rc1, o1 = _exec([str(w / "netsh.exe"), "winsock", "reset"], 120)
        rc2, o2 = _exec([str(w / "netsh.exe"), "int", "ip", "reset"], 120)
        ok = rc1 == 0
        return ok, ok, "rede redefinida, reinicie o PC para concluir" if ok else (o1 + o2).strip()[-300:]
    raise ValueError(rid)
