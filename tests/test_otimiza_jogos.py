"""Otimização (aplicar/desfazer com registro falso) e regras dos componentes de jogos. Não toca no sistema."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import driverprecision_jogos as jg  # noqa: E402
import driverprecision_otimiza as ot  # noqa: E402


class RegistroFalso:
    def __init__(self):
        self.d = {}

    def get(self, h, p, n):
        k = (h, p.lower(), n.lower())
        return (True, *self.d[k]) if k in self.d else (False, None, None)

    def set(self, h, p, n, t, v):
        self.d[(h, p.lower(), n.lower())] = (t, v)

    def delete(self, h, p, n):
        self.d.pop((h, p.lower(), n.lower()), None)

    def subkeys(self, h, p):
        return []


class Otimizacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._reg, self._bk = ot.REG, ot.BACKUP
        ot.REG = RegistroFalso()
        ot.BACKUP = Path(self.tmp.name) / "bk.json"

    def tearDown(self):
        ot.REG, ot.BACKUP = self._reg, self._bk
        self.tmp.cleanup()

    def test_aplicar_e_desfazer_volta_ao_original(self):
        mm = ot.MM
        ot.REG.set("HKLM", mm, "SystemResponsiveness", "DWORD", 20)  # valor de fábrica; o resto não existe
        antes = dict(ot.REG.d)
        ot.aplicar("mmcss")
        self.assertEqual(ot.estado(ot.POR_ID["mmcss"]), "ATIVO")
        self.assertEqual(ot.REG.get("HKLM", mm, "SystemResponsiveness")[2], 0)
        ot.desfazer("mmcss")
        self.assertEqual(ot.REG.d, antes)  # inclusive apagou o que não existia
        self.assertEqual(ot.aplicados(), [])

    def test_aplicar_duas_vezes_preserva_backup_original(self):
        p = r"SYSTEM\CurrentControlSet\Control\PriorityControl"
        ot.REG.set("HKLM", p, "Win32PrioritySeparation", "DWORD", 2)
        ot.aplicar("prio_sep")
        ot.aplicar("prio_sep")
        ot.desfazer("prio_sep")
        self.assertEqual(ot.REG.get("HKLM", p, "Win32PrioritySeparation")[2], 2)

    def test_estado_parcial(self):
        ot.REG.set("HKCU", ot.GCS, "GameDVR_Enabled", "DWORD", 0)
        self.assertEqual(ot.estado(ot.POR_ID["game_dvr"]), "PARCIAL")

    def test_todos_os_ajustes_tem_campos(self):
        for a in ot.AJUSTES:
            self.assertIn(a["risco"], ("baixo", "médio", "alto"), a["id"])
            self.assertTrue(a["desc"] and a["cat"] and a["nome"], a["id"])
            self.assertTrue(a.get("reg") or a.get("tipo"), a["id"])
            for r in a.get("reg", []):
                self.assertIn(r[0], ("HKCU", "HKLM"))
                self.assertIn(r[3], ("DWORD", "SZ"))


class Jogos(unittest.TestCase):
    def test_pendentes_ignora_opcional_e_info(self):
        itens = [{"id": "a", "status": "FALTA", "instalavel": True, "opcional": False},
                 {"id": "b", "status": "DESATUALIZADO", "instalavel": True, "opcional": False},
                 {"id": "c", "status": "FALTA", "instalavel": True, "opcional": True},
                 {"id": "d", "status": "INFO", "instalavel": False, "opcional": False},
                 {"id": "e", "status": "OK", "instalavel": True, "opcional": False}]
        self.assertEqual(jg.pendentes(itens), ["a", "b"])

    def test_componentes_tem_fonte_oficial(self):
        for c in jg.COMPONENTES:
            if c.get("tipo") in ("info", "dism"):
                continue
            self.assertTrue(c["url"].startswith("https://"), c["id"])
            self.assertTrue(c.get("signer"), c["id"])


if __name__ == "__main__":
    unittest.main()
