# Segurança

## Versões suportadas

Só a versão mais recente em [Releases](https://github.com/joao-eder/driverprecision/releases/latest) recebe correções.

## Como reportar

Para vulnerabilidades (ex.: download não validado, execução de arquivo adulterado, injeção de comando), **não abra issue pública**. Use o [relatório privado de vulnerabilidade](https://github.com/joao-eder/driverprecision/security/advisories/new) do GitHub.

Inclua: versão, passos para reproduzir e impacto. A resposta inicial deve vir em até 7 dias.

## O que o programa faz no seu PC

- `scan`: só lê (WMI, registro, busca do Windows Update) e baixa catálogos públicos da Lenovo, Dell, HP e Microsoft. Não envia dados a ninguém.
- `baixar`: baixa o pacote e valida o hash publicado pela fonte e a assinatura Authenticode. Arquivo que não confere é apagado.
- `instalar`: só roda como administrador, depois de digitar `SIM`, e tenta criar ponto de restauração antes. BIOS/firmware nunca são instalados automaticamente.
