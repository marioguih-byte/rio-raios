# BlueOcean — Monitor de Raios (versão web)

Versão do painel focada **só em raios** (GLM/GOES-19) — sem rajada de vento,
precipitação ou CAPE. Layout redesenhado.

## O que mudou em relação à versão anterior

- Removidas todas as variáveis de previsão (rajada de vento, chuva, CAPE) e
  a busca no Open-Meteo. O app não depende mais de nenhuma data/modelo — é
  só monitoramento de raios ao vivo.
- O status de cada unidade (🟢/🟡/🔴) agora é calculado direto pela
  distância até o raio ativo mais próximo, não por um "risco combinado".
- Layout novo: cabeçalho com indicador do status geral (quantas unidades
  em alerta agora), fonte Inter, cores revisadas.
- Cada alerta na aba **📋 Alertas** agora tem um campo **"Quem recebeu o
  alerta:"** — você digita o nome de quem confirmou o recebimento (por
  telefone, por exemplo) e ele entra automaticamente na mensagem, logo
  antes da linha "Válido até as...". Continua sendo copiar e colar (`st.code`
  com botão de copiar) pro WhatsApp — nada é enviado automaticamente por
  aqui.
- O painel que abre ao clicar numa unidade agora mostra status e contatos
  (sem o gráfico horário, que dependia das variáveis removidas).
- O boletim em PDF virou um "Boletim de Raios": unidades em alerta agora +
  lista de alertas gerados (já com "Quem recebeu o alerta" preenchido, se
  informado).

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

Se preferir sem terminal: no repositório existente no GitHub, é só
substituir o `streamlit_app.py` e o `README.md` pelos novos (upload de
arquivo, mesmo nome, sobrescreve).

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
