# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [1.0.0] - 2026-11-11

### Adicionado
- Janela para usuário comum: **Verificar agora** → lista já marcada → **Instalar**. Pede administrador uma vez, cria ponto de restauração, baixa, valida e instala sozinho; oferece reiniciar quando necessário.
- Modo `auto` na linha de comando (verifica e instala os recomendados sem perguntas).
- Inventário de hardware via WMI: modelo, SKU, placa-mãe, BIOS, build do Windows, Hardware/Compatible IDs e driver em uso de cada dispositivo físico.
- Fonte OEM Lenovo (catálogo por Machine Type, versão do driver por Hardware ID, SHA-256).
- Fonte OEM Dell (`CatalogPC.cab` por SystemSKU e `PCIInfo`, MD5).
- Fonte OEM HP (HPIA platformList + arquivo de referência por Platform ID e SO, SHA-256).
- Fonte Windows Update (API WUA, só busca; usa o Microsoft Update quando registrado).
- Fonte Microsoft Update Catalog com verificação pela lista oficial de *Supported Hardware IDs*.
- Classificação: SEM DRIVER, INSTALAR, SUBSTITUIR, ATUALIZAR, VERIFICAR, GENÉRICO, OK.
- Relatório HTML (claro/escuro, filtros) e estado em JSON.
- Comandos `baixar` (hash + Authenticode) e `instalar` (admin, confirmação, ponto de restauração; BIOS/firmware nunca automático).
- `DriverPrecision.exe` gerado pelo GitHub Actions a cada release.

[1.0.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.0.0
