# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [1.3.3] - 2026-11-16

### Alterado
- Otimização: o aviso de reinício (↻) deixou de ser uma etiqueta fixa. Agora só aparece nos ajustes aplicados ou desfeitos depois da última inicialização do Windows, e some ao reiniciar.

## [1.3.2] - 2026-11-16

### Adicionado
- Logo do app (controle + engrenagem): ícone do `.exe`, da janela e da barra de tarefas, e no menu lateral.

## [1.3.1] - 2026-11-16

Versão de correções, depois de testar tudo num Windows de verdade (Windows Server 2022 e 2025 descartáveis do GitHub, como administrador): aplicar e desfazer os 30 ajustes, baixar e instalar os componentes de jogos, consultar Lenovo/Dell/HP, verificar drivers e abrir a janela e o .exe.

### Corrigido
- **Desfazer dos ajustes de energia** (estacionamento de núcleos, USB, Wi-Fi, PCIe) falhava com "Acesso negado": o Windows protege as chaves dos planos de energia. Agora a leitura e o desfazer passam pelo `powercfg`.
- **Conferência de assinatura digital falhava** quando o programa era aberto a partir do PowerShell 7, bloqueando a instalação de componentes e drivers.
- Ajuste de energia que não existe no PC (ex.: Wi-Fi em desktop) aparecia como aplicado; agora aparece "Não se aplica".
- Drivers Lenovo: instalação falhava se a pasta do usuário tivesse espaço no nome.
- Pacotes Lenovo que reiniciam o PC sozinhos ficam fora da instalação automática.
- Texto com acento na saída de um instalador podia interromper a instalação.
- Erros do Windows no plano de energia e no `bcdedit` deixam de ser relatados como sucesso.
- Janela cabia mal em telas pequenas (1366x768 e menores): agora abre no tamanho da tela, centralizada, com os botões sempre visíveis e os textos quebrando na largura certa.

### Adicionado
- Teste de integração automático em Windows real a cada alteração do código (`tests/integracao_windows.py`).

## [1.3.0] - 2026-11-16

### Alterado
- Interface nova: tema escuro, menu lateral grande com ícones (Drivers, Jogos, Otimização) no lugar das abas pequenas, listas e botões redesenhados, barra de título escura no Windows 10/11.
- A release agora é publicada sozinha quando o `main` recebe uma versão nova: o workflow cria a tag, compila e publica o .exe.
- Na Otimização, só os ajustes de risco alto ficam em vermelho; nos Jogos, só o que falta ou está desatualizado fica colorido.

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

[1.3.3]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.3
[1.3.2]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.2
[1.3.1]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.1
[1.3.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.0
[1.2.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.2.0
[1.1.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.1.0
[1.0.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.0.0
