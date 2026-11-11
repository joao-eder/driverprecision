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
