# Assistente de envio ao WhatsApp (com supervisão)

Como funciona: no painel de alertas do mapa, o botão **🤖 Preparar no WhatsApp** manda o alerta
(já com "Quem recebeu o alerta") para a aba do WhatsApp Web. Lá, o script procura o grupo da
unidade, abre o chat e deixa a mensagem **digitada** — você confere e aperta **Enter**.
O script NUNCA envia sozinho.

## Instalação (uma vez, no Edge/Chrome)
1. Instale a extensão **Tampermonkey**.
2. Tampermonkey → *Criar novo script* → apague tudo, cole o conteúdo de `rio-raios-whatsapp.user.js` → salvar.
3. O app em `rio-raios.streamlit.app` já é reconhecido. Se usar outro endereço, acrescente `// @match https://SEU-ENDERECO/*` no cabeçalho do script.
   `// @match https://SEU-ENDERECO/*` no cabeçalho do script.
4. Deixe abertas as duas abas: o app RIO Raios e o WhatsApp Web (logado). Recarregue as duas.

## Uso
Preencha "Quem recebeu o alerta" → clique em **🤖 Preparar no WhatsApp** → vá à aba do WhatsApp,
confira a mensagem e aperte Enter.

## Se não achar o grupo
O script procura pelo nome da estação antes do " - " (ex.: "UTE Termobahia"), depois pela sigla
(ex.: "UTE TBA") e pelo nome completo. Se o nome do grupo for diferente, preencha
`BUSCA_POR_UNIDADE` no topo do script. Quando algo falha, o texto é copiado e a faixa no topo avisa:
é só colar no grupo (Ctrl+V).

## Limitações
- O WhatsApp muda o código da página de vez em quando; se parar de achar os grupos, o aviso
  aparece e o plano B (texto copiado) continua funcionando.
- A aba do WhatsApp Web precisa estar aberta e logada.

## Fila de boletins (todos de uma vez, com supervisão)
Na lista de boletins, **🤖 Preparar todos (fila)** manda todas as unidades para o script. Ele abre o
grupo da 1ª unidade e deixa o boletim digitado; **você confere e aperta Enter**. Quando a caixa
esvazia (mensagem enviada), ele abre a próxima. Na aba do WhatsApp aparecem os botões
**⏭ Pular este** e **⏹ Parar fila**. Se você abrir outro chat no meio, a unidade é contada como pulada.
Grupos não encontrados são listados no resumo final (o texto é copiado para você colar à mão).
O script nunca aperta Enter por você.

## Registrar no site da BlueOcean (v1.7)
Botão **📝 Registrar no site** (painel do alerta e card do mapa). Com a aba *Registro de eventos críticos* (`/alerts`) aberta, o script preenche **Unidade, Início (agora, Brasília), Vencimento (início + validade escolhida), Nível e RAIOS (sempre marcado)**. O texto vem do modo *Automático* do site. O script **nunca clica em Salvar**: confira e clique em *Salvar alerta automático*.
- Atualize o script no Tampermonkey (v1.7) e **recarregue a aba do site** depois.
- No alerta verde (fim do alerta) unidade, início, nível e RAIOS são preenchidos; o vencimento fica como o site sugere.

## Boletins no site (v1.9)
Em cada linha dos boletins há **📝 Registrar no site**: com a aba *Histórico de Boletins* (`/newsletter`) aberta, o script preenche Unidade, Status (qualquer 🔴 = Vermelho; senão qualquer 🟡 = Amarelo; senão Verde), Data e hora (agora, Brasília), Título (`<unidade> - Boletim de previsão do tempo`) e Texto (a mensagem sem a primeira linha). O Resumo fica vazio. Você confere e clica em *Adicionar boletim*.
