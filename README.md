# DriverPrecision

Identifica o hardware do PC e localiza o driver **correto** para cada dispositivo — o publicado para aquele modelo / Hardware ID exato. Nada de pacote genérico.

Requisitos: Windows 10/11 e Python 3.10+ (só stdlib). Nada a instalar via pip.

## Uso

```
python driverprecision.py scan                 # somente leitura (padrão)
python driverprecision.py baixar ID [ID ...]   # baixa e valida, não instala
python driverprecision.py instalar ID [ID ...] # terminal admin; pede "SIM"; cria ponto de restauração
```

Os IDs (`LEN:...`, `DELL:...`, `HP:...`, `WU:...`, `CAT:...`) aparecem no relatório.
Saída em `DriverPrecision_saida\` (relatório HTML + `ultimo_scan.json`). Cache em `%LOCALAPPDATA%\DriverPrecision\cache`.

Opções do scan: `--sem-oem`, `--sem-wu`, `--sem-catalogo`, `--nao-abrir`.

## Como identifica

1. **Inventário** (WMI): fabricante, modelo, SKU, placa-mãe, BIOS, build do Windows; por dispositivo, Hardware IDs, Compatible IDs, erro do Gerenciador de Dispositivos e driver em uso (versão, data, provedor, INF).
   - INF `oemNN.inf` = driver de fabricante; outro nome = driver inbox (genérico) do Windows.
   - O casamento usa os Hardware IDs + Compatible IDs que ainda identificam o chip (`VEN&DEV`, `VID&PID`). IDs só de classe (`PCI\CC_`, `USB\CLASS_`) nunca entram.

2. **Fontes, por ordem de confiança**

| # | Fonte | Chave de busca | Integridade |
|---|-------|----------------|-------------|
| 1 | Lenovo `catalog/<MT>_Win11.xml` | Machine Type + Hardware ID + versão do driver (`_Driver`) | SHA-256 do descritor e do instalador |
| 1 | Dell `CatalogPC.cab` | SystemSKU (System ID) + `PCIInfo` + SO | MD5 do catálogo + Authenticode |
| 1 | HP HPIA `platformList` / `ref/<plat>_64_<SO>.cab` | Platform ID (placa) + Hardware ID + SO | SHA-256 do softpaq |
| 2 | Windows Update (API WUA, só busca) | Hardware ID que o próprio Windows casou | assinado pelo WU |
| 3 | Microsoft Update Catalog | Hardware ID mais específico (SUBSYS / VID&PID) | Authenticode |

   - **Catalog**: a busca do site é textual, então todo resultado é conferido na página do pacote: o Hardware ID do aparelho tem que estar **literalmente** em "Supported Hardware IDs". Se não estiver, ou se o provedor for a própria Microsoft (driver genérico), o pacote é descartado. Resultado que só bate no chip (`VEN&DEV` sem `SUBSYS`) não é recomendado.
   - PC montado ou marca sem catálogo público: usa as fontes 2 e 3 e mostra a placa-mãe para buscar no site do fabricante dela.

3. **Status no relatório**

| Status | Significado |
|---|---|
| SEM DRIVER / INSTALAR | dispositivo com erro ou sem driver; INSTALAR = driver exato encontrado |
| SUBSTITUIR | está com driver inbox genérico e existe driver específico |
| ATUALIZAR | a fonte informa versão de driver mais nova que a instalada |
| VERIFICAR | a fonte só informa a versão do *pacote* (não do driver): confira nas notas |
| GENÉRICO | inbox em classe crítica (vídeo, rede, áudio...) e nenhuma fonte publica driver específico |
| OK | igual/mais novo, ou driver de classe padrão do Windows (USB hub, HID, NVMe padrão...) — nesses o driver de classe é o correto e o fabricante não publica outro |

Se o fabricante do PC tiver driver e houver outro mais novo fora dele (ex.: direto da Intel no Catalog), o relatório mostra os dois, mas recomenda o do fabricante.

## Instalação (comando `instalar`)

- Exige terminal administrador e confirmação digitando `SIM`; tenta criar ponto de restauração antes.
- Todo arquivo baixado é validado (hash do catálogo do fabricante + assinatura digital válida). Se falhar, o arquivo é apagado e nada roda.
- **BIOS e firmware nunca são instalados automaticamente**: use `baixar`, leia as notas e rode manualmente, com carregador conectado.
- Lenovo: roda o `ExtractCommand` e o `Install` do descritor oficial. Dell: `DUP.exe /s`. HP: `spXXXX.exe /s`. Catalog: `expand` + `pnputil /add-driver /install`. WU: API do Windows Update.

## Limitações conhecidas

- Dell não publica Hardware ID de alguns pacotes (áudio, USB etc.): esses aparecem na seção "pacotes do modelo" como VERIFICAR.
- Lenovo consumer (IdeaPad/Legion) nem sempre tem catálogo público por MT: cai para WU + Catalog.
- Placas de vídeo dedicadas (NVIDIA/AMD) em PCs montados: o Catalog tem os drivers WHQL, mas o mais recente costuma sair antes no site do fabricante da GPU.
