# Contribuindo

Contribuições são bem-vindas: fabricantes novos, correções de casamento, traduções e relatórios de bug.

## Regras do projeto

1. **Precisão acima de cobertura.** Um driver só é recomendado se a fonte o liga ao Hardware ID ou ao modelo exato. Na dúvida, o status é `VERIFICAR`, nunca `ATUALIZAR`.
2. **Nada de driver genérico.** Pacotes cujo provedor é a própria Microsoft, ou que só casam no chip (`VEN&DEV` sem `SUBSYS`), não são recomendados.
3. **Somente stdlib do Python** + ferramentas nativas do Windows (PowerShell, `expand.exe`, `pnputil`). Isso mantém o `.exe` pequeno e auditável.
4. **`scan` é somente leitura.** Nada que altere o sistema pode rodar fora de `instalar`.
5. **Todo download é validado** (hash publicado pela fonte e/ou Authenticode válido) antes de ser executado.

## Ambiente

```
git clone https://github.com/joao-eder/driverprecision
cd driverprecision
python -m unittest discover -s tests -v
python driverprecision.py scan --nao-abrir
```

## Adicionando um fabricante

Crie uma função `fonte_<nome>(sysinfo, devs, sistema) -> str` em `driverprecision.py`:

- Use `sysinfo` (modelo, SKU, placa-mãe, BIOS, build) para achar o catálogo **do modelo exato**.
- Para cada pacote com Hardware IDs, case com `id_match(d["mids"], id_do_pacote)` e adicione em `d["cands"]` um dict com pelo menos: `cid` (`"PREFIXO:id"`), `source="OEM"`, `source_name`, `title`, `version`, `date`, `url`, `match_id`, `level` e `sha256` ou `md5` quando a fonte publicar.
- Se a fonte só der a versão do pacote (e não a do driver), marque `version_is_pkg=True`.
- BIOS/firmware e pacotes sem Hardware ID vão para a lista `sistema`, com `status`.
- Retorne uma linha de resumo (`"ok - N pacotes, M associações"`).
- Registre em `fabricante()` e no dicionário de fontes dentro de `scan()`.
- Adicione testes em `tests/` com XML de exemplo (sem dados pessoais).

## Adicionando um ajuste de otimização

Acrescente um dict em `AJUSTES` (`driverprecision_otimiza.py`):

```python
{"id": "meu_ajuste", "cat": "Placa de vídeo", "nome": "Nome curto", "risco": "baixo|médio|alto",
 "reboot": True,                      # precisa reiniciar?
 "reg": [("HKLM", r"SYSTEM\...", "Valor", DW, 1)],   # DW = DWORD, SZ = texto
 "desc": "O que faz e o que o usuário ganha/perde, em português simples."}
```

O backup do valor original, o estado (Ativo/Padrão/Parcial) e o desfazer são automáticos. Para ajustes que dependem de comando (powercfg, bcdedit) ou de chaves descobertas na hora (por GPU, por placa de rede), use `"tipo"` e trate em `regs_do_ajuste`/`aplicar`/`desfazer`. Explique de onde vem o ganho no PR; ajuste que reduz segurança leva `"seguranca": True`.

## Adicionando um componente de jogos

Acrescente um dict em `COMPONENTES` (`driverprecision_jogos.py`) com `check` (função que devolve `("OK"|"FALTA"|"DESATUALIZADO", detalhe)`), `url` **oficial**, `args` silenciosos e `signer` (texto que deve aparecer no assinante da assinatura digital).

## Pull requests

- Um assunto por PR, com testes passando (`python -m unittest discover -s tests`).
- Descreva em que máquina testou (fabricante, modelo, Windows). **Não anexe** o `ultimo_scan.json` nem o relatório completo: eles contêm o número de série do PC.
- Atualize o `CHANGELOG.md` na seção `[Não lançado]`.

## Lançando uma versão (mantenedores)

1. Atualize `VERSION` em `driverprecision.py` e o `CHANGELOG.md`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`
3. O workflow `release.yml` testa, gera o `.exe`, o `.zip` e o `SHA256SUMS.txt` e publica a release.
