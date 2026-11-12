# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [1.2.0] - 2026-11-12

### Adicionado
- 12 ajustes novos na aba **Otimização avançada** (agora são 30), todos com backup e desfazer:
  - Windows: desligar Inicialização rápida, telemetria (serviço DiagTrack), anúncios/dicas/apps sugeridos, busca na web (Bing) no Menu Iniciar, atraso dos programas de inicialização, hibernação.
  - Disco (categoria nova): garantir TRIM do SSD, desligar registro de último acesso (NTFS).
  - Rede: não compartilhar atualizações com outros PCs (Otimização de Entrega P2P), desligar economia de energia do Wi-Fi.
  - Placa de vídeo: desligar economia de energia do PCIe (ASPM) na tomada.
  - Mouse e teclado: repetição do teclado mais rápida.
- Desfazer da hibernação só religa se ela estava ligada antes.

## [1.1.0] - 2026-11-11

### Adicionado
- Aba **Jogos**: verifica e instala o que os jogos precisam para abrir — Visual C++ 2005 a 2022 (x86/x64), DirectX 9/10/11 legado (d3dx9, XInput 1.3, XAudio 2.7), .NET Framework 3.5/4.8, .NET Desktop Runtime 8/10, XNA 4.0, OpenAL, WebView2, DirectPlay (opcional) e checagem do Vulkan. Downloads só de links oficiais, com assinatura digital conferida.
- Detecta Visual C++ 2015-2022 abaixo de 14.40 (jogos compilados com VS 2022 17.10+ fecham ao abrir com runtime antigo).
- Aba **Otimização avançada**: 18 ajustes em 7 categorias (energia/CPU, placa de vídeo, MMCSS, rede, mouse, Windows, segurança x desempenho), cada um com risco, estado atual e explicação. Backup do valor original, ponto de restauração, "Desfazer marcados" e "Desfazer tudo".
- Ajuste de timer (BCD) bloqueado com BitLocker ativo, para não disparar pedido de chave de recuperação.

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

[1.2.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.2.0
[1.1.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.1.0
[1.0.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.0.0
