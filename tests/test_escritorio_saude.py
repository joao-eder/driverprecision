"""Tela Escritório (perfis, ajustes via PowerShell, PC de empresa) e Saúde do PC. Não toca no sistema."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision_otimiza as ot  # noqa: E402
import driverprecision_saude as sd  # noqa: E402
from test_otimiza_jogos import RegistroFalso  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._salvo = (ot.REG, ot.BACKUP, ot._AMBIENTE, ot.dp.powershell)
        ot.REG = RegistroFalso()
        ot.BACKUP = Path(self.tmp.name) / "bk.json"
        ot._AMBIENTE = {"gerenciado": False, "descricao": "", "dominio": False, "entra": False, "mdm": False}

    def tearDown(self):
        ot.REG, ot.BACKUP, ot._AMBIENTE, ot.dp.powershell = self._salvo
        self.tmp.cleanup()


class Perfis(Base):
    def test_cada_tela_tem_seus_ajustes(self):
        jogos, esc = ot.do_perfil("jogos"), ot.do_perfil("escritorio")
        ids_j, ids_e = {a["id"] for a in jogos}, {a["id"] for a in esc}
        self.assertIn("plano_max", ids_j)
        self.assertNotIn("plano_max", ids_e)          # plano de desempenho máximo acaba com a bateria do notebook
        self.assertNotIn("vbs", ids_e)                # nada que reduza segurança no escritório
        self.assertNotIn("hibernacao", ids_e)
        self.assertIn("chrome_memoria", ids_e)
        self.assertNotIn("chrome_memoria", ids_j)
        self.assertIn("telemetria", ids_j & ids_e)    # compartilhados aparecem nas duas
        cats = [a["cat"] for a in esc]
        self.assertEqual(cats[0], ot.CAT_ENERGIA)
        self.assertEqual([c for c in cats if c != ot.CAT_ENERGIA][0], "Memória e muitas abas")
        self.assertEqual(cats, sorted(cats, key=ot.ORDEM_CATS["escritorio"].index))

    def test_nenhum_ajuste_de_escritorio_reduz_seguranca(self):
        for a in ot.do_perfil("escritorio"):
            self.assertFalse(a.get("seguranca"), a["id"])
            self.assertNotEqual(a["risco"], "alto", a["id"])


class AjustePowerShell(Base):
    def _ps(self, estado):
        chamadas = []

        def fake(script, timeout=600):
            chamadas.append(script)
            if "Get-MMAgent" in script:
                return estado["v"]
            if "Enable-MMAgent" in script and "'True' -eq 'True'" in script:
                estado["v"] = "True"
            elif "MMAgent" in script:
                estado["v"] = "False" if "'False' -eq 'True'" in script else estado["v"]
            return ""
        ot.dp.powershell = fake
        return chamadas

    def test_aplica_e_desfaz_pelo_powershell(self):
        estado = {"v": "False"}
        self._ps(estado)
        a = ot.POR_ID["memcomp"]
        self.assertEqual(ot.estado(a), "PADRÃO")
        ot.aplicar("memcomp")
        self.assertEqual(estado["v"], "True")
        self.assertEqual(ot.estado(a), "ATIVO")
        ot.desfazer("memcomp")
        self.assertEqual(estado["v"], "False")
        self.assertEqual(ot.aplicados(), [])

    def test_ja_ativo_nao_mexe_e_desfazer_nao_desliga(self):
        estado = {"v": "True"}
        chamadas = self._ps(estado)
        ot.aplicar("memcomp")
        ot.desfazer("memcomp")
        self.assertEqual(estado["v"], "True")
        self.assertFalse(any("Disable-MMAgent" in c and "'False' -eq 'True'" in c for c in chamadas))

    def test_recurso_inexistente_vira_nao_se_aplica(self):
        def falha(script, timeout=600):
            raise RuntimeError("cmdlet não existe")
        ot.dp.powershell = falha
        self.assertEqual(ot.estado(ot.POR_ID["pua"]), "N/A")
        with self.assertRaises(RuntimeError):
            ot.aplicar("pua")
        self.assertEqual(ot.aplicados(), [])

    def test_protecao_do_sistema_nao_e_desligada_no_desfazer(self):
        estado = {"v": "0"}
        gravados = []

        def fake(script, timeout=600):
            if "SystemRestoreConfig" in script:
                return estado["v"]
            gravados.append(script)
            if "Enable-ComputerRestore" in script and "'1' -eq '1'" in script:
                estado["v"] = "1"
            return ""
        ot.dp.powershell = fake
        ot.aplicar("restauracao")
        self.assertEqual(estado["v"], "1")
        msg = ot.desfazer("restauracao")
        self.assertEqual(estado["v"], "1")            # desligar apagaria os pontos de restauração
        self.assertIn("continua ligada", msg)
        self.assertEqual(len(gravados), 1)

    def test_paginacao_guarda_e_devolve_tamanho_manual(self):
        estado = {"v": "False"}

        def fake(script, timeout=600):
            if "AutomaticManagedPagefile" in script and "Set-CimInstance" not in script:
                return estado["v"]
            if "Set-CimInstance" in script:
                estado["v"] = "True" if "Parse('True')" in script else "False"
                if estado["v"] == "True":
                    ot.REG.set("HKLM", ot.MEM, "PagingFiles", "MULTI_SZ", ["?:\\pagefile.sys"])
            return ""
        ot.dp.powershell = fake
        manual = ["C:\\pagefile.sys 1024 2048"]
        ot.REG.set("HKLM", ot.MEM, "PagingFiles", "MULTI_SZ", manual)
        ot.aplicar("pagefile")
        self.assertEqual(estado["v"], "True")
        ot.desfazer("pagefile")
        self.assertEqual(estado["v"], "False")
        self.assertEqual(ot.REG.get("HKLM", ot.MEM, "PagingFiles")[2], manual)


class Demora(Base):
    def test_confere_de_novo_quando_o_windows_demora(self):
        leituras = iter(["False", "False", "False", "True"])   # antes, logo depois, ..., refletiu

        def fake(script, timeout=600):
            return next(leituras) if "Get-MMAgent" in script else ""
        ot.dp.powershell = fake
        sleep_orig, ot.time.sleep = ot.time.sleep, lambda s: None
        try:
            ot.aplicar("memcomp")
            self.assertEqual(ot.aplicados(), ["memcomp"])
        finally:
            ot.time.sleep = sleep_orig


class PcDaEmpresa(Base):
    def test_programa_ausente_fica_nao_se_aplica(self):
        a = ot.POR_ID["chrome_memoria"]
        self.assertEqual(ot.estado(a), "N/A")
        self.assertIn("Chrome", ot.bloqueado(a))
        with self.assertRaises(RuntimeError):
            ot.aplicar("chrome_memoria")
        ot.REG.set("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", "", "SZ", "C:\\chrome.exe")
        self.assertEqual(ot.bloqueado(a), "")

    def test_pc_gerenciado_bloqueia_so_o_que_a_ti_controla(self):
        ot._AMBIENTE = {"gerenciado": True, "descricao": "domínio EMPRESA", "dominio": True, "entra": False, "mdm": False}
        for aid in ("telemetria", "rede_descoberta", "unidades_admin", "pua", "smb1_off", "vpn_dns", "plano_max", "wifi_power"):
            self.assertIn("empresa", ot.bloqueado(ot.POR_ID[aid]), aid)
        for aid in ("impressora_padrao", "extensoes", "visual", "anuncios"):
            self.assertEqual(ot.bloqueado(ot.POR_ID[aid]), "", aid)
        with self.assertRaises(RuntimeError):
            ot.aplicar("telemetria")
        lista = {a["id"]: a for a in ot.listar("escritorio")}
        self.assertTrue(lista["pua"]["bloqueado"])
        self.assertFalse(lista["impressora_padrao"]["bloqueado"])


class Saude(unittest.TestCase):
    def _st(self, itens, iid):
        return next(i for i in itens if i["id"] == iid)

    def test_avaliacao(self):
        d = {"ram_gb": 7.8, "ram_livre_gb": 1, "uptime_h": 300, "pagefile_auto": False, "notebook": True,
             "c_livre_gb": 10, "c_total_gb": 240, "discos": {"nome": "SSD", "saude": "Warning"},
             "antivirus": [{"nome": "Windows Defender", "estado": 397568}], "defender_rt": True, "defender_assin_dias": 9,
             "firewall": [{"perfil": "Public", "ligado": False}, {"perfil": "Private", "ligado": True}],
             "update_dias": 120, "bitlocker": "Off", "uac": 0, "smb1": "Enabled", "restauracao_ligada": False,
             "redes": {"nome": "Wi-Fi", "categoria": "Public", "internet": "Internet"}, "spooler": "Stopped",
             "office_plataforma": "x86", "inicializacao": [str(i) for i in range(14)]}
        it = sd.avaliar(d, {"gerenciado": True, "descricao": "Intune/MDM"})
        esperado = {"antivirus": sd.OK, "assinaturas": sd.ATENCAO, "firewall": sd.PROBLEMA, "update": sd.PROBLEMA,
                    "uac": sd.PROBLEMA, "smb1": sd.ATENCAO, "bitlocker": sd.ATENCAO, "restauracao": sd.ATENCAO,
                    "disco_SSD": sd.PROBLEMA, "espaco": sd.PROBLEMA, "ram": sd.ATENCAO, "uptime": sd.ATENCAO,
                    "pagefile": sd.ATENCAO, "inicializacao": sd.ATENCAO, "office_bits": sd.ATENCAO, "spooler": sd.PROBLEMA,
                    "rede_Wi-Fi": sd.INFO, "ambiente": sd.INFO}
        for iid, st in esperado.items():
            self.assertEqual(self._st(it, iid)["status"], st, iid)
        self.assertEqual(self._st(it, "spooler")["reparo"], "spooler")
        self.assertEqual(self._st(it, "smb1")["ajuste"], "smb1_off")
        for i in it:   # ajustes e reparos citados existem
            if i["ajuste"]:
                self.assertIn(i["ajuste"], ot.POR_ID)
            if i["reparo"]:
                self.assertIn(i["reparo"], sd.REP_ID)

    def test_pc_saudavel_e_dados_faltando(self):
        d = {"ram_gb": 16, "ram_livre_gb": 8, "uptime_h": 20, "pagefile_auto": True, "c_livre_gb": 200, "c_total_gb": 500,
             "discos": [{"nome": "NVMe", "saude": "Healthy"}], "antivirus": [], "defender_rt": True, "defender_assin_dias": 0,
             "firewall": [{"perfil": "Domain", "ligado": True}], "update_dias": 5, "bitlocker": "On", "uac": 1,
             "smb1": "Disabled", "restauracao_ligada": True, "restauracao_dias": 2, "spooler": "Running", "office_plataforma": "x64"}
        it = sd.avaliar(d)
        ruins = [i["id"] for i in it if i["status"] in (sd.PROBLEMA, sd.ATENCAO)]
        self.assertEqual(ruins, [])
        self.assertTrue(sd.avaliar({}))               # Windows sem os cmdlets: não quebra

    def test_limpa_so_temporario_antigo(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / "a" / "Temp"
            (base / "sub").mkdir(parents=True)
            velho, novo = base / "sub" / "velho.tmp", base / "novo.tmp"
            velho.write_bytes(b"x" * 1000)
            novo.write_bytes(b"y")
            antigo = time.time() - 3 * 86400
            os.utime(velho, (antigo, antigo))
            env = os.environ.copy()
            try:
                os.environ["TEMP"] = str(base)
                os.environ["SystemRoot"] = str(Path(t) / "nao_existe")
                n, tam = sd._limpa_temp()
            finally:
                os.environ.clear()
                os.environ.update(env)
            self.assertEqual((n, tam), (1, 1000))
            self.assertFalse(velho.exists())
            self.assertTrue(novo.exists())


if __name__ == "__main__":
    unittest.main()


class PlanoDeEnergia(Base):
    def test_plano_novo_herda_tampa_e_tela_do_plano_anterior(self):
        antigo, novo = "381b4222-f694-41f0-9685-ff5bb260df2e", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        planos = {antigo: {"LIDACTION": [0, 0], "VIDEOIDLE": [600, 300], "PBUTTONACTION": [1, 1],
                           "SBUTTONACTION": [1, 1], "STANDBYIDLE": [0, 900]},
                  novo: {"LIDACTION": [1, 1], "VIDEOIDLE": [0, 0], "PBUTTONACTION": [1, 1],
                         "SBUTTONACTION": [1, 1], "STANDBYIDLE": [0, 0]}}
        ativo = [antigo]

        def cmd(args):
            op = args[1].lower()
            if op == "/getactivescheme":
                return 0, f"GUID do Esquema de Energia: {ativo[0]}  (Equilibrado)"
            if op == "/list":
                return 0, f"GUID do Esquema de Energia: {novo}  (Desempenho Máximo)"
            if op == "/qh":
                ac, dc = planos[args[2]][args[4]]
                return 0, f"Índice AC Atual: 0x{ac:08x}\r\nÍndice DC Atual: 0x{dc:08x}\r\n"
            if op in ("/setacvalueindex", "/setdcvalueindex"):
                planos[args[2]].setdefault(args[4], [None, None])[0 if "ac" in op else 1] = int(args[5])
                return 0, ""
            if op == "/setactive":
                ativo[0] = args[2]
            return 0, ""
        cmd_orig, ot._cmd = ot._cmd, cmd
        try:
            ot.aplicar("plano_max")
            self.assertEqual(ativo[0], novo)
            self.assertEqual(planos[novo]["LIDACTION"], [0, 0])      # tampa: "não fazer nada" continua
            self.assertEqual(planos[novo]["VIDEOIDLE"], [600, 300])
            self.assertEqual(planos[novo]["STANDBYIDLE"], [0, 900])
            for _, st, v in ot.DESEMPENHO_NA_BATERIA:              # desempenho também na bateria
                self.assertEqual(planos[novo][st], [v, v], st)
            self.assertNotIn("3619c3f2-afb2-4afc-b0e9-e7fef372de36", planos[antigo])   # plano antigo intocado
            ot.desfazer("plano_max")
            self.assertEqual(ativo[0], antigo)
        finally:
            ot._cmd = cmd_orig


class Tampa(Base):
    def test_tampa_vale_em_todos_os_planos_e_desfaz(self):
        p1, p2 = "381b4222-f694-41f0-9685-ff5bb260df2e", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
        lid = {p1: [1, 3], p2: [0, 0]}          # Equilibrado: suspende na tomada, desliga na bateria; Alto desempenho: nada

        def cmd(args):
            op = args[1].lower()
            if op == "/list":
                return 0, f"GUID: {p1}  (Equilibrado) *\r\nGUID: {p2}  (Alto desempenho)"
            if op == "/getactivescheme":
                return 0, f"GUID: {p1}"
            if op == "/qh":
                ac, dc = lid[args[2]]
                return 0, f"AC: 0x{ac:08x}\r\nDC: 0x{dc:08x}\r\n"
            if op in ("/setacvalueindex", "/setdcvalueindex"):
                lid[args[2]][0 if "ac" in op else 1] = int(args[5])
            return 0, ""
        cmd_orig, bat = ot._cmd, ot._BATERIA
        ot._cmd, ot._BATERIA = cmd, True
        try:
            a = ot.POR_ID["tampa_nada"]
            self.assertEqual(set(a["perfis"]), {"jogos", "escritorio"})
            self.assertEqual(ot.estado(a), "PARCIAL")
            ot.aplicar("tampa_nada")
            self.assertEqual(lid, {p1: [0, 0], p2: [0, 0]})
            self.assertEqual(ot.estado(a), "ATIVO")
            ot.desfazer("tampa_nada")
            self.assertEqual(lid, {p1: [1, 3], p2: [0, 0]})
            ot._BATERIA = False                  # desktop: não se aplica
            self.assertEqual(ot.estado(a), "N/A")
        finally:
            ot._cmd, ot._BATERIA = cmd_orig, bat

    def test_notebook_no_topo_das_duas_telas(self):
        for perfil in ("jogos", "escritorio"):
            self.assertEqual([a["id"] for a in ot.do_perfil(perfil)[:3]], ["tampa_nada", "botoes_nada", "tela_sempre"], perfil)
