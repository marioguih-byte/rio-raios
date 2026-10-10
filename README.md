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

## Ajustes da última rodada

- **Legenda retrátil**, recolhida por padrão (clique em "▸ Legenda" no canto do mapa).
- **Sem upload de planilha:** o app usa sempre as 40 unidades cadastradas.
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
