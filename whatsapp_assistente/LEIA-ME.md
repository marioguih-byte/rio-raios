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
- No alerta verde (fim do alerta) o vencimento é sempre início + 1 hora.

## Boletins no site (v1.9)
Em cada linha dos boletins há **📝 Registrar no site**: com a aba *Histórico de Boletins* (`/newsletter`) aberta, o script preenche Unidade, Status (qualquer 🔴 = Vermelho; senão qualquer 🟡 = Amarelo; senão Verde), Data e hora (agora, Brasília), Título (`<unidade> - Boletim de previsão do tempo`) e Texto (a mensagem sem a primeira linha). O Resumo fica vazio. Você confere e clica em *Adicionar boletim*.

## Quadro de operação compartilhado
No topo do app, visível para todos os usuários conectados (atualiza a cada 5 s):
- **🟢 Online agora**: quem está com o site aberto (você e os outros), com aviso quando alguém entra ou sai do site.
- **👥 De plantão agora**: a **entrada** é registrada sozinha quando a pessoa abre o site com o seu nome; a **saída**, ao apertar **🚪 Saindo do Turno**. Depois de sair, o turno não reabre sozinho por 1 h (há o botão **🟢 Voltar ao turno**); turnos esquecidos fecham sozinhos após 16 h. **🕒 Registro de turnos** guarda entrada, saída e duração, com CSV.
- A **escala prevista** (horário de Brasília; turnos que viram a noite; linhas com **Data** = troca pontual) aparece só como referência: “Previsto na escala agora”.
- **Alertas emitidos** por qualquer meteorologista: unidade, quem emitiu, horário, via (WhatsApp / Site / Copiado), validade e contagem regressiva. Botões **➕ 30 min** (renovar) e **✖ Tirar** (remover do quadro) para qualquer usuário.
- Entra no quadro ao clicar em *Preparar no WhatsApp*, *Registrar no site* ou *Copiar*; **some** ao finalizar (alerta verde), excluir, tirar ou vencer.
- **Avisos com mensagem e sinal sonoro** (uma vez por alerta em cada sessão): alerta novo emitido por outra pessoa, faltando **5 min** e faltando **1 min** (sinal mais urgente). Liga/desliga em *🔔 Som do quadro*.
- **Escala dos meteorologistas** editável por todos, com agenda da semana e trocas pontuais.
- **Histórico de alertas** compartilhado (últimos 500 registros: emitido, renovado, finalizado, vencido, removido, escala atualizada) com download em CSV.

Os dados ficam na memória do servidor e num arquivo temporário (sobrevivem a reinícios simples, não a um novo deploy). Para fixar a escala no GitHub, crie `data/escala.json`: `[{"nome":"Fulano","dia":"Todos os dias","data":"","inicio":"08:00","fim":"17:00"}]`.

## Boletins e mapas baixados pelo navegador
Sem chave de API, ao clicar em *Gerar boletins* ou *Gerar mapas de previsão* o **navegador de quem clicou** baixa os dados do Open-Meteo (o limite diário conta no IP dessa pessoa, não no do servidor). Os dados voltam ao app e ficam em cache para todos (boletins 30 min, mapas 3 h). Com `OPEN_METEO_API_KEY` configurada, o servidor baixa como antes.

## Fila de boletins no site (v2.3)

1. No app, em **Enviar pelo WhatsApp Web (assistido)**, clique em **📝 Registrar todos no site (fila)**.
2. Deixe aberta a aba **Histórico de Boletins** (`/newsletter`) do site. Aparece um painel no canto inferior direito.
3. O painel preenche um boletim por vez. Você confere e clica em **Adicionar boletim**; quando o formulário limpa (ou o título aparece na lista), o próximo é preenchido sozinho e o check **Site** da unidade é marcado no app.
4. Botões do painel: **✔ Salvei → próximo** (se a detecção automática não confirmar), **↻ Preencher de novo**, **⏭ Pular**, **⏹ Parar fila**.
5. O script nunca clica em salvar. Atualize o script do Tampermonkey para a **v2.3**.

## Satélites do mapa

Todos NASA GIBS · GOES-East: Infravermelho, GeoColor e Massa de ar; um por vez.

## Alertas ativos no painel lateral

Os alertas emitidos por qualquer meteorologista aparecem na aba **📡 Ativos** do painel "Alertas e riscos" (lateral do mapa) e também no painel de alertas ao lado do mapa, com quem emitiu, a via, o horário, a validade e a contagem regressiva. O painel ocupa a altura do mapa e rola para cima e para baixo. **✖ Tirar** remove o alerta do quadro. O "Quadro de operação" mantém quem está online, o histórico e os avisos (mensagem + som) de 5 min e 1 min.

## Quem encerra o alerta é você

Os alertas amarelo/vermelho **não terminam sozinhos**: nem quando os raios se afastam, nem quando a validade acaba. Não há mais alerta verde automático nem nova notificação por vencimento. O alerta sai da lista só quando você usa **🟢 Finalizar alerta**, **🟢 Emitir alerta verde**, **✖ Tirar** (aba Ativos) ou **✕ Excluir**. A validade (1 h, 1 h 30 ou 2 h) continua valendo para o horário enviado ao WhatsApp e ao site; passado o prazo, o card mostra "prazo vencido: segue ativo até você encerrar". Os avisos de 5 min e 1 min antes do prazo continuam.

## Alterar para amarelo, anéis e espessura

- No card de um alerta **vermelho** (painel de alertas e painel do mapa) há o botão **🟡 Alterar para amarelo**: gera o alerta amarelo da unidade, que você copia/envia como os demais. O vermelho anterior fica na lista até você excluir. Do amarelo dá para voltar ao vermelho com **🔴 Antecipar para vermelho**.
- Em **⚙ Configuração → Anéis de distância no mapa** há uma caixa para cada anel (30, 50, 100 e 200 km): desmarque para tirar do mapa e da legenda.
- **Espessura das linhas dos anéis**: de 1 (mais fino) a 5 (mais grosso); o padrão é 3 (médio, igual ao que era antes).

No painel de cada unidade há três botões: **🟢 Emitir alerta verde**, **🟡 Emitir alerta amarelo** e **🔴 Emitir alerta vermelho**. Cada um gera o card do nível escolhido (mensagem de 50 km no amarelo e de 30 km no vermelho), mesmo sem raio por perto; depois é só copiar, preparar no WhatsApp ou registrar no site.

## Versão 2.6 — o que mudou

- **Sem mensagem duplicada no WhatsApp:** a caixa de mensagem é esvaziada antes de digitar (um rascunho antigo não é emendado), o texto é conferido
  (nem faltando, nem repetido) e cada pedido é tratado por uma única aba, mesmo com duas abas do WhatsApp abertas. No app, se a mesma mensagem
  (unidade + nível) já foi enviada nos últimos 30 min por qualquer meteorologista, o botão pede um **segundo clique** para confirmar.
  Além disso, outra sessão do app não recria o alerta de uma unidade que alguém já emitiu ou já finalizou.
- **Fim do alerta manual:** em "Validade" escolha **Fim manual** e digite o horário (HH:MM, Brasília). Vale para a mensagem e para o Vencimento no site.
- **Site da BlueOcean:** funciona nos dois modos do formulário. No **Manual** preenche Unidade, Data e hora, Vencimento, **Meteorologista (o nome
  cadastrado no RIO)**, Tipo de alerta = Raios, Nível e Texto; no **Automático** preenche como antes. Nunca clica em salvar.
- **Navegadores:** Chrome, Edge, Brave, Opera e Firefox (Tampermonkey ou Violentmonkey). O script tem plano B se o gerenciador não avisar mudanças
  (consulta a cada 1 s) e se a área de transferência estiver bloqueada.
