---
title: "Um Kobo, um iPhone e nenhum cabo"
description: "sem cabo USB, enviei um EPUB do iPhone para o Kobo usando o servidor SSH do KOReader, o tethering do iPhone e o SFTP do Termius."
feature: "img/kobo-sem-cabo-capa.png"
date: 2026-10-29T22:40:00Z
draft: false
tags: ["iPhone", "Github", "Kobo", "ssh", "Koreader", "sftp", "epub", "devto"]
categories: ["Blogging"]
---

**Resumo**: sem cabo USB, enviei um EPUB do iPhone para o Kobo usando o servidor SSH do KOReader, o tethering do iPhone e o SFTP do Termius. Levou cerca de meia hora, e o caminho deu certo mesmo com a pasta errada no primeiro envio.

## Contexto

Depois de terminar o último livro de literatura, passei cerca de um mês sem ler nada do gênero. Hoje decidi retomar. Fui à academia levando apenas o Kobo e o iPhone, e foi aí que a peripécia começou.

## O problema

Eu tinha o EPUB no iPhone e queria lê-lo no Kobo, mas não trouxe cabo USB. Sem cabo, o caminho habitual (conectar ao computador e copiar o arquivo) não existia, e foi preciso achar outra rota entre os dois aparelhos.

## Caminhos descartados

Antes de chegar à solução, três ideias ficaram pelo caminho:

- **Baixar o EPUB direto no Kobo.** O navegador do Kobo não dá conta de JavaScript mais pesado nem de páginas complexas.
- **LocalSend.** Esbarrou no mesmo limite do navegador.
- **Servidor de arquivos no iPhone com iSH e Python.** Viável em teoria, mas foi abandonado quando lembrei de uma opção mais simples.

A opção mais simples era o acesso SSH que o KOReader já oferece.

## A solução

O KOReader, instalado no Kobo, traz um servidor SSH. Depois de algumas tentativas frustradas, a combinação que funcionou foi esta: o Kobo conectado ao iPhone por tethering (Wi-Fi do hotspot), o SSH ativado no KOReader e o Termius no iPhone, entrando como root e usando o recurso de SFTP para enviar o arquivo. Na prática, o Kobo virou apenas mais um host na rede do iPhone.

## A pasta errada

O envio deu certo, mas o livro não apareceu na lista do Kobo: eu o havia colocado na pasta errada. A biblioteca nativa do Kobo só indexa o que está em `/mnt/onboard`, enquanto o KOReader enxerga o sistema de arquivos inteiro. O gerenciador de arquivos do próprio KOReader resolveu: movi o EPUB para o lugar certo e, cerca de meia hora depois de começar, o livro estava aberto.

Aprendizado: no próximo envio, o destino do SFTP já deve ser `/mnt/onboard`.

## Receita resumida

1. Ligar o tethering no iPhone e conectar o Kobo (Wi-Fi) ao hotspot.
2. No KOReader, ativar o servidor SSH e anotar o IP do Kobo (a rede do hotspot costuma usar a faixa `172.20.10.x`).
3. No Termius, criar um host com esse IP, a porta do SSH do KOReader (a padrão é 2222; confira na tela) e o usuário root.
4. Abrir o SFTP e enviar o EPUB direto para `/mnt/onboard`.
5. Se o livro não aparecer na biblioteca, mover o arquivo para essa pasta com o gerenciador de arquivos do KOReader.

## O que eu esperava encontrar e não existe

Depois de tudo funcionar, tentei achar uma forma de fazer upload pelo Safari, sem Termius. Parti de uma informação errada, que aparece nas primeiras respostas desta conversa: a de que o KOReader teria uma página de upload acessível pelo navegador. Não tem, até onde sei. O que de fato existe:

| Recurso | Para que serve | Resolve o upload pelo iPhone? |
| --- | --- | --- |
| SSH/SFTP | Acesso remoto aos arquivos do Kobo | Sim, é o que usei |
| HTTP Inspector | Depuração (expõe o estado interno do KOReader em JSON) | Não: a página aberta no Safari se descreveu como ferramenta para desenvolvedores |
| Calibre (Wireless) | Conecta o KOReader a um Calibre rodando em outro computador | Não, exige o Calibre num computador |
| OPDS | O KOReader baixa livros de um catálogo remoto | Não, o sentido é de download para o Kobo |

Também houve dois tropeços menores: o Safari assume HTTPS quando o endereço vem sem `http://`, e a opção de cliente sem fio marcada no KOReader provavelmente indicava apenas que o Wi-Fi do Kobo estava conectado ao hotspot, não um servidor ativo (não cheguei a confirmar).

## Alternativas para o futuro e lições

Para uso ocasional, o SFTP pelo Termius continua sendo o caminho mais simples. Para algo recorrente, há uma ideia ainda não testada: o KOReader tem *Cloud storage* com suporte a WebDAV, FTP e Dropbox, então um app do iPhone que rode um servidor WebDAV ou FTP poderia servir como "Calibre de bolso". O app Documents (Readdle) foi citado como candidato, mas sem confirmação de que a versão atual faça isso. Um servidor WebDAV em Python no iSH (por exemplo com `wsgidav`) seria possível em teoria, mas também não foi verificado.

Lições:

- Sob restrição, vale eliminar rotas de baixo para cima até sobrar a que as ferramentas já instaladas oferecem.
- O KOReader enxerga o sistema de arquivos inteiro; a biblioteca do Kobo só indexa `/mnt/onboard`.
- Antes de depender de um recurso de um app, confirmar que ele existe. Vários palpites desta sessão estavam errados e só caíram na prática.

DISCLAIMER: o Claude auxiliou na confecção desse artigo, que foi publicado da esteira da academia. :)
