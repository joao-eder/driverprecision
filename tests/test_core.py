"""Testes das regras de casamento e comparação (não acessam rede nem WMI)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision as dp  # noqa: E402


def dev(hwids, compat=(), inf="oem1.inf", cls="SYSTEM", ver="1.0.0.0", err=0):
    hw = [h.upper() for h in hwids]
    cp = [c.upper() for c in compat]
    return {
        "id": hw[0] + "\\0", "name": hw[0], "cls": cls, "hwids": hw, "compat": cp,
        "mids": hw + [c for c in cp if ("VEN_" in c or "VID_" in c) and c not in hw],
        "ver": ver, "inf": inf, "inbox": not inf.lower().startswith("oem"),
        "sem_driver": bool(err) or not inf, "err": err, "bus": hw[0].split("\\")[0], "cands": [],
    }


class Versao(unittest.TestCase):
    def test_vcmp(self):
        self.assertEqual(dp.vcmp("24.40.0.4", "23.110.0.5"), 1)
        self.assertEqual(dp.vcmp("1.85", "1.85.0.0"), 0)
        self.assertEqual(dp.vcmp("10.0.1", "10.0.10"), -1)
        self.assertIsNone(dp.vcmp("", "1.0"))

    def test_limpa_ver_lenovo(self):
        self.assertEqual(dp.limpa_ver("6.0.9430.1^10.0"), "6.0.9430.1")
        self.assertEqual(dp.limpa_ver("1.7.46.1308^"), "1.7.46.1308")
        self.assertEqual(dp.limpa_ver("10.0.22000.1/10.13.1.4/5.0.18.168", "5.0.1.1"), "5.0.18.168")


class Casamento(unittest.TestCase):
    def test_id_exato(self):
        ids = ["PCI\\VEN_8086&DEV_9DF0&SUBSYS_00308086"]
        self.assertEqual(dp.id_match(ids, "pci\\ven_8086&dev_9df0&subsys_00308086"), ids[0])
        self.assertIsNone(dp.id_match(ids, "PCI\\VEN_8086&DEV_9DF"))

    def test_id_sem_barramento_lenovo(self):
        ids = ["INTELAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2279"]
        self.assertTrue(dp.id_match(ids, "VEN_10EC&DEV_0257"))
        self.assertIsNone(dp.id_match(ids, "VEN_10EC&DEV_025"))

    def test_curinga(self):
        self.assertTrue(dp.id_match(["USB\\VID_1234&PID_0001&MI_00"], "USB\\VID_1234&PID_*"))

    def test_compat_de_classe_nao_entra(self):
        d = dev(["PCI\\VEN_8086&DEV_9DF0&SUBSYS_00308086"], ["PCI\\VEN_8086&DEV_9DF0", "PCI\\CC_0280"])
        self.assertIn("PCI\\VEN_8086&DEV_9DF0", d["mids"])
        self.assertNotIn("PCI\\CC_0280", d["mids"])

    def test_especificidade(self):
        self.assertEqual(dp.especificidade("PCI\\VEN_8086&DEV_9DF0&SUBSYS_00308086"), "exato")
        self.assertEqual(dp.especificidade("PCI\\VEN_8086&DEV_9DF0"), "chip")
        self.assertEqual(dp.especificidade("USB\\VID_8087&PID_0AAA"), "exato")
        self.assertEqual(dp.especificidade("ACPI\\PNP0C02"), "chip")
        self.assertEqual(dp.especificidade("ACPI\\INT3F0D"), "exato")


class Avaliacao(unittest.TestCase):
    def cand(self, src="OEM", ver="2.0.0.0", level="exato", pkg=False, **kw):
        c = {"cid": f"{src}:x{ver}", "source": src, "source_name": src, "title": "t", "version": ver,
             "level": level, "version_is_pkg": pkg}
        c.update(kw)
        return c

    def test_atualizar(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"])
        d["cands"] = [self.cand()]
        dp.avaliar(d)
        self.assertEqual(d["status"], "ATUALIZAR")

    def test_versao_do_pacote_vira_verificar(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"])
        d["cands"] = [self.cand(pkg=True)]
        dp.avaliar(d)
        self.assertEqual(d["status"], "VERIFICAR")

    def test_oem_tem_prioridade(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"])
        d["cands"] = [self.cand("CAT", "9.0.0.0"), self.cand("OEM", "1.5.0.0")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["source"], "OEM")
        self.assertEqual(d["alt_nova"]["source"], "CAT")

    def test_catalogo_so_chip_nao_recomenda(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"])
        d["cands"] = [self.cand("CAT", "9.0.0.0", level="chip")]
        dp.avaliar(d)
        self.assertIsNone(d["melhor"])

    def test_inbox_com_driver_especifico_substituir(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"], inf="netwtw.inf", cls="NET")
        d["cands"] = [self.cand()]
        dp.avaliar(d)
        self.assertEqual(d["status"], "SUBSTITUIR")

    def test_driver_de_classe_ok(self):
        d = dev(["USB\\VID_1&PID_2"], ["USB\\CLASS_03"], inf="input.inf", cls="HIDCLASS")
        dp.avaliar(d)
        self.assertEqual(d["status"], "OK")

    def test_generico_em_classe_critica(self):
        d = dev(["PCI\\VEN_10DE&DEV_1C8D&SUBSYS_1"], ["PCI\\CC_0300"], inf="display.inf", cls="DISPLAY")
        dp.avaliar(d)
        self.assertEqual(d["status"], "GENÉRICO")

    def test_wu_microsoft_descartado(self):
        d = dev(["PCI\\VEN_1&DEV_2&SUBSYS_3"])
        d["cands"] = [self.cand("WU", provider="Microsoft")]
        dp.avaliar(d)
        self.assertIsNone(d["melhor"])


class PecaTrocadaEEstavel(unittest.TestCase):
    """Leis: driver do FABRICANTE DA PEÇA (não só do PC) e só versões estáveis."""
    cand = Avaliacao.cand
    AX210 = ["PCI\\VEN_8086&DEV_2725&SUBSYS_00248086&REV_1A", "PCI\\VEN_8086&DEV_2725&SUBSYS_00248086",
             "PCI\\VEN_8086&DEV_2725&CC_028000", "PCI\\VEN_8086&DEV_2725"]

    def placa(self, hw=None, **kw):
        d = dev(hw or self.AX210, inf="oem12.inf", cls="NET", ver="22.100.0.3")
        d.update(pc_oem="lenovo", oem_consultado=True, **kw)
        return d

    def test_fabricante_da_peca_pelo_hardware_id(self):
        self.assertEqual(dp.fabricante_peca(dev(self.AX210))[0], "Intel")
        self.assertEqual(dp.fabricante_peca(dev(["PCI\\VEN_10EC&DEV_C822&SUBSYS_C82310EC"]))[0], "Realtek")
        self.assertEqual(dp.fabricante_peca(dev(["HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2292"]))[0], "Realtek")
        self.assertEqual(dp.fabricante_peca(dev(["USB\\VID_8087&PID_0032&REV_0000"]))[0], "Intel")
        self.assertEqual(dp.fabricante_peca(dev(["ACPI\\VEN_INT&DEV_34BB"]))[0], "Intel")
        self.assertEqual(dp.fabricante_peca(dev(["ACPI\\ELAN0001"]))[0], "ELAN")
        self.assertIsNone(dp.fabricante_peca(dev(["PCI\\VEN_ABCD&DEV_0001"])))

    def test_pacote_do_pc_so_pelo_chip_nao_e_exato(self):
        self.assertEqual(dp.especificidade_pacote("VEN_8086&DEV_2725"), "chip")
        self.assertEqual(dp.especificidade_pacote("PCI\\VEN_8086&DEV_2725&SUBSYS_00248086"), "exato")
        self.assertEqual(dp.especificidade_pacote("USB\\VID_8087&PID_0032"), "exato")

    def test_realtek_trocada_por_intel_usa_driver_da_intel(self):
        # catálogo Lenovo só tinha a Realtek original: nada casa; o Windows Update oferece o driver da Intel
        d = self.placa()
        d["cands"] = [self.cand("WU", "23.80.0.3", level="exato", provider="Intel"),
                      self.cand("CAT", "23.90.0.1", level="exato", provider="ReempacotadorQualquer")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["provider"], "Intel")
        self.assertEqual(d["status"], "ATUALIZAR")
        self.assertIn("fabricante da peça, Intel", d["motivo"])

    def test_mesmo_chip_com_pacote_do_pc_so_por_chip_prefere_o_fabricante_da_peca(self):
        d = self.placa()
        d["cands"] = [self.cand("OEM", "22.200.0.1", level="chip"), self.cand("CAT", "23.80.0.3", level="exato", provider="Intel")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["source"], "CAT")

    def test_so_pacote_do_pc_por_chip_ainda_serve(self):
        d = self.placa()
        d["cands"] = [self.cand("OEM", "22.200.0.1", level="chip")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["source"], "OEM")

    def test_wifi_original_vale_a_versao_mais_nova_da_intel(self):
        d = self.placa()
        d["cands"] = [self.cand("OEM", "22.200.0.1", level="exato"), self.cand("WU", "23.80.0.3", level="exato", provider="Intel")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["provider"], "Intel")
        self.assertFalse(d["peca_fora_do_catalogo"])

    def test_video_empate_fica_com_o_do_fabricante_do_pc(self):
        d = self.placa(["PCI\\VEN_8086&DEV_3EA0&SUBSYS_229217AA"])
        d["cls"] = "DISPLAY"
        d["cands"] = [self.cand("WU", "31.0.101.2125", level="exato", provider="Intel"), self.cand("OEM", "31.0.101.2125", level="exato")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["source"], "OEM")

    def test_audio_chipset_e_afins_ficam_com_o_validado_pelo_pc(self):
        for cls, hw in (("MEDIA", "HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2292"), ("SYSTEM", "PCI\\VEN_8086&DEV_9DA3&SUBSYS_229217AA"),
                        ("SCSIADAPTER", "PCI\\VEN_8086&DEV_9DD3&SUBSYS_229217AA")):
            d = self.placa([hw])
            d["cls"] = cls
            d["cands"] = [self.cand("OEM", "6.0.9049.1", level="exato"),
                          self.cand("WU", "6.0.9600.1", level="exato", provider="Realtek" if "10EC" in hw else "Intel")]
            dp.avaliar(d)
            self.assertEqual(d["melhor"]["source"], "OEM", cls)
            self.assertEqual(d["alt_nova"]["version"], "6.0.9600.1", cls)   # o relatório mostra a mais nova

    def test_audio_generico_do_windows_update_volta_para_o_do_pc(self):
        # o Windows Update pôs o Realtek genérico 6.0.9600 por cima do Lenovo 6.0.9049 (afinado para o modelo)
        d = self.placa(["HDAUDIO\\FUNC_01&VEN_10EC&DEV_0257&SUBSYS_17AA2292"])
        d.update(cls="MEDIA", ver="6.0.9600.1")
        d["cands"] = [self.cand("OEM", "6.0.9049.1", level="exato"), self.cand("WU", "6.0.9600.1", level="exato", provider="Realtek")]
        dp.avaliar(d)
        self.assertEqual(d["status"], "SUBSTITUIR")
        self.assertEqual(d["melhor"]["version"], "6.0.9049.1")
        self.assertTrue(d["melhor"]["voltar_versao"])
        rec = dp.recomendados({"devices": [d]})
        self.assertEqual(rec[0][1]["alvo_id"], d["id"])

    def test_chipset_mais_novo_nao_e_rebaixado(self):
        d = self.placa(["PCI\\VEN_8086&DEV_9DE8&SUBSYS_229217AA"])
        d.update(cls="SYSTEM", ver="30.100.2229.1")
        d["cands"] = [self.cand("OEM", "30.100.2031.2", level="exato")]
        dp.avaliar(d)
        self.assertEqual(d["status"], "OK")

    def test_confere_versao_depois_de_voltar(self):
        c = {"alvo_id": "HDAUDIO\\X\\1", "version": "6.0.9049.1"}
        orig = dp.versao_instalada
        try:
            dp.versao_instalada = lambda i: "6.0.9049.1"
            self.assertTrue(dp.conferir_versao(c, "ok")[0])
            dp.versao_instalada = lambda i: "6.0.9600.1"          # o Windows manteve o mais novo
            ok, msg = dp.conferir_versao(c, "ok")
            self.assertFalse(ok)
            self.assertIn("manteve", msg)
        finally:
            dp.versao_instalada = orig

    def test_firmware_do_windows_update_nunca_e_instalado(self):
        # caso real (ASUS M1502IA, Windows 11 26H2): o Windows Update ofereceu o firmware UEFI como "driver"
        d = dev(["UEFI\\RES_{F9BFFFE2-14C5-53A3-8FF4-C455A116F02F}&REV_312", "UEFI\\RES_{F9BFFFE2-14C5-53A3-8FF4-C455A116F02F}"],
                inf="c_firmware.inf", cls="FIRMWARE", ver="10.0.26100.4768")
        d["cands"] = [self.cand("WU", "10.1.2.312", level="chip", provider="ASUSTeK COMPUTER INC.",
                                title="ASUSTeK COMPUTER INC. - Firmware - 10.1.2.312", category="Firmware")]
        for rev in ("REV_312", "REV_305"):                          # mesmo com revisão mais nova oferecida: nada
            d["hwids"] = [h.replace("REV_312", rev) for h in d["hwids"]]
            dp.avaliar(d)
            self.assertEqual(d["status"], "OK")
            self.assertIn("Saúde do PC", d["motivo"])
            self.assertEqual(dp.recomendados({"devices": [d]}), [])
        self.assertFalse(dp.instalar_um(d["cands"][0])[0])         # nem pedindo direto

    def test_bios_nunca_baixada_nem_instalada(self):
        bios = {"cid": "LEN:n2iuj", "source": "OEM", "title": "BIOS Update", "category": "BIOS", "version": "1.80",
                "kind": "firmware", "url": "https://download.lenovo.com/x.exe"}
        with self.assertRaises(RuntimeError):
            dp.baixar_um(bios)
        ok, _, msg = dp.instalar_um(bios)
        self.assertFalse(ok)
        self.assertIn("não é instalado", msg)

    def test_terceiros_e_outro_fabricante_de_pc_descartados(self):
        d = self.placa()
        d["cands"] = [self.cand("CAT", "30.0.0.0", level="exato", provider="Dell"),
                      self.cand("CAT", "31.0.0.0", level="exato", provider="DriverPack Solutions")]
        dp.avaliar(d)
        self.assertIsNone(d["melhor"])

    def test_pacote_do_proprio_fabricante_do_pc_no_catalogo_serve_depois_do_da_peca(self):
        d = self.placa()
        d["cands"] = [self.cand("CAT", "23.90.0.0", level="exato", provider="Lenovo"),
                      self.cand("WU", "23.80.0.3", level="exato", provider="Intel Corporation")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["provider"], "Intel Corporation")

    def test_so_versao_estavel(self):
        d = self.placa()
        d["cands"] = [self.cand("WU", "24.0.0.1", level="exato", provider="Intel", title="Intel - Net - 24.0.0.1 Beta"),
                      self.cand("CAT", "23.99.0.1", level="exato", provider="Intel", products="Windows Insider Pre-Release"),
                      self.cand("CAT", "23.98.0.1", level="exato", provider="Intel", title="Intel Wi-Fi Driver Preview"),
                      self.cand("WU", "23.80.0.3", level="exato", provider="Intel", title="Intel - Net - 23.80.0.3")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["version"], "23.80.0.3")
        self.assertEqual(d["instaveis"], 3)

    def test_aparelho_da_microsoft_aceita_driver_da_microsoft(self):
        d = dev(["USB\\VID_045E&PID_0B12&REV_0503"], inf="", cls="XNACOMPOSITE", err=28)
        d["cands"] = [self.cand("WU", "10.0.22621.1", level="exato", provider="Microsoft")]
        dp.avaliar(d)
        self.assertEqual(d["status"], "INSTALAR")
        e = dev(["USB\\VID_046D&PID_085E"], inf="", err=28)            # webcam Logitech: Microsoft aqui é genérico
        e["cands"] = [self.cand("WU", "10.0.1.1", level="exato", provider="Microsoft")]
        dp.avaliar(e)
        self.assertEqual(e["status"], "SEM DRIVER")

    def test_periferico_conectado_sem_driver_recebe_o_do_fabricante(self):
        d = dev(["USB\\VID_03F0&PID_2B2A&MI_00"], inf="", cls="PRINTER", err=28)
        d["cands"] = [self.cand("WU", "61.240.1.24", level="exato", provider="HP"),
                      self.cand("CAT", "9.9.9.9", level="exato", provider="Drivers Universais Ltda")]
        dp.avaliar(d)
        self.assertEqual(d["status"], "INSTALAR")
        self.assertEqual(d["melhor"]["provider"], "HP")
        self.assertTrue(dp._alvo_catalogo(dict(d, bus="USBPRINT")))   # impressora USB sem driver também é procurada

    def test_pacote_sem_versao_nao_vence_versao_conhecida(self):
        # caso real (ASUS Vivobook M1502IA): Bluetooth Intel sem driver; o Windows Update ofereceu um pacote sem versão
        # (de 2015) e o Catálogo, o 22.200.0.2. Antes o "sem versão" vencia.
        d = dev(["USB\\VID_8087&PID_0A2B&REV_0010", "USB\\VID_8087&PID_0A2B"],
                ["USB\\COMPAT_VID_8087&CLASS_E0&SUBCLASS_01&PROT_01", "USB\\CLASS_E0"], inf="", cls="", err=28)
        d["cands"] = [self.cand("WU", "", level="exato", provider="Intel Corporation",
                                title="Intel Corporation - Bluetooth Controller - Intel(R) Wireless"),
                      self.cand("CAT", "22.200.0.2", level="exato", provider="Intel Corporation",
                                title="Intel Corporation - Bluetooth - 22.200.0.2")]
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["version"], "22.200.0.2")
        self.assertEqual(d["status"], "INSTALAR")
        so = dev(["USB\\VID_8087&PID_0A2B"], inf="", err=28)      # se só existir o sem versão, ele ainda serve
        so["cands"] = [dict(d["cands"][0])]
        dp.avaliar(so)
        self.assertEqual(so["melhor"]["source"], "WU")

    def test_classe_deduzida_quando_esta_sem_driver(self):
        self.assertEqual(dp.classe_pelos_ids(["USB\\COMPAT_VID_8087&CLASS_E0&SUBCLASS_01"]), "BLUETOOTH")
        self.assertEqual(dp.classe_pelos_ids(["PCI\\VEN_8086&DEV_24FD&CC_028000"]), "NET")
        self.assertEqual(dp.classe_pelos_ids(["PCI\\VEN_1002&CC_030000"]), "DISPLAY")
        self.assertEqual(dp.classe_pelos_ids(["USB\\CLASS_0E&SUBCLASS_01"]), "CAMERA")
        self.assertEqual(dp.classe_pelos_ids(["USB\\CLASS_07"]), "PRINTER")
        self.assertEqual(dp.classe_pelos_ids(["ACPI\\PNP0C0A"]), "")

    def test_asus_reconhecida_e_pacote_dela_aceito(self):
        self.assertEqual(dp.fabricante({"mfr": "ASUSTeK COMPUTER INC."}), "asus")
        self.assertNotIn("asus", dp.OEM_COM_DRIVERS)                  # a ASUS só informa a BIOS, não drivers por ID
        self.assertEqual(dp.fabricante_peca(dev(["ACPI\\ASUS2018"]))[0], "ASUS")
        self.assertEqual(dp.fabricante_peca(dev(["USB\\VID_0781&PID_5567"]))[0], "SanDisk")
        d = dev(["ACPI\\VEN_ELAN&DEV_1203"], inf="oem3.inf", cls="HIDCLASS", ver="16.0.0.20")
        d.update(pc_oem="asus", oem_consultado=False)
        d["cands"] = [self.cand("CAT", "16.0.0.31", level="exato", provider="ASUSTek COMPUTER INC.")]
        dp.avaliar(d)                                                   # touchpad ELAN com pacote da ASUS: serve
        self.assertEqual(d["status"], "ATUALIZAR")

    def test_estavel_nao_confunde_palavras(self):
        for t in ("Realtek Audio Driver", "Intel Graphics 31.0.101.5590", "AMD Chipset Software", "Precision Touchpad"):
            self.assertTrue(dp.estavel({"title": t}), t)


class Confirmacao(unittest.TestCase):
    def _com(self, resposta):
        import builtins
        orig = builtins.input
        builtins.input = (lambda _p: (_ for _ in ()).throw(EOFError)) if resposta is EOFError else (lambda _p: resposta)
        try:
            return dp.confirma("? ")
        finally:
            builtins.input = orig

    def test_sim_do_powershell_com_bom(self):
        self.assertTrue(self._com("\ufeffSIM"))       # caso real: "SIM" | python ... no Windows PowerShell 5.1
        self.assertTrue(self._com(" sim \r"))
        self.assertFalse(self._com("não"))
        self.assertFalse(self._com(EOFError))          # entrada acabou: cancela, sem travar com erro


class ModoAutomatico(unittest.TestCase):
    def test_recomendados_so_o_que_e_seguro(self):
        mk = Avaliacao.cand
        a = dev(["PCI\\VEN_1&DEV_1&SUBSYS_1"])          # ATUALIZAR -> entra
        a["cands"] = [mk(None)]
        b = dev(["PCI\\VEN_1&DEV_2&SUBSYS_1"])          # versão só do pacote -> VERIFICAR, fica fora
        b["cands"] = [mk(None, pkg=True)]
        c = dev(["PCI\\VEN_1&DEV_3&SUBSYS_1"])          # firmware -> nunca automático
        c["cands"] = [mk(None, kind="firmware")]
        d = dev(["PCI\\VEN_1&DEV_4&SUBSYS_1"])          # mesmo pacote de 'a' -> instala uma vez
        d["cands"] = [dict(a["cands"][0])]
        for x in (a, b, c, d):
            dp.avaliar(x)
        rec = dp.recomendados({"devices": [a, b, c, d]})
        self.assertEqual([r[0]["name"] for r in rec], [a["name"]])


if __name__ == "__main__":
    unittest.main()
