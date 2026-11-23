"""Fonte oficial da AMD: lista de chips aceitos, só WHQL, comparação pela versão de lançamento da AMD. Sem internet."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision as dp  # noqa: E402
from test_core import dev  # noqa: E402

INDICE = {"ADDL_VERSION": "1.0", "Consumer_Whql_Win10": {"version": "26.20.29.02-261116a",
          "url": "https://www2.ati.com/drivers/installer/json/DrvDldDetails_Consumer_WHQL_Win11.json"},
          "Consumer_Beta_Win10": {"version": "26.20.31.01", "url": "https://www2.ati.com/drivers/installer/json/beta.json"}}
PACOTES = [{"edition": "AMD Software: Adrenalin Edition", "externalbuildversion": "26.11.2",
            "internalbuildversion": "26.20.29.02-261116a-206168C-AMD-Software-Adrenalin-Edition",
            "fullbuild": "https://www2.ati.com/drivers/whql-amd-software-adrenalin-edition-26.11.2-win11-c.exe",
            "fullbuildfilesize": "1678.32", "releasedate": "11/18/2026",
            "releasenotes": "https://www.amd.com/en/resources/support-articles/release-notes/rn-rad-win-26-11-2.html",
            "skus": ["7480-CF", "73FF-C7", "15BF-C1"]},
           {"edition": "AMD Software: Adrenalin Edition", "externalbuildversion": "25.9.1",
            "internalbuildversion": "25.10.13.01-250901a-Legacy", "fullbuild": "https://www2.ati.com/drivers/legacy-25.9.1.exe",
            "skus": ["1636-C7", "15D8-C1"]}]


class Base(unittest.TestCase):
    def setUp(self):
        self.pedidos = []

        def falso(url, nome, ttl_h=24, timeout=90):
            self.pedidos.append(url)
            if "version.json" in url:
                return json.dumps(INDICE).encode()
            if "beta" in url:
                raise AssertionError("o pacote beta não pode ser consultado")
            return json.dumps(PACOTES).encode()
        self._orig = (dp.cached, dp.amd_versao_instalada)
        dp.cached = falso
        self.instalada = "26.10.20.01-260810a-ABC"
        dp.amd_versao_instalada = lambda i: self.instalada

    def tearDown(self):
        dp.cached, dp.amd_versao_instalada = self._orig

    def placa(self, dev_id="7480", rev="CF"):
        d = dev([f"PCI\\VEN_1002&DEV_{dev_id}&SUBSYS_0E361002&REV_{rev}", f"PCI\\VEN_1002&DEV_{dev_id}"], cls="DISPLAY",
                inf="oem30.inf", ver="32.0.21020.1001")
        d["name"] = "AMD Radeon RX 7600"
        return d


class Amd(Base):
    def test_sku(self):
        self.assertEqual(dp.amd_sku(self.placa()), "7480-CF")

    def test_placa_na_lista_recebe_o_whql_mais_novo(self):
        d = self.placa()
        d["cands"].append({"cid": "CAT:x", "source": "CAT", "source_name": "Catalog", "title": "AMD - Display",
                           "version": "32.0.21030.2001", "level": "exato", "provider": "Advanced Micro Devices, Inc."})
        r = dp.fonte_amd({"build": 26100}, [d])
        self.assertIn("26.11.2", r)
        dp.avaliar(d)
        self.assertEqual(d["status"], "ATUALIZAR")
        b = d["melhor"]
        self.assertEqual((b["source"], b["amd_version"], b["signer"]), ("AMD", "26.11.2", "Advanced Micro Devices"))
        self.assertTrue(b["interativo"])
        self.assertIn("26.10.20.01", d["motivo"])
        self.assertFalse(any("beta" in u for u in self.pedidos))

    def test_placa_antiga_usa_a_linha_dela(self):
        d = self.placa("1636", "C7")                 # Radeon integrado do ASUS M1502IA
        d["name"] = "AMD Radeon(TM) Graphics"
        self.instalada = "25.10.12.01-250801a"
        dp.fonte_amd({"build": 26100}, [d])
        dp.avaliar(d)
        self.assertEqual(d["melhor"]["amd_version"], "25.9.1")

    def test_placa_fora_da_lista_nao_recebe_nada_do_site(self):
        d = self.placa("9999", "00")
        r = dp.fonte_amd({"build": 26100}, [d])
        self.assertIn("não consta", r)
        self.assertFalse(d["cands"])

    def test_ja_atualizado_nao_propoe(self):
        d = self.placa()
        self.instalada = "26.20.29.02-261116a"
        dp.fonte_amd({"build": 26100}, [d])
        dp.avaliar(d)
        self.assertNotEqual(d["status"], "ATUALIZAR")
        self.assertFalse(any(c["source"] == "AMD" for c in d["cands"]))

    def test_sem_versao_instalada_legivel_nao_compara(self):
        d = self.placa()
        self.instalada = ""
        r = dp.fonte_amd({"build": 26100}, [d])
        self.assertIn("não comparado", r)
        dp.avaliar(d)
        self.assertFalse(d.get("melhor") and d["melhor"]["source"] == "AMD")

    def test_confere_versao_depois_de_instalar(self):
        c = {"source": "AMD", "alvo_id": "PCI\\X", "version": "26.20.29.02", "amd_version": "26.11.2"}
        self.instalada = "26.20.29.02-261116a-206168C"
        self.assertTrue(dp.conferir_versao(c, "ok")[0])
        self.instalada = "26.10.20.01-260810a"
        ok, msg = dp.conferir_versao(c, "ok")
        self.assertFalse(ok)
        self.assertIn("26.11.2", msg)


if __name__ == "__main__":
    unittest.main()
