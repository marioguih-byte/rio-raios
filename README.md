# BlueOcean — Monitor de Raios (versão web)

Versão do painel focada **só em raios** (GLM/GOES-19) — sem rajada de vento,
precipitação ou CAPE.

## Atualização "sutil" — o mapa não recarrega mais

Antes, cada atualização de raios reconstruía o mapa inteiro (o Leaflet, os
tiles, tudo), o que causava um "flash" visível a cada ciclo. Agora o mapa
é um **componente Streamlit de verdade** (`bo_mapa_component/`, uma pasta
nova que precisa ir junto no deploy) — ele monta **uma única vez** e, a
cada ciclo, o Python só manda os dados novos pra ele (via o protocolo
oficial de componentes do Streamlit); o JS do lado do mapa apenas
redesenha os pontos de raio e as unidades, sem recarregar tiles, sem
perder zoom, sem popup fechando sozinho. A única coisa que muda
visualmente a cada ciclo é um fade rápido no textinho de status
("⚡ raios atualizados às..."), propositalmente sutil.

Isso também resolve de vez o problema de confiabilidade de antes: esse
componente é servido pelo mecanismo oficial do Streamlit pra componentes
(diferente do "static file serving" ad-hoc, que só é confiável pra
arquivos gravados durante a execução — aquele era o motivo dos raios às
vezes sumirem do mapa).

**Importante pro deploy**: a pasta `bo_mapa_component/` (com o
`index.html` dentro) precisa subir pro GitHub junto com o
`streamlit_app.py`, mantendo essa mesma estrutura de pastas — sem ela o
mapa não carrega.

## Novidades desta versão

- **Raios por idade:** vermelho 0–5 min · laranja 5–10 · amarelo 10–15 · verde
  15–20, com legenda no mapa. O mapa agora mostra 20 min de raios; os
  **alertas e o rastreio de células continuam usando a janela de 15 min**
  de antes, então a sensibilidade dos alertas não mudou.
- **Anéis de distância** das unidades mais grossos.
- **Mapa de fundo:** OpenStreetMap (padrão) e Satélite (Esri), no controle de
  camadas do canto superior direito do mapa.
- **GOES-East** (infravermelho limpo, banda 13, via NASA GIBS) ligado por
  padrão como camada sobreposta; dá pra desligar no mesmo controle.
- **Pop-up da unidade** (clique no marcador): rajada de vento e precipitação
  horárias do Open-Meteo para **ECMWF, ICON e GFS** (botões Hoje/Amanhã, tabela
  de máximo/acumulado e dois gráficos). A consulta é feita pelo navegador só
  quando a unidade é clicada e fica em cache por 30 min.
- **Boletins WhatsApp:** seção no fim da página que usa o `boletins_bo.py`
  (o mesmo script de boletins, sem alterações): ensemble ECMWF+ICON+GFS,
  filtro por nome, nº de dias, download consolidado (.txt) e um .txt por
  unidade (.zip). A geração roda em segundo plano, sem travar o mapa.
  **O arquivo `boletins_bo.py` precisa subir pro GitHub junto com o
  `streamlit_app.py`.**

## Alertas e riscos dentro do mapa

- Botão 🚨 no canto superior esquerdo do mapa (abaixo da tela cheia), com contador de unidades em
  alerta. Abre um painel com as mesmas abas do painel lateral — **Risco** (unidades em amarelo/vermelho,
  contatos, "Ver no mapa") e **Alertas** (campo "Quem recebeu o alerta", texto para copiar, excluir
  e limpar todos) — e funciona **também em tela cheia**.
- "Quem recebeu", excluir e limpar voltam para o Streamlit e valem também para o painel lateral.

## Tela cheia do mapa

- Botão de tela cheia no canto superior esquerdo do mapa (abaixo do zoom); o painel da unidade, a
  legenda e o controle de camadas vão junto. Se o navegador não permitir a tela cheia nativa dentro do
  quadro do Streamlit, o botão passa a **aumentar a altura do mapa** (e reduzir ao clicar de novo).

## GOES-East com menos atraso

- **GOES-East:** o padrão é o **SSEC RealEarth** (GOES-19, banda 13 com realce de topos frios).
  Também há banda 13 simples, IR Sandwich (topos convectivos) e GeoColor, e o NASA GIBS (~30 min de
  atraso) continua disponível, desligado, no controle de camadas. O mapa mostra "imagem das HH:MM
  (há X min)" para você conferir o atraso real. Crédito exigido pelo SSEC: "Source: SSEC RealEarth,
  UW-Madison" (aparece na atribuição do mapa). Obs.: o SSEC pode exibir uma marca d'água
  ("Size limit exceeded") quando o uso passa do limite gratuito dele.

## Barra de rolagem

- Barra de rolagem mais grossa no site e no painel da unidade (Chrome/Edge); no Firefox vale a espessura "auto" do navegador.

## Celular (primeira rodada)

- Mapa um pouco mais baixo em celular em pé (560 px); botões maiores para o toque; campos de texto
  com fonte de 16 px (o iPhone não dá zoom ao digitar); painéis da unidade e de alertas ocupam a
  largura da tela; tabela do painel da unidade rola de lado; cabeçalho compacto.
- **Rolagem:** na tela normal, 1 dedo rola a página e o mapa se move/zoom com 2 dedos (dica na
  primeira vez). Em tela cheia ou com o mapa ampliado (botão ⛶), 1 dedo move o mapa. No computador
  nada muda.

## Som do alerta

- O aviso de som fica nos dados do mapa até tocar (a reexecução que abre o pop-up podia substituí-lo antes).
  Se o navegador bloquear o som, aparece um aviso e ele toca no primeiro toque/clique no mapa.
- O som toca **uma única vez por alerta novo**. Antes, abrir/fechar o menu lateral (ou o painel de
  alertas, ou redimensionar a janela) fazia o Streamlit reenviar os mesmos dados ao mapa e o som tocava de novo.

## Painel de alertas retrátil

- A chave "🚨 Painel de alertas" (acima do mapa, à direita) abre e fecha o painel lateral de risco e
  alertas. Começa **recolhido**, com o mapa ocupando a largura toda; os avisos de raio continuam
  aparecendo em pop-up. A tela de boas-vindas agora diz "Bem-vindo ao RIO".

## Cores das bolinhas dos boletins

- Verde/amarelo/vermelho seguem os limiares: **chuva** <10 · 10–24 · ≥25 mm/dia; **rajada** 0–40 ·
  41–61 · ≥62 km/h; **UV** 0–5 · 6–10 · ≥11; **umidade** ≥40% · 12–39% · <12%. O vento médio
  segue como antes (40/60 km/h). O texto do boletim não mudou, só as bolinhas.

## Correção nos boletins

- Todas as unidades agora começam no **dia de hoje em Brasília**. Antes cada unidade usava o dia do
  próprio fuso; a UTE Três Lagoas (MS, 1 h atrás de Brasília) saía com o boletim do dia anterior
  entre 00h e 01h. O formato do boletim não mudou.
- Depois de gerar, o app confere se todos os boletins começam em hoje (Brasília) e avisa quando alguma
  unidade sair com outro dia — sinal de que o `boletins_bo.py` em uso é a versão antiga.

## Removido

- Botão "Baixar boletim de raios em PDF" (e a dependência `reportlab`).
- A legenda "— mesmo formato do script de boletins" na seção de boletins.

## Pontos das unidades

- Os pontos ficam numa camada própria **acima dos anéis, dos raios e das células**, com borda preta
  sólida — antes o contorno escuro dos anéis e os raios cobriam a borda.

## Identidade visual

- Cabeçalho: logo do **RIO** (`data/logo_rio.webp`) e título "RIO — Rede Inteligente de Observação
  (de descargas atmosféricas)". O ícone da aba do navegador é `data/icone_rio.png`.
  A pasta `data/` precisa subir pro GitHub junto com o `streamlit_app.py`.

## Ajustes (mais recentes 2)

- **Cores dos anéis:** removida a opção "Personalizada"; agora são 7 paletas prontas (Padrão, Alto
  contraste, Vivas, Quentes, Frias, Semáforo e Daltonismo).
- **Pontos das unidades:** cores de status mais vivas (vermelho · amarelo · verde) e borda preta sutil.

## Ajustes (mais recentes)

- **Anéis:** voltaram às cores azul · verde · laranja · vermelho, em tons mais vivos, com contorno
  escuro por baixo. Na barra lateral dá pra trocar a paleta (Padrão, Alto contraste, Vivas) ou
  escolher uma cor para cada anel (Personalizada).
- **Alertas:** o pop-up do alerta aparece uma única vez por alerta novo (antes reaparecia nas
  primeiras atualizações) e fica aberto até ser fechado. O alerta **não abre mais o painel da
  unidade nem move o mapa**; o painel só abre ao clicar na unidade.
- **Atualização sutil:** os raios e as células são redesenhados sem esvaziar o mapa (as camadas novas
  entram antes de as antigas saírem).
- Título da seção de boletins agora é "Boletins de previsão".

## Ajustes (última rodada)

- **Bolinhas de raio** com tamanho fixo (5); a opção de ajuste foi removida.
- **Anéis mais visíveis:** 30 km ciano · 50 km magenta · 100 km branco · 200 km lilás, cada um com
  contorno escuro por baixo, pra aparecerem sobre o GOES-East, o satélite e o mapa claro.

## Ajustes (rodada atual)

- **Mapa:** as demais regiões voltaram a aparecer (levemente esmaecidas fora do Brasil); a vista
  inicial segue focada no Brasil.
- **Raios fora do Brasil não são mostrados** (exceção: raios a até ~55 km de uma unidade, pra um
  raio no mar perto de uma unidade litorânea não sumir do mapa).
- **Deslocamento das células** de volta ao estilo original: ✕ por posição (verde = mais antiga →
  amarelo → vermelho = atual) ligados por linha tracejada até os pontos previstos (+30/60/90 min).
- Removido o texto "Só os raios ... atualizam sozinhos" da barra lateral.

## Ajustes mais recentes

- **Contorno das UFs em todo o Brasil** (inclui o limite externo) e **mapa só do Brasil**:
  o que está fora do território fica coberto por uma máscara escura e o zoom/arraste é limitado ao país.
- **Tamanho das bolinhas de raio** ajustável na barra lateral.
- **Raios antigos voltaram a aparecer** (0–20 min): antes o mapa só recebia os 5000 raios mais
  novos, que cabiam todos na faixa de 0–5 min. Agora cada faixa de 5 min é enviada.
- **Alertas já ativos não abrem o painel ao abrir o site**; só alertas novos abrem.
- **Deslocamento das células**: linha única de trajetória (percorrida + prevista tracejada), marcas
  de +30/60/90 min, seta e ✕ na posição atual com velocidade/rumo.
- **Painel da unidade**: contatos primeiro, depois as informações.
- Removidos: título/legenda "Unidades monitoradas" da barra lateral e o 1º contato do Porto Açu.

## Ajustes da última rodada

- **Legenda retrátil**, recolhida por padrão (clique em "▸ Legenda" no canto do mapa).
- **Sem upload de planilha:** o app usa sempre as 41 unidades cadastradas.
- **Anéis:** ficou só a caixa "Mostrar anéis de distância" (30/50/100/200 km sempre juntos).
- **Divisão de UFs** no mapa (limites entre estados, ligável/desligável no controle de camadas).
- **Bolinhas de raio maiores.**
- **Deslocamento das células redesenhado:** trilha percorrida (mais forte = mais recente),
  marcador pulsante com velocidade/rumo, trajetória prevista com marcas de +30/+60/+90 min,
  seta de direção e cone de incerteza.
- **Painel da unidade** (clique no marcador) em formato de painel completo: cartões de resumo
  (status, raio mais próximo, rajada e chuva de hoje+amanhã e das próximas 6 h), tabela por
  modelo (ECMWF/ICON/GFS), gráficos de rajada (com faixas 40/61 km/h) e de chuva, e contatos.
  Fecha com ✕ ou Esc.

## Cores dos anéis

Ajustadas pra bater com o exemplo que você mandou: 30 km azul, 50 km
verde, 100 km laranja, 200 km vermelho.

## Outras correções desta rodada (mantidas)

- **Fundo do mapa**: OpenStreetMap padrão (sempre gratuito, sem key) com
  filtro CSS escuro — a CartoDB passou a exigir API key em agosto/2026.
- **Legenda** fixa no canto do mapa com as cores de status (🔴🟡🟢) e dos
  anéis.
- Som de alerta embutido como base64 no componente (não depende de
  arquivo estático nem de conexão externa pra tocar).

## O que mudou em relação à versão anterior (rajada/chuva/CAPE)

- Removidas todas as variáveis de previsão e a busca no Open-Meteo.
- O status de cada unidade (🟢/🟡/🔴) é calculado direto pela distância
  até o raio ativo mais próximo.
- Cada alerta na aba **📋 Alertas** tem um campo **"Quem recebeu o
  alerta:"** que entra automaticamente na mensagem, pronta pra copiar e
  colar. Nada é enviado automaticamente por aqui.
- O boletim em PDF virou um "Boletim de Raios": unidades em alerta agora +
  lista de alertas gerados.

## Passo a passo pra colocar no ar (grátis)

### 1. Suba esta pasta pro GitHub

```bash
cd blueocean_web
git init
git add .
git commit -m "BlueOcean — Monitor de Raios"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/blueocean-web.git
git push -u origin main
```

Se preferir sem terminal: no repositório existente no GitHub, suba (upload
de arquivo, mesmo nome, sobrescreve) o `streamlit_app.py`, o `README.md`,
o `.streamlit/config.toml` **e a pasta nova `bo_mapa_component/` com o
`index.html` dentro** — essa pasta é obrigatória, sem ela o mapa quebra.

### 2. Publique/atualize no Streamlit Cloud

Se o app já está publicado em **share.streamlit.io**, ele atualiza sozinho
assim que detecta o push no GitHub. Se for a primeira vez, siga o fluxo
normal: **New app** → repositório `blueocean-web` → branch `main` → main
file `streamlit_app.py` → **Deploy**.

## Rodando localmente (pra testar antes de subir)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Limite conhecido do plano gratuito

O Streamlit Community Cloud gratuito tem um limite de recursos (RAM/CPU)
compartilhado por app. Pra uso por 1-2 pessoas ao mesmo tempo funciona
bem; pra uso mais intenso, vale considerar um plano pago ou outro provedor
(Render, Railway).
