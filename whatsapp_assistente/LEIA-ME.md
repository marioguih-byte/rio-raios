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
