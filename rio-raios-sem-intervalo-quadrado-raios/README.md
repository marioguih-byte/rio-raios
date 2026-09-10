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
