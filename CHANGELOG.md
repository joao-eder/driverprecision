# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [1.4.5] - 2026-11-22

### Adicionado
- Botões **"Marcar todos"** e **"Desmarcar todos"** acima das listas das telas Drivers, Jogos, Otimização e Escritório (só marcam o que tem caixinha: instalados, "não se aplica" e bloqueados pela empresa ficam de fora). "Marcar recomendados" foi para a mesma barra.
- **BIOS sempre visível** na tela de Drivers: versão instalada e se é a mais nova publicada pelo fabricante. Só aviso.
- **ASUS:** a versão de BIOS mais nova publicada para o modelo é conferida no site de suporte da ASUS (só a lista de versões; nenhum arquivo é baixado).

### Alterado
- **BIOS/firmware nunca é baixado, de nenhuma marca** — nem pela linha de comando. O programa só lê a versão instalada e a lista de versões publicadas.
- **Proteção do sistema (pontos de restauração):** o ajuste que a ligava foi retirado; o programa não muda essa configuração. A Saúde do PC só verifica e sugere como ligar.

## [1.4.4] - 2026-11-21

### Corrigido
- **Ajustes de energia conferidos na tomada e na bateria.** Caso real (ASUS M1502IA): o Wi-Fi estava sem economia na tomada mas com economia média na bateria, e o app mostrava "Ativo". Agora mostra "Parcial" quando só um dos dois bate.
- **Plano Desempenho Máximo leva os ajustes de energia já aplicados** (Wi-Fi, PCIe, USB, núcleos). Esses ajustes valem por plano; ao trocar de plano, o novo vinha com o padrão de fábrica.

## [1.4.3] - 2026-11-21

### Corrigido
- **Firmware oferecido pelo Windows Update como "driver" era instalado.** Caso real (ASUS Vivobook M1502IA, Windows 11 26H2): o firmware UEFI da ASUS veio como driver do dispositivo "Firmware do Sistema". Agora tudo do firmware do sistema (barramento UEFI, classe Firmware, pacotes de firmware) segue a regra da BIOS: nunca é instalado; se a revisão oferecida for mais nova que a instalada (`REV_` do Hardware ID), aparece só como aviso, com a versão disponível.

## [1.4.2] - 2026-11-21

### Adicionado
- Ajuste **"Windows Update não troca drivers sozinho"** (telas Otimização e Escritório, categoria Windows): política oficial do Windows que impede o Windows Update de instalar ou trocar drivers por conta própria. As atualizações de segurança continuam; o DriverPrecision passa a buscar os drivers no Catálogo da Microsoft.

### Corrigido
- **Áudio com o driver genérico do Windows Update:** quando o Windows Update põe o driver genérico do fabricante da peça (ex.: Realtek) por cima do adaptado pelo fabricante do PC, o app não diz mais "OK": propõe voltar para a versão validada pelo fabricante do PC e, depois de instalar, confere a versão que ficou de fato (o Windows costuma preferir o driver mais novo); se não trocou, explica como resolver. Chipset, disco e térmico mais novos não são rebaixados.

## [1.4.1] - 2026-11-21

### Alterado
- **Driver do fabricante da peça, não só do PC.** O app identifica quem fabricou cada peça pelo Hardware ID (Intel, Realtek, AMD, NVIDIA, Qualcomm, MediaTek, Broadcom...). O pacote do fabricante do PC só é usado quando o catálogo dele lista aquela peça exata (com `SUBSYS`). Peça trocada (ex.: Wi-Fi Realtek de fábrica substituído por Intel) recebe o driver do fabricante dela, e o relatório avisa. Pacote do PC que bate só pelo chip fica atrás do driver do fabricante da peça, e reempacotadores de terceiros são descartados.
- **Só versões estáveis:** beta, alpha, preview, pre-release, insider e release candidate são descartados; entre os válidos vale a versão estável mais nova.
- **Peça original com versão mais nova do fabricante da peça:** Wi-Fi, Bluetooth, rede e vídeo ficam com a versão estável mais nova (o pacote do fabricante do PC é o mesmo driver, repassado com atraso); áudio, chipset, controlador de disco, térmico, touchpad, câmera e afins ficam com a versão validada pelo fabricante do PC (ajustada ao modelo), e o relatório mostra a mais nova.
- **BIOS e firmware só avisam:** a tela de Drivers mostra a versão instalada, a disponível e a data, com botão para a página do fabricante. Nunca são instalados pelo programa.
- Lista de drivers ("Driver de") e relatório mostram o fabricante da peça e quem publicou o driver.
- Fabricantes de PC sem catálogo público (ASUS, Acer, MSI, Gigabyte, Samsung, Positivo, Avell...) são reconhecidos: pacotes da própria marca publicados no Catálogo da Microsoft (touchpad, controle do sistema) são aceitos.
- **Corrigido:** pacote sem versão informada vencia o de versão conhecida (caso real: Bluetooth Intel recebia um pacote de 2015 em vez do 22.200.0.2). Agora "sem versão" só vale se for o único.
- **Corrigido:** aparelho sem driver ficava sem tipo (o Windows não informa); agora o tipo e um nome legível saem dos IDs de classe ("Bluetooth Intel (sem driver)"), e a regra por tipo de peça vale para ele.
- **Corrigido (linha de comando):** o "SIM" enviado pelo PowerShell não era aceito (caractere invisível no começo); sem resposta, o programa terminava com erro do Python em vez de cancelar. Sem ponto de restauração, mostra como ligar a Proteção do sistema.
- **Aparelhos conectados:** periféricos de mais de 30 marcas (Logitech, HP, Epson, Canon, Brother, Razer, Wacom...) têm o fabricante identificado; impressoras USB/de rede e aparelhos Bluetooth LE sem driver também são procurados; aparelhos da própria Microsoft (controle Xbox, Surface) aceitam o driver da Microsoft.
- Busca no Catálogo da Microsoft também para peças que o fabricante do PC só reconhece pelo chip.

## [1.4.0] - 2026-11-16

### Adicionado
- Tela **Escritório**: 30 ajustes para trabalho com muitas abas, planilhas, rede e segurança, no mesmo motor da Otimização (backup, Desfazer, aviso de reinício).
  - Memória: compressão de memória, arquivo de paginação automático, SysMain.
  - Navegadores: Chrome (Economia de memória, fechar de verdade) e Firefox (sem agente e telemetria em segundo plano), pelas políticas oficiais.
  - Excel e Office: sem animações; sem aceleração gráfica (só com sintoma); LibreOffice com cache de imagens maior.
  - Rede: descoberta de rede, unidades mapeadas em programas de administrador, impressora padrão fixa, placa de rede sem economia de energia, DNS pela VPN.
  - Segurança: extensões visíveis, Defender contra programas indesejados (PUA), SMB1 desligado, Proteção do sistema ligada.
- Tela **Saúde do PC**: diagnóstico só de leitura (segurança, integridade, memória, rede) com dicas em ordem de gravidade, e reparos com um clique (DNS, fila de impressão, temporários, chkdsk, SFC, DISM, redefinir rede).
- **PC de empresa** (domínio, Entra ID ou Intune) detectado: o que a TI controla fica bloqueado nas telas de ajustes, nas duas telas.
- Ajustes de programas não instalados (Chrome, Firefox, Office, LibreOffice) aparecem como "Não se aplica".
- Categoria **Tampa, botões e tela**, no topo das telas Otimização e Escritório, valendo em todos os planos de energia, na bateria e na tomada:
  - Fechar a tampa não suspende nem desliga (notebook): só a tela do notebook apaga; programas, VPN e monitor externo continuam.
  - Botão de energia e de suspensão não fazem nada (segurar o botão continua desligando um PC travado).
  - Tela e PC nunca apagam nem suspendem sozinhos.
- Plano **Desempenho Máximo** com desempenho também na bateria: gráficos Intel no máximo, vídeo em qualidade máxima e mídia sem suspender. **PCIe sem economia** passa a valer também na bateria.

### Corrigido
- O plano **Desempenho Máximo** trocava a ação da tampa, do botão de energia e os tempos de tela e suspensão pelos padrões do Windows (fechar a tampa passava a suspender, e monitores em hub USB-C voltavam com resolução errada). Agora o plano novo herda essas preferências do plano anterior.
- "Efeitos visuais no mínimo" mantém o ClearType (letras nítidas) ligado.
- Ajustes via PowerShell conferem de novo por alguns segundos antes de declarar falha (a compressão de memória às vezes demora a refletir).
- Mensagens do SFC e do DISM sem as barras de progresso.

### Alterado
- "Desfazer tudo" desfaz só os ajustes da tela em que você está.

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

[1.4.5]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.5
[1.4.4]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.4
[1.4.3]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.3
[1.4.2]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.2
[1.4.1]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.1
[1.4.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.4.0
[1.3.3]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.3
[1.3.2]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.2
[1.3.1]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.1
[1.3.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.3.0
[1.2.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.2.0
[1.1.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.1.0
[1.0.0]: https://github.com/joao-eder/driverprecision/releases/tag/v1.0.0
