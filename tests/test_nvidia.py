"""Fonte oficial da NVIDIA: identificação do produto, driver Game Ready WHQL, comparação de versões. Sem internet."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision as dp  # noqa: E402
from test_core import dev  # noqa: E402

SERIES = [("GeForce RTX 50 Series (Notebooks)", "133"), ("GeForce RTX 30 Series (Notebooks)", "123"),
          ("GeForce RTX 30 Series", "120"), ("GeForce GTX 16 Series (Notebooks)", "112"), ("GeForce GTX 16 Series", "107"),
          ("NVIDIA RTX PRO / RTX / Quadro", "3")]
PRODUTOS = {"123": [("GeForce RTX 3060 Laptop GPU", "938"), ("GeForce RTX 3070 Laptop GPU", "939")],
            "120": [("NVIDIA GeForce RTX 3060", "933")],
            "112": [("GeForce GTX 1650", "889")], "107": [("NVIDIA GeForce GTX 1650", "883")]}


def resposta(versao="581.57", beta="0", whql="1", url="https://us.download.nvidia.com/Windows/581.57/581.57-notebook-win10-win11-64bit-international-dch-whql.exe"):
    return json.dumps({"Success": "1", "IDS": [{"downloadInfo": {
        "Success": "1", "ID": "285321", "Name": "GeForce%20Game%20Ready%20Driver", "Version": versao, "IsBeta": beta,
        "IsWHQL": whql, "ReleaseDateTime": "Tue Oct 21, 2025", "DownloadURL": url}}]}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = (dp._nv_lista, dp.http_get)
        dp._nv_lista = lambda tipo, pai="": SERIES if tipo == 2 else PRODUTOS.get(str(pai), [])
        self.resp = resposta()
        dp.http_get = lambda url, **k: self.resp

    def tearDown(self):
        dp._nv_lista, dp.http_get = self._orig


class Versoes(unittest.TestCase):
    def test_conversao_nvidia_windows(self):
        self.assertEqual(dp.nv_de_windows("32.0.15.6636"), "566.36")
        self.assertEqual(dp.nv_de_windows("27.21.14.5749"), "457.49")   # o que o Catálogo oferecia para a GTX 1650
        self.assertEqual(dp.nv_de_windows("566.36"), "566.36")
        self.assertEqual(dp.windows_de_nv("581.57", "32.0"), "32.0.15.8157")
        self.assertEqual(dp.nv_de_windows(dp.windows_de_nv("610.05")), "610.05")


class Produto(Base):
    def test_notebook_acha_a_serie_de_notebook(self):
        self.assertEqual(dp.nv_produto("NVIDIA GeForce RTX 3060 Laptop GPU", True), ("123", "938", "GeForce RTX 3060 Laptop GPU"))
        self.assertEqual(dp.nv_produto("NVIDIA GeForce GTX 1650", True)[:2], ("112", "889"))
        self.assertEqual(dp.nv_produto("NVIDIA GeForce GTX 1650 with Max-Q Design", True)[:2], ("112", "889"))

    def test_desktop_acha_a_serie_de_desktop(self):
        self.assertEqual(dp.nv_produto("NVIDIA GeForce RTX 3060", False)[:2], ("120", "933"))
        self.assertEqual(dp.nv_produto("NVIDIA GeForce GTX 1650", False)[:2], ("107", "883"))

    def test_desconhecida(self):
        self.assertIsNone(dp.nv_produto("NVIDIA GeForce RTX 9999", False))


class Fonte(Base):
    def gpu(self, ver="27.21.14.5749"):
        d = dev(["PCI\\VEN_10DE&DEV_1F99&SUBSYS_3A4317AA&REV_A1", "PCI\\VEN_10DE&DEV_1F99"], inf="oem20.inf",
                cls="DISPLAY", ver=ver)
        d["name"] = "NVIDIA GeForce GTX 1650"
        return d

    def test_driver_whql_vira_candidato_e_vence_o_do_catalogo(self):
        d = self.gpu()
        d["cands"].append({"cid": "CAT:x", "source": "CAT", "source_name": "Microsoft Update Catalog", "title": "NVIDIA - Display",
                           "version": "27.21.14.5749", "level": "exato", "provider": "NVIDIA"})
        r = dp.fonte_nvidia({"build": 26100, "notebook": True}, [d])
        self.assertIn("581.57", r)
        nv = [c for c in d["cands"] if c["source"] == "NV"][0]
        self.assertEqual((nv["nv_version"], nv["signer"], nv["provider"]), ("581.57", "NVIDIA", "NVIDIA"))
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["source"], "NV")
        self.assertEqual(d["status"], "ATUALIZAR")
        self.assertIn("457.49", dp.nv_de_windows(d["ver"]))

    def test_prefixo_diferente_nao_engana_a_comparacao(self):
        d = self.gpu(ver="32.0.15.8157")          # já tem o 581.57 (prefixo 32.0)
        d["cands"].append({"cid": "CAT:y", "source": "CAT", "source_name": "Catalog", "title": "NVIDIA - Display",
                           "version": "31.0.15.9000", "level": "exato", "provider": "NVIDIA"})   # 590.00, prefixo antigo
        dp.fonte_nvidia({"build": 26100, "notebook": True}, [d])
        dp.avaliar(d)
        self.assertEqual(dp.nv_de_windows(d["melhor"]["version"]), "590.00")
        self.assertEqual(d["status"], "ATUALIZAR")

    def test_beta_nao_whql_e_link_estranho_recusados(self):
        for r in (resposta(beta="1"), resposta(whql="0"), resposta(url="https://exemplo.com/driver.exe")):
            self.resp = r
            d = self.gpu()
            dp.fonte_nvidia({"build": 26100, "notebook": True}, [d])
            self.assertFalse(d["cands"])

    def test_confere_versao_pelo_numero_da_nvidia(self):
        c = {"source": "NV", "alvo_id": "PCI\\X", "version": "32.0.15.8157", "nv_version": "581.57"}
        orig = dp.versao_instalada
        try:
            dp.versao_instalada = lambda i: "33.0.15.8157"     # o Windows pode trocar o prefixo
            self.assertTrue(dp.conferir_versao(c, "ok")[0])
            dp.versao_instalada = lambda i: "32.0.15.6636"
            ok, msg = dp.conferir_versao(c, "ok")
            self.assertFalse(ok)
            self.assertIn("566.36", msg)
        finally:
            dp.versao_instalada = orig

    def test_placa_amd_ou_intel_nao_consulta_nvidia(self):
        d = dev(["PCI\\VEN_8086&DEV_3EA0&SUBSYS_229217AA"], cls="DISPLAY")
        self.assertFalse(dp.eh_nvidia(d))
        self.assertIn("nenhuma placa", dp.fonte_nvidia({"build": 26100}, [d]))


if __name__ == "__main__":
    unittest.main()
