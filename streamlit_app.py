# ======================================================================
# BLUEOCEAN — MONITOR DE RAIOS (versão web / Streamlit)
# Versão focada só em raios (GLM/GOES-19), por Mário Henrique.
# ======================================================================
import base64
import copy
import io
import math
import os
import re
import threading
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import boletins_bo  # script de boletins (WhatsApp), incorporado sem alterações

def _carregar_icone_pagina():
    try:
        from PIL import Image
        return Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "icone_rio.png"))
    except Exception:
        return "⚡"


st.set_page_config(page_title="RIO — Rede Inteligente de Observação", layout="wide", page_icon=_carregar_icone_pagina())

EMPRESA = "BlueOcean"

# ======================================================================
# COMPONENTE DO MAPA — atualiza os raios sem recarregar o mapa
# ======================================================================
# Componente bidirecional de verdade (não é st.components.v1.html): o
# frontend (bo_mapa_component/index.html) fica montado uma única vez, e a
# cada ciclo o Python só manda um "render event" com os dados novos — o
# Leaflet do lado do JS só redesenha as camadas de raios/unidades, sem
# recriar o mapa, sem recarregar tiles, sem nenhum "flash" de carregamento.
_APP_DIR_COMPONENTE = os.path.dirname(os.path.abspath(__file__))
_mapa_raios_component = components.declare_component(
    "bo_mapa_raios", path=os.path.join(_APP_DIR_COMPONENTE, "bo_mapa_component")
)


# ======================================================================
# ÁUDIO DE ALERTA
# ======================================================================
# Importante: o "static file serving" do Streamlit Community Cloud só
# garante servir de forma confiável os arquivos que já vêm no repositório
# do GitHub — arquivos GRAVADOS em disco durante a execução do app (como
# o raios_live.json que essa versão usava antes) não têm entrega
# garantida e foi isso que fazia o mapa às vezes não mostrar os raios.
# Por isso o som de alerta agora vai embutido direto no HTML do mapa,
# como um data URI em base64 — não depende de nenhum arquivo estático
# servido por HTTP.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SOM_ALERTA_NOME = "alerta_raio.wav"


@st.cache_data(show_spinner=False)
def _som_padrao_data_uri():
    caminho = os.path.join(APP_DIR, "data", SOM_ALERTA_NOME)
    with open(caminho, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:audio/wav;base64,{b64}"


@st.cache_data(show_spinner=False)
def _logo_data_uri():
    """Logo do RIO embutida no HTML do cabeçalho (data URI), sem depender de arquivo estático."""
    try:
        with open(os.path.join(APP_DIR, "data", "logo_rio.webp"), "rb") as f:
            return "data:image/webp;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


def utc_para_brasilia(dt_utc):
    return dt_utc - timedelta(hours=3)

# ======================================================================
# CONTATOS POR UNIDADE
# ======================================================================
CONTATOS_UNIDADES = {'REGAP': {'nome': 'REGAP', 'numeros': [{'numero': '(31) 3529 4470'}, {'numero': '(31) 3529 4405'}, {'numero': '(31) 3529 4508'}]}, 'CILEP_CENPES': {'nome': 'CILEP CENPES', 'numeros': [{'numero': '(21) 9 9700 6335'}, {'numero': '(21) 9 7968 0027'}]}, 'TMIB COQUEIROS': {'nome': 'TMIB COQUEIROS', 'numeros': [{'numero': '(79) 3212 5101'}, {'numero': '(79) 9 9630 8427'}]}, 'ARM RIO': {'nome': 'ARM RIO', 'numeros': [{'numero': '(21) 9 6576-0066'}, {'numero': '(21) 9 6576-0142'}, {'numero': '(21) 9 9649 4019'}]}, 'UTE_Canoas': {'nome': 'UTE Canoas', 'numeros': [{'numero': '(51) 3415-3939'}, {'numero': '(51) 99866-6449'}]}, 'Guamaré': {'nome': 'Guamaré', 'numeros': [{'numero': '(85) 98830.3729'}, {'numero': '(84) 99984.7020'}, {'numero': '85) 99207.7804'}]}, 'REFAP': {'nome': 'REFAP', 'numeros': [{'numero': '(51) 3415-2080'}, {'numero': '(51) 99982-0520'}, {'numero': '(51) 99617-3964'}]}, 'REPAR': {'nome': 'REPAR', 'numeros': [{'numero': '(41) 3641-2987'}, {'numero': '(41) 99157-6902'}, {'numero': '(41) 99241-5443'}]}, 'UTC_Nova_Piratininga': {'nome': 'UTE Nova Piratininga', 'numeros': [{'numero': '(11) 3523-5856'}, {'numero': '(11) 3523 5876'}, {'numero': '(11) 98393-0913'}]}, 'RPBC': {'nome': 'RPBC', 'numeros': [{'numero': '(13) 3328-4074'}, {'numero': '(13) 99712-4788'}, {'numero': '(13) 3328-4253'}]}, 'RECAP': {'nome': 'RECAP', 'numeros': [{'numero': '(11) 3795-9314'}, {'numero': '(11) 96183-2809'}, {'numero': '(11) 3795-9130'}]}, 'UTG_Caraguatatuba': {'nome': 'UTGCA - Caraguatatuba', 'numeros': [{'numero': '(12) 3886-5050', 'descricao': 'Opção 1'}, {'numero': '(12) 3886-5117', 'descricao': 'Opção 2'}, {'numero': '(12) 3886-5066', 'descricao': 'Opção 3'}]}, 'REVAP': {'nome': 'REVAP', 'numeros': [{'numero': '(12) 3928-6304'}, {'numero': '(12) 3928-6499'}, {'numero': '(12) 9 9130-6608'}]}, 'REPLAN': {'nome': 'REPLAN', 'numeros': [{'numero': '(19) 2116-6892 e (19) 99772-1201', 'descricao': 'celular melhor'}, {'numero': '(19) 2116-6542 e (19) 99602-8522'}, {'numero': '(19) 2116--6183'}]}, 'UTE_Tres_lagoas': {'nome': 'UTE Três Lagoas', 'numeros': [{'numero': '(67) 3509-3275', 'descricao': 'Opção 1 - Sala de Controle'}, {'numero': '(67) 3509 - 3234', 'descricao': 'Opção 2 - Supervisor de Turno'}, {'numero': '(67) 9 - 9847 - 3567', 'descricao': 'Opção 3 - Celular da Operação'}]}, 'UTE_Seropedica': {'nome': 'UTE Seropédica', 'numeros': [{'numero': '(21) 2665-9221', 'descricao': 'supervisao op'}, {'numero': '(21) 2665-9234'}, {'numero': '(21) 98330 0979.'}]}, 'UTE_Termorio': {'nome': 'UTE Termorio', 'numeros': [{'numero': '(21) 3227-5746'}, {'numero': '(21) 98055-0569'}, {'numero': '(21) 9 6720 8088'}]}, 'REDUC': {'nome': 'REDUC', 'numeros': [{'numero': '(21) 2677-2232', 'descricao': 'Opção 1'}, {'numero': '(21) 2677-2975', 'descricao': 'Opção 2'}, {'numero': '(21) 9 - 9872 - 4188', 'descricao': 'Fernanda Neves (Gerente do Setor)'}]}, 'UTG_Itaborai': {'nome': 'UTG Itaboraí', 'numeros': [{'numero': '(21) 2133-4199', 'descricao': 'ligar neste'}, {'numero': '(21) 2133-4202'}, {'numero': '(21) 99700-6571'}]}, 'Arm Macaé': {'nome': 'Arm Macaé', 'numeros': [{'numero': '(22) 9 9824-6085'}, {'numero': '(22) 9 9940-2957'}]}, 'UTE Juiz de Fora': {'nome': 'UTE Juiz de Fora', 'numeros': [{'numero': '(32) 3239-8431', 'descricao': 'sala op'}, {'numero': '(32) 3239-8423', 'descricao': 'sala op'}, {'numero': '(32) 99804-4943'}]}, 'UTE_Termomacae': {'nome': 'UTE Termomacaé', 'numeros': [{'numero': '(22) 3379-6134'}, {'numero': '(22) 3379-6135'}, {'numero': '(22) 98817-2571'}]}, 'UTG_Cabiunas': {'nome': 'UTG Cabiunas', 'numeros': [{'numero': '(22) 9 - 9981-1678 / Ramal: 2759 - 5280', 'descricao': 'Opção 1'}, {'numero': '(22) 9 - 9778-7616 / Ramal: 2797 - 5248 / 2797 - 5249', 'descricao': 'Opção 2'}]}, 'UTE_Ibirite': {'nome': 'UTE Ibirité', 'numeros': [{'numero': '(31) 3472-2230'}, {'numero': '(31) 99704-5869'}, {'numero': '(11) 96857-9818'}]}, 'UTG Sul_Capixaba': {'nome': 'UTG Sul Capixaba', 'numeros': [{'numero': '(28) 3360-6065', 'descricao': 'CISP'}, {'numero': '(27) 99297-9464', 'descricao': 'CISP'}]}, 'UTG_Cacimbas': {'nome': 'UTG C - Cacimbas', 'numeros': [{'numero': '(27) 3048-9107 / 9903', 'descricao': 'Supervisão da Operação (K-45)'}, {'numero': '(27) 3048-9300 / 9909'}, {'numero': '(27)3048-9152', 'descricao': 'Coordenador de Turno da Operação (K-45)'}, {'numero': '(27) 3048-9131', 'descricao': 'SMS (k-32)'}, {'numero': '(27)3048-9140', 'descricao': 'Controle de CFTV - 24h (k-04)'}]}, 'RNEST': {'nome': 'RNEST', 'numeros': [{'numero': '(81) 3879 - 4530'}, {'numero': '(81) 3879 - 3220'}, {'numero': '(81) 3879 - 4525'}]}, 'UTE_Termobahia': {'nome': 'UTE Termobahia', 'numeros': [{'numero': '(71) 3348-5006', 'descricao': 'Opção 1'}, {'numero': '(71) 9 - 9988-5704', 'descricao': 'Opção 2'}, {'numero': '(71) 9 - 9918 - 3933 / 9 -9672 - 4400', 'descricao': 'Opção 3'}]}, 'Porto Belém': {'nome': 'PORTO BELÉM', 'numeros': [{'numero': '(91) 99150.0369'}, {'numero': '(79) 99163.0089'}, {'numero': '(85) 99207.7804'}]}, 'Mucuripe_Paracuru': {'nome': 'Mucuripe Paracuru', 'numeros': [{'numero': '(85) 98147.6460'}, {'numero': '(85) 98829.9818'}, {'numero': '(85) 98126.3018'}, {'numero': '85) 99207.7804'}]}, 'UTE_Vale_ACU': {'nome': 'UTE Vale do Açu', 'numeros': [{'numero': '(84) 3235-6033', 'descricao': 'Opção 1'}, {'numero': '(84) 3235-6034', 'descricao': 'Opção 2'}, {'numero': '(84)  9 9609 - 9675', 'descricao': 'Opção 3'}]}, 'UTE_Termoceara': {'nome': 'UTE Termoceara', 'numeros': [{'numero': '(85) 3411 - 4420 / 4440', 'descricao': 'Sala de Controle da Unidade'}, {'numero': '(85) 9 9957-4422', 'descricao': 'Cristiano Freire - Gerente de Operação'}, {'numero': '(85) 998490019', 'descricao': 'Thiago Gerente de SMS'}]}, 'Porto Aratu': {'nome': 'Porto Aratu', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Macaé': {'nome': 'UTE Porto Macaé', 'numeros': [{'numero': '(22) 9 8113-0416'}, {'numero': '(22) 9 8183-0096'}, {'numero': '(22) 9 9736-9161'}]}, 'Porto Valença': {'nome': 'UTE Porto VALENÇA', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Açu': {'nome': 'UTE Porto AÇU', 'numeros': [{'numero': '(22) 2101 5960'}]}, 'Porto B Guanabara': {'nome': 'UTE PORTO BAIA DE  GUANABARA', 'numeros': [{'numero': '(21) 9 9519 4346'}, {'numero': '(21) 2144 0051'}, {'numero': '(21) 9 8145 4321'}]}}

def _normalizar_nome(texto):
    if not texto: return ""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", " ", texto).strip().upper()

ALIASES_UNIDADES = {
    "REGAP": ["Refinaria Gabriel Passos"], "REVAP": ["Refinaria Henrique Lage", "Refinaria do Vale do Paraiba"],
    "REPLAN": ["Refinaria de Paulinia", "Refinaria Paulinia"],
    "RPBC": ["Refinaria Presidente Bernardes", "Refinaria de Presidente Bernardes", "Refinaria de Cubatao"],
    "RECAP": ["Refinaria de Capuava", "Refinaria Capuava"], "REDUC": ["Refinaria Duque de Caxias", "Refinaria de Duque de Caxias"],
    "REFAP": ["Refinaria Alberto Pasqualini"],
    "REPAR": ["Refinaria Presidente Getulio Vargas", "Refinaria de Araucaria", "Refinaria Araucaria"],
    "RNEST": ["Refinaria Abreu e Lima", "Refinaria de Abreu e Lima"],
    "CILEP_CENPES": ["CENPES", "Centro de Pesquisas Leopoldo Americo Miguez de Mello"],
    "UTG_Itaborai": ["Boaventura"], "UTG_Cabiunas": ["UTGCAB", "UTG CAB", "UTG-CAB"],
    "UTG Sul_Capixaba": ["UTGSUL", "UTGSC", "UTG-SUL", "UTG SUL"], "UTG_Cacimbas": ["UTGC"],
    "UTG_Caraguatatuba": ["UTGCA"], "TMIB COQUEIROS": ["TMIB"], "Mucuripe_Paracuru": ["Mucuripe", "Paracuru"],
    "ARM RIO": ["Armazem Rio de Janeiro", "Armazem do Rio de Janeiro"],
}
_PALAVRAS_GENERICAS_UNIDADE = {"REFINARIA", "USINA", "UNIDADE", "TERMELETRICA", "TERMOELETRICA", "TERMICA", "COMPLEXO", "INDUSTRIAL", "TRATAMENTO", "GAS", "PORTO", "TERMINAL", "ARMAZENAMENTO", "DE", "DO", "DA", "DOS", "DAS", "E"}

def _palavras_significativas(t):
    return {p for p in t.split() if p not in _PALAVRAS_GENERICAS_UNIDADE and len(p) > 2}

def buscar_contatos_por_estacao(nome_estacao):
    alvo = _normalizar_nome(str(nome_estacao))
    if not alvo: return None
    palavras_alvo = _palavras_significativas(alvo)
    melhor_substring, melhor_tam, melhor_palavras, melhor_qtd = None, 0, None, 0
    for chave, info in CONTATOS_UNIDADES.items():
        candidatos = [chave, info["nome"]] + ALIASES_UNIDADES.get(chave, [])
        for bruto in candidatos:
            candidato = _normalizar_nome(bruto)
            if not candidato: continue
            if candidato == alvo: return info
            if len(candidato) >= 4 and (candidato in alvo or alvo in candidato):
                if len(candidato) > melhor_tam:
                    melhor_substring, melhor_tam = info, len(candidato)
            pc = _palavras_significativas(candidato)
            if len(pc) >= 2 and pc and pc <= palavras_alvo:
                if len(pc) > melhor_qtd:
                    melhor_palavras, melhor_qtd = info, len(pc)
    return melhor_substring or melhor_palavras

# ======================================================================
# ESTAÇÕES
# ======================================================================
ESTACOES_PADRAO = [
    {"estacao": "UTE Termocamaçari - UTE TCA", "lat": -12.66687, "lon": -38.31469},
    {"estacao": "UTE Termobahia - UTE TBA", "lat": -12.70324, "lon": -38.5649},
    {"estacao": "UTE Termoceará - UTE TCE", "lat": -3.69246, "lon": -38.87061},
    {"estacao": "UTE Vale do Açu - UTE VLA", "lat": -5.38169, "lon": -36.81975},
    {"estacao": "Refinaria Abreu e Lima - RNEST", "lat": -8.37966, "lon": -35.0102},
    {"estacao": "Unidade de Tratamento de Gás Sul Capixaba - UTGSUL", "lat": -20.79446, "lon": -40.62091},
    {"estacao": "Unidade de Tratamento de Gás de Cacimbas - UTGC", "lat": -19.4631, "lon": -39.7606},
    {"estacao": "Refinaria Duque de Caxias - REDUC", "lat": -22.7151, "lon": -43.28401},
    {"estacao": "UTE Termorio - UTE TRI", "lat": -22.71488, "lon": -43.25435},
    {"estacao": "BOAVENTURA, Itaboraí-RJ", "lat": -22.66071, "lon": -42.85363},
    {"estacao": "Unidade de Tratamento de Gás de Cabiúnas - UTGCAB", "lat": -22.28533, "lon": -41.71791},
    {"estacao": "UTE Termomacaé - UTE TMA", "lat": -22.30616, "lon": -41.8767},
    {"estacao": "UTE Seropédica/Baixada Fluminense - UTE SRP/BF", "lat": -22.72329, "lon": -43.64772},
    {"estacao": "Refinaria Gabriel Passos - REGAP", "lat": -19.96428, "lon": -44.09514},
    {"estacao": "UTE Ibirité - UTE IBT", "lat": -19.98858, "lon": -44.09821},
    {"estacao": "UTE Juiz de Fora - UTE JF", "lat": -21.69062, "lon": -43.45672},
    {"estacao": "UTE Três Lagoas - UTE TLG", "lat": -20.7455, "lon": -51.66459},
    {"estacao": "UFN III - Unidade de Fertilizantes Nitrogenados III", "lat": -20.9859, "lon": -51.8383},
    {"estacao": "Unidade de Tratamento de Gás de Caraguatatuba - UTGCA", "lat": -23.65419, "lon": -45.50121},
    {"estacao": "Refinaria Presidente Bernardes - RPBC", "lat": -23.87333, "lon": -46.42757},
    {"estacao": "UTE Cubatão - UTE CBT", "lat": -23.87573, "lon": -46.43139},
    {"estacao": "Refinaria Henrique Lage - REVAP", "lat": -23.1848, "lon": -45.81581},
    {"estacao": "Refinaria de Capuava - RECAP", "lat": -23.65668, "lon": -46.48088},
    {"estacao": "Refinaria de Paulínia - REPLAN", "lat": -22.72959, "lon": -47.14771},
    {"estacao": "UTE Nova Piratininga - UTE NPI", "lat": -23.69941, "lon": -46.67388},
    {"estacao": "Refinaria Presidente Getúlio Vargas - REPAR", "lat": -25.56614, "lon": -49.36942},
    {"estacao": "Refinaria Alberto Pasqualini - REFAP", "lat": -29.8699, "lon": -51.17819},
    {"estacao": "UTE Canoas - UTE CAN", "lat": -29.87507, "lon": -51.14544},
    {"estacao": "Armazém Rio de Janeiro", "lat": -22.81097, "lon": -43.28188},
    {"estacao": "CILEP - CENPES", "lat": -22.8542, "lon": -43.23383},
    {"estacao": "Porto Baia de Guanabara", "lat": -22.87894, "lon": -43.20933},
    {"estacao": "ARM Macaé - Armazém Macaé", "lat": -22.41532, "lon": -41.86135},
    {"estacao": "Porto de Imbetiba - Macaé", "lat": -22.38683, "lon": -41.76874},
    {"estacao": "Porto Açu", "lat": -21.86474, "lon": -41.01644},
    {"estacao": "Porto Aratu", "lat": -12.78013, "lon": -38.49676},
    {"estacao": "Porto TMIB", "lat": -10.82413, "lon": -36.9463},
    {"estacao": "Porto Belém", "lat": -1.4399, "lon": -48.49492},
    {"estacao": "Porto Valença", "lat": -13.36937, "lon": -39.07125},
    {"estacao": "Porto Guamaré", "lat": -5.10669, "lon": -36.31959},
    {"estacao": "Porto Mucuripe", "lat": -3.71312, "lon": -38.47404},
    {"estacao": "Porto Paracuru", "lat": -3.40115, "lon": -39.0109},
]

# Anéis de distância (km) e paletas de cor. No mapa cada anel ganha também um contorno
# escuro por baixo, pra se destacar do mapa e do GOES-East.
DISTANCIAS_ANEIS_KM = [30, 50, 100, 200]
PALETAS_ANEIS = {
    "Padrão (azul · verde · laranja · vermelho)": ["#2f6bff", "#00c853", "#ff8f00", "#ff1744"],
    "Alto contraste (ciano · magenta · branco · lilás)": ["#00e5ff", "#ff2bd6", "#ffffff", "#b388ff"],
    "Vivas (azul · lima · amarelo · rosa)": ["#00b0ff", "#76ff03", "#ffea00", "#ff4081"],
    "Quentes (amarelo · laranja · vermelho · vinho)": ["#ffd600", "#ff9100", "#ff3d00", "#c2185b"],
    "Frias (ciano · azul · índigo · roxo)": ["#00e5ff", "#2979ff", "#651fff", "#d500f9"],
    "Semáforo (verde · amarelo · laranja · vermelho)": ["#00e676", "#ffea00", "#ff9100", "#ff1744"],
    "Daltonismo (azul · celeste · laranja · vermelhão)": ["#0072b2", "#56b4e9", "#e69f00", "#d55e00"],
}

# Tamanho (raio em pixels) das bolinhas de raio no mapa.
TAMANHO_BOLINHA_RAIO = 5.0

# Limite apenas para a visualização no navegador (por faixa de idade de 5 min,
# pra que os raios mais antigos também apareçam). Os cálculos de alerta
# continuam usando TODOS os raios disponíveis na janela selecionada.
MAX_RAIOS_POR_FAIXA = 2500

# Janela usada nos alertas e no rastreio de células (mantida em 15 min).
# O mapa mostra 20 min de raios, mas isso não muda a sensibilidade dos alertas.
JANELA_ALERTA_MIN = 15

# Alerta verde: depois de um alerta vermelho (raio a <= 30 km), a unidade é "liberada" quando o ÚLTIMO
# ponto de raio a menos de VERDE_RAIO_KM km some do mapa (os pontos ficam 20 min: vermelho, laranja,
# amarelo e, por fim, verde) e passam mais VERDE_MINUTOS_SEM_RAIO minutos. Ou seja: 20 + 5 = 25 min
# depois do último raio dentro de 30 km.
VERDE_RAIO_KM = 30
VERDE_MINUTOS_SEM_RAIO = 5

GLM_BUCKET = "noaa-goes19"
GLM_BASE_URL = f"https://{GLM_BUCKET}.s3.amazonaws.com"
SOUTH_AMERICA_BOUNDS = {"lat_min": -58.0, "lat_max": 13.5, "lon_min": -82.0, "lon_max": -33.0}
BRAZIL_BOUNDS = {"lat_min": -34.0, "lat_max": 5.5, "lon_min": -74.5, "lon_max": -32.0}

def montar_mensagem_proximidade_raio(nivel_km, nome_estacao, meteorologista):
    agora = utc_para_brasilia(datetime.now(timezone.utc))
    validade = agora + timedelta(hours=1)
    janela = "-15 min até o momento" if nivel_km == 30 else "-30 min até o momento"
    emoji = "🔴" if nivel_km == 30 else "🟡"
    return (f"{emoji} {agora.strftime('%d/%m/%Y')} - {agora.strftime('%H:%M')}\n"
            f"* Local: {nome_estacao}\n"
            f"* Meteorologista: {meteorologista or '(não informado)'}\n"
            f"* Raios próximos de sua região ({janela})\n"
            f"Válido até as {validade.strftime('%H:%M')}")

def montar_mensagem_alerta_verde(nome_estacao, meteorologista):
    agora = utc_para_brasilia(datetime.now(timezone.utc))
    return (f"🟢 {agora.strftime('%d/%m/%Y')} - {agora.strftime('%H:%M')}\n"
            f"* Local: {nome_estacao}\n"
            f"* Meteorologista: {meteorologista or '(não informado)'}\n"
            f"* FIM DO ALERTA DE RAIOS")

def ultimo_raio_ate_km(raios_df, lat, lon, km):
    """Horário (UTC) do raio mais recente a até `km` km do ponto, ou None se não houver."""
    if raios_df is None or raios_df.empty: return None
    lat_r = np.radians(pd.to_numeric(raios_df["lat"], errors="coerce").to_numpy(dtype=float))
    lon_r = np.radians(pd.to_numeric(raios_df["lon"], errors="coerce").to_numpy(dtype=float))
    ok = np.isfinite(lat_r) & np.isfinite(lon_r)
    if not ok.any(): return None
    lat1, lon1 = math.radians(lat), math.radians(lon)
    a = np.sin((lat_r - lat1) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat_r) * np.sin((lon_r - lon1) / 2.0) ** 2
    d = 2.0 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    m = ok & (d <= km)
    if not m.any(): return None
    return pd.to_datetime(raios_df["time"], utc=True)[m].max().to_pydatetime()

def classificar_risco_raio(dist_min_km):
    """Classifica o risco somente quando existe raio dentro de 50 km."""
    if dist_min_km is None or not np.isfinite(dist_min_km):
        return 0, "Sem raios próximos", "🟢", "#19d36b", None
    if dist_min_km <= 30:
        return 2, "Alto — raio a menos de 30 km", "🔴", "#ff2d44", "vermelho"
    if dist_min_km <= 50:
        return 1, "Médio — raio a menos de 50 km", "🟡", "#ffc400", "amarelo"
    return 0, "Sem raios próximos", "🟢", "#19d36b", None

def calcular_status_estacoes(df_stations, raios_df, encerrados=None):
    """Calcula a distância geodésica real até o raio mais próximo da janela atual."""
    linhas = []
    tem_raios = raios_df is not None and not raios_df.empty
    if tem_raios:
        raio_lat = pd.to_numeric(raios_df["lat"], errors="coerce").to_numpy(dtype=float)
        raio_lon = pd.to_numeric(raios_df["lon"], errors="coerce").to_numpy(dtype=float)
        valido = np.isfinite(raio_lat) & np.isfinite(raio_lon)
        raio_lat = np.radians(raio_lat[valido])
        raio_lon = np.radians(raio_lon[valido])
        raio_t = pd.to_datetime(raios_df["time"], utc=True).dt.tz_localize(None).to_numpy()[valido]

    for _, row in df_stations.iterrows():
        nome_completo = str(row["estacao"])
        nome = nome_completo.split(" - ")[0]
        lat, lon = float(row["lat"]), float(row["lon"])
        dist_min = None
        if tem_raios and len(raio_lat):
            lat1 = math.radians(lat)
            lon1 = math.radians(lon)
            dlat = raio_lat - lat1
            dlon = raio_lon - lon1
            a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(raio_lat) * np.sin(dlon / 2.0) ** 2
            dists = 2.0 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
            corte = (encerrados or {}).get(nome_completo)
            if corte is not None:
                # alerta verde já emitido: raios a <= 30 km ANTERIORES ao encerramento não contam mais
                ignorar = (dists <= VERDE_RAIO_KM) & (raio_t <= np.datetime64(corte.replace(tzinfo=None)))
                dists = np.where(ignorar, np.inf, dists)
            dist_min = float(dists.min()) if np.isfinite(dists.min()) else None

        score, label, emoji, color, nivel_chave = classificar_risco_raio(dist_min)
        contatos = buscar_contatos_por_estacao(nome_completo)
        linhas.append({
            "estacao": nome_completo, "nome": nome, "lat": lat, "lon": lon,
            "dist_min_km": dist_min, "risco_score": score, "risco_label": label,
            "risco_emoji": emoji, "risco_color": color, "nivel_chave": nivel_chave,
            "contatos": contatos,
        })
    return pd.DataFrame(linhas)

# ======================================================================
# GLM — RAIOS
# ======================================================================
def build_session():
    s = requests.Session()
    retries = Retry(total=8, backoff_factor=4, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"], respect_retry_after_header=True)
    a = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", a); s.mount("http://", a)
    s.headers.update({"User-Agent": "BlueOceanApp/1.0 (uso pessoal/operacional - contato via Streamlit)"})
    return s

def _parse_glm_timestamp(nome):
    m = re.search(r"_s(\d{13})", nome)
    if not m: return None
    b = m.group(1)
    ano, doy = int(b[0:4]), int(b[4:7])
    hh, mm, ss = int(b[7:9]), int(b[9:11]), int(b[11:13])
    return datetime(ano, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=hh, minutes=mm, seconds=ss)

def _listar_arquivos_glm_hora(session, ano, doy, hora):
    prefixo = f"GLM-L2-LCFA/{ano}/{doy:03d}/{hora:02d}/"
    url = f"{GLM_BASE_URL}/?list-type=2&prefix={prefixo}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    root = ET.fromstring(r.content)
    return [el.text for el in root.findall(".//s3:Key", ns)]

@st.cache_data(show_spinner=False, ttl=90)
def fetch_glm_flashes_recent(minutos=15):
    import netCDF4
    session = build_session()
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(minutes=minutos)
    horas = {(agora.year, agora.timetuple().tm_yday, agora.hour)}
    if inicio.hour != agora.hour or inicio.timetuple().tm_yday != agora.timetuple().tm_yday:
        horas.add((inicio.year, inicio.timetuple().tm_yday, inicio.hour))

    chaves = []
    falhas = 0
    for ano, doy, hora in horas:
        try: chaves.extend(_listar_arquivos_glm_hora(session, ano, doy, hora))
        except Exception: falhas += 1
    if falhas == len(horas): raise RuntimeError("não foi possível conectar ao bucket GLM na AWS")

    arquivos = sorted(c for c in chaves if (ts := _parse_glm_timestamp(c)) is not None and ts >= inicio)
    if not arquivos: return pd.DataFrame(columns=["lat", "lon", "energy_j", "time"])

    linhas = []
    for chave in arquivos:
        try:
            r = session.get(f"{GLM_BASE_URL}/{chave}", timeout=30)
            r.raise_for_status()
            with netCDF4.Dataset("inmemory.nc", memory=r.content) as ds:
                lats = np.asarray(ds.variables["flash_lat"][:])
                lons = np.asarray(ds.variables["flash_lon"][:])
                energias = np.asarray(ds.variables["flash_energy"][:])
                ts_arquivo = _parse_glm_timestamp(chave)
                for lat, lon, en in zip(lats, lons, energias):
                    linhas.append({"lat": float(lat), "lon": float(lon), "energy_j": float(en), "time": ts_arquivo})
        except Exception: continue
    df = pd.DataFrame(linhas)
    if not df.empty:
        b = SOUTH_AMERICA_BOUNDS
        df = df[(df["lat"] >= b["lat_min"]) & (df["lat"] <= b["lat_max"]) &
                (df["lon"] >= b["lon_min"]) & (df["lon"] <= b["lon_max"])]
    return df

def _dist_km(lat1, lon1, lat2, lon2):
    dlat = (lat1 - lat2) * 111
    latm = (lat1 + lat2) / 2
    dlon = (lon1 - lon2) * 111 * math.cos(math.radians(latm))
    return math.hypot(dlat, dlon)

def _bearing_graus(lat1, lon1, lat2, lon2):
    lat1r, lon1r, lat2r, lon2r = map(math.radians, (lat1, lon1, lat2, lon2))
    dlon = lon2r - lon1r
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def _bearing_para_rumo(deg):
    rumos = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return rumos[round(deg / 45) % 8]

def _destino_ponto(lat, lon, bearing_deg, dist_km):
    R = 6371
    lat1, lon1, brng = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    lat2 = math.asin(math.sin(lat1) * math.cos(dist_km / R) + math.cos(lat1) * math.sin(dist_km / R) * math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng) * math.sin(dist_km / R) * math.cos(lat1), math.cos(dist_km / R) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def clusterizar_raios(raios_df, dist_km=18, min_pts=3):
    if raios_df.empty: return []
    pontos = raios_df[["lat", "lon"]].to_dict("records")
    n = len(pontos)
    tamanho_grade = dist_km / 111
    buckets = defaultdict(list)
    for i, p in enumerate(pontos):
        buckets[(int(p["lat"] // tamanho_grade), int(p["lon"] // tamanho_grade))].append(i)

    pai = list(range(n))
    def _find(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    def _uniao(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb: pai[ra] = rb

    dist2_lim = dist_km ** 2
    for (gx, gy), idxs in buckets.items():
        vizinhos = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                vizinhos.extend(buckets.get((gx + dx, gy + dy), []))
        for i in idxs:
            for j in vizinhos:
                if j <= i: continue
                dlat = (pontos[i]["lat"] - pontos[j]["lat"]) * 111
                latm = (pontos[i]["lat"] + pontos[j]["lat"]) / 2
                dlon = (pontos[i]["lon"] - pontos[j]["lon"]) * 111 * math.cos(math.radians(latm))
                if dlat * dlat + dlon * dlon <= dist2_lim:
                    _uniao(i, j)
    grupos_map = defaultdict(list)
    for i in range(n): grupos_map[_find(i)].append(pontos[i])
    return [g for g in grupos_map.values() if len(g) >= min_pts]

def _hull_convexo(pontos):
    """Casco convexo (monotone chain) de uma lista de dicts {lat, lon} —
    usado pra desenhar o contorno "nublado" ao redor de cada célula de
    raios, em vez de só os pontos soltos. Expande um pouco pra fora do
    centro pra dar aquele efeito de área/nuvem em vez de polígono
    apertadinho nos pontos."""
    pts = sorted({(p["lon"], p["lat"]) for p in pontos})
    if len(pts) < 3:
        return [{"lat": p[1], "lon": p[0]} for p in pts]

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    inferior = []
    for p in pts:
        while len(inferior) >= 2 and cruz(inferior[-2], inferior[-1], p) <= 0:
            inferior.pop()
        inferior.append(p)
    superior = []
    for p in reversed(pts):
        while len(superior) >= 2 and cruz(superior[-2], superior[-1], p) <= 0:
            superior.pop()
        superior.append(p)
    casco = inferior[:-1] + superior[:-1]

    cx = sum(p[0] for p in casco) / len(casco)
    cy = sum(p[1] for p in casco) / len(casco)
    fator = 1.18
    return [{"lat": cy + (p[1] - cy) * fator, "lon": cx + (p[0] - cx) * fator} for p in casco]

def atualizar_celulas_raio(grupos, agora_ts):
    celulas = st.session_state.get("celulas_raio", [])
    usadas = set()
    for grupo in grupos:
        lat = sum(p["lat"] for p in grupo) / len(grupo)
        lon = sum(p["lon"] for p in grupo) / len(grupo)
        melhor, menor_dist = None, float("inf")
        for cel in celulas:
            if cel["id"] in usadas: continue
            ult = cel["historico"][-1]
            d = _dist_km(lat, lon, ult["lat"], ult["lon"])
            if d < menor_dist:
                menor_dist, melhor = d, cel
        if melhor is not None and menor_dist <= 60:
            alvo = melhor
        else:
            novo_id = st.session_state.get("proximo_id_celula", 1)
            alvo = {"id": novo_id, "historico": []}
            st.session_state.proximo_id_celula = novo_id + 1
            celulas.append(alvo)
        alvo["historico"].append({"lat": lat, "lon": lon, "t": agora_ts, "n": len(grupo)})
        if len(alvo["historico"]) > 6: alvo["historico"] = alvo["historico"][-6:]
        alvo["ultima_atualizacao"] = agora_ts
        usadas.add(alvo["id"])
    celulas = [c for c in celulas if agora_ts - c["ultima_atualizacao"] <= 900]
    st.session_state.celulas_raio = celulas
    return celulas

def calcular_trajetoria_celula(celula):
    hist = celula["historico"]
    if len(hist) < 2: return None
    referencia, atual = hist[0], hist[-1]
    dist_km = _dist_km(referencia["lat"], referencia["lon"], atual["lat"], atual["lon"])
    horas = max((atual["t"] - referencia["t"]) / 3600, 1 / 3600)
    vel_kmh = dist_km / horas
    rumo_graus = _bearing_graus(referencia["lat"], referencia["lon"], atual["lat"], atual["lon"])
    rumo_texto = _bearing_para_rumo(rumo_graus)
    checkpoints = []
    if len(hist) >= 3 and 2 <= vel_kmh <= 120:
        b = SOUTH_AMERICA_BOUNDS
        for passo in range(1, 4):
            minutos_futuro = passo * 30
            dist_proj = vel_kmh * (minutos_futuro / 60)
            lat2, lon2 = _destino_ponto(atual["lat"], atual["lon"], rumo_graus, dist_proj)
            if not (b["lat_min"] <= lat2 <= b["lat_max"] and b["lon_min"] <= lon2 <= b["lon_max"]): break
            checkpoints.append({"lat": lat2, "lon": lon2, "min": minutos_futuro})
    return {"vel_kmh": vel_kmh, "rumo_texto": rumo_texto, "checkpoints": checkpoints}

# ======================================================================
# TEXTO PRA COPIAR — insere a linha "Quem recebeu o alerta" (preenchida
# na hora, na aba Alertas) antes da linha final "Válido até as HH:MM".
# ======================================================================
def montar_texto_copia(alerta):
    linhas = alerta["texto"].split("\n")
    quem = (alerta.get("quem_recebeu") or "").strip()
    if alerta.get("nivel") == "verde":
        linhas.insert(-1, f"* Quem Recebeu o Alerta: {quem}".rstrip())
    else:
        linhas.insert(-1, f"* Quem recebeu o alerta: {quem}")
    return "\n".join(linhas)

# ======================================================================
# INTERFACE STREAMLIT
# ======================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: radial-gradient(circle at top left, #101825 0%, #0a0e15 55%, #05070a 100%); }
section[data-testid="stSidebar"] { background-color: #10151d; border-right: 1px solid #1f2733; }
section[data-testid="stSidebar"] h3 { color: #3fc2c2; }
h1, h2, h3 { letter-spacing: -0.01em; }
.bo-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
             padding: 14px 20px; margin-bottom: 6px; border-radius: 14px;
             background: linear-gradient(120deg, #101f2b 0%, #0c151f 100%); border: 1px solid #1f2d3a; }
.bo-header { gap: 18px; }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 0.8rem 0.5rem 3rem !important; }
  .bo-header { padding: 10px 12px; gap: 8px; border-radius: 12px; }
  .bo-brand { gap: 10px; }
  .bo-logo { height: 48px; padding: 4px 8px; border-radius: 9px; }
  .bo-header h1 { font-size: 1.0rem; }
  .bo-header h1 .bo-sub { display: block; font-size: 0.8rem; }
  .bo-header p { font-size: 0.72rem; }
}
/* Barra de rolagem mais grossa. Chrome/Edge/Safari usam ::-webkit-scrollbar; no Firefox vale a espessura "auto"
   (a largura exata no Firefox/Linux depende da configuração do sistema). */
@supports selector(::-webkit-scrollbar) {
  ::-webkit-scrollbar { width: 18px; height: 18px; }
  ::-webkit-scrollbar-track { background: #11151c; }
  ::-webkit-scrollbar-thumb { background: #3fc2c2; border: 4px solid #11151c; border-radius: 12px; }
  ::-webkit-scrollbar-thumb:hover { background: #63d8d8; }
  ::-webkit-scrollbar-corner { background: #11151c; }
}
@supports not selector(::-webkit-scrollbar) {
  * { scrollbar-width: auto; scrollbar-color: #3fc2c2 #11151c; }
}
.bo-brand { display: flex; align-items: center; gap: 18px; min-width: 0; }
.bo-logo { background: #fdfdfd; border-radius: 12px; padding: 6px 12px; height: 74px; width: auto; flex-shrink: 0;
           box-shadow: 0 2px 10px rgba(0,0,0,0.35); }
.bo-header h1 { margin: 0; font-size: 1.5rem; color: #eaf6f6; line-height: 1.25; }
.bo-header h1 .bo-sub { font-weight: 500; font-size: 1.05rem; color: #9db4c0; }
.bo-header p { margin: 2px 0 0; color: #8b93a3; font-size: 0.85rem; }
.bo-pill { display: inline-block; padding: 6px 16px; border-radius: 999px; font-weight: 600; font-size: 0.85rem; white-space: nowrap; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px !important; }
.stButton>button[kind="primary"] { background-color: #3fc2c2; border-color: #3fc2c2; }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------------------------
# Persistência entre reinícios da sessão.
# Se a conexão da página cai (computador suspenso, aba em segundo plano, rede instável...), o Streamlit
# abre uma sessão NOVA e o st.session_state volta vazio: pedia o nome de novo e os alertas "recomeçavam"
# (notificando e tocando som outra vez). Para evitar isso:
#  - o nome fica na URL (?nome=...) e é lido de lá se a sessão nova estiver sem nome;
#  - o estado dos alertas fica guardado no servidor, identificado por um código na URL (?sid=...),
#    e é restaurado quando a mesma URL reabre.
# ----------------------------------------------------------------------------------------------
_CHAVES_PERSISTENTES = ("meteorologista_nome", "alertas_raio_ativos", "alertas_unidade", "verde_estado", "som_token", "altura_mapa_pct")

@st.cache_resource
def _armazem_sessoes():
    return {}

def _salvar_estado():
    try:
        arm = _armazem_sessoes()
        sid = st.query_params.get("sid")
        if not sid:
            return
        arm[sid] = {"_ts": time.time(), **{k: copy.deepcopy(st.session_state[k]) for k in _CHAVES_PERSISTENTES if k in st.session_state}}
        if len(arm) > 60:  # mantém só os mais recentes
            for velho in sorted(arm, key=lambda k: arm[k].get("_ts", 0))[:len(arm) - 60]:
                arm.pop(velho, None)
    except Exception:
        pass  # guardar o estado nunca pode derrubar o app

if not st.query_params.get("sid"):
    st.query_params["sid"] = uuid.uuid4().hex[:12]
if "_estado_restaurado" not in st.session_state:
    st.session_state["_estado_restaurado"] = True
    _salvo = _armazem_sessoes().get(st.query_params.get("sid"))
    if _salvo:
        for _k in _CHAVES_PERSISTENTES:
            if _k in _salvo and _k not in st.session_state:
                st.session_state[_k] = copy.deepcopy(_salvo[_k])
    if not str(st.session_state.get("meteorologista_nome", "")).strip() and str(st.query_params.get("nome", "")).strip():
        st.session_state["meteorologista_nome"] = str(st.query_params.get("nome")).strip()

if "alertas_raio_ativos" not in st.session_state: st.session_state.alertas_raio_ativos = []
if "alertas_unidade" not in st.session_state: st.session_state.alertas_unidade = {}
if "verde_estado" not in st.session_state: st.session_state.verde_estado = {}

# Na primeira abertura, identifica imediatamente o meteorologista responsável.
# O restante da interface só é exibido depois da confirmação do nome.
if "meteorologista_nome" not in st.session_state or not str(st.session_state.get("meteorologista_nome", "")).strip():
    @st.dialog("👤 Identificação do Meteorologista")
    def _dialog_meteorologista_inicial():
        st.markdown("### Bem-vindo ao RIO")
        st.write("Informe o nome do meteorologista responsável pelo monitoramento para iniciar a operação.")
        nome = st.text_input(
            "Nome do Meteorologista",
            key="meteorologista_inicial_input",
            placeholder="Digite seu nome",
            label_visibility="visible",
        )
        if st.button("Entrar no monitoramento", type="primary", use_container_width=True):
            nome = str(nome).strip()
            if nome:
                st.session_state.meteorologista_nome = nome
                st.query_params["nome"] = nome
                _salvar_estado()
                st.rerun()
            else:
                st.warning("Digite o nome do meteorologista para continuar.")

    _dialog_meteorologista_inicial()
    st.stop()

if str(st.session_state.get("meteorologista_nome", "")).strip() and st.query_params.get("nome") != st.session_state["meteorologista_nome"]:
    st.query_params["nome"] = st.session_state["meteorologista_nome"]

with st.sidebar:
    st.header("⚙ Configuração")
    meteorologista = st.text_input(
        "Meteorologista responsável",
        value=st.session_state.get("meteorologista_nome", ""),
        key="meteorologista_responsavel",
    )
    if meteorologista.strip() != st.session_state.get("meteorologista_nome", ""):
        st.session_state.meteorologista_nome = meteorologista.strip()
        if meteorologista.strip():
            st.query_params["nome"] = meteorologista.strip()

    df_stations = pd.DataFrame(ESTACOES_PADRAO)

    st.subheader("⚡ Raios ao vivo (GLM/GOES-19)")
    raios_minutos = 20  # janela exibida no mapa (cores: 0–5 · 5–10 · 10–15 · 15–20 min)
    intervalo_raios_seg = 120
    st.caption("🔄 Atualização automática: a cada 2 minutos")
    st.caption("🔊 O som e o pop-up automático de alerta ficam sempre ativos.")
    arquivo_som = st.file_uploader("Trocar o som de alerta (opcional)", type=["mp3", "wav", "ogg", "m4a"])
    mostrar_deslocamento = st.checkbox("Mostrar deslocamento das células de tempestade", value=True)

    st.subheader("📏 Anéis de distância no mapa")
    mostrar_aneis = st.checkbox("Mostrar anéis de distância ao redor das unidades", value=True)
    paleta_escolhida = st.selectbox("Cores dos anéis", list(PALETAS_ANEIS), disabled=not mostrar_aneis)
    cores_aneis = PALETAS_ANEIS[paleta_escolhida]

    st.subheader("🗺️ Mapa")
    if "altura_mapa_pct" not in st.session_state:
        st.session_state["altura_mapa_pct"] = 86      # padrão (também pode vir restaurado da sessão anterior)
    altura_mapa_pct = st.slider("Altura do mapa (% da altura da janela)", min_value=60, max_value=120, step=1, key="altura_mapa_pct",
                                help="86% é o padrão. Aumente para deixar o mapa mais alto (entre 700 e 1400 px; no celular em pé fica fixo).")

# --------------------------------------------------------------
# Som de alerta personalizado: se a pessoa subiu um arquivo, ele vira um
# data URI (base64) embutido direto no HTML do mapa — sem gravar nada em
# disco, então não depende do static file serving do Streamlit Cloud.
# Fica valendo enquanto durar a sessão.
# --------------------------------------------------------------
_MIME_SOM = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}
if arquivo_som is not None:
    ext = os.path.splitext(arquivo_som.name)[1].lower() or ".mp3"
    conteudo = arquivo_som.getvalue()
    b64 = base64.b64encode(conteudo).decode("ascii")
    som_data_uri = f"data:{_MIME_SOM.get(ext, 'audio/mpeg')};base64,{b64}"
    st.sidebar.audio(arquivo_som, format=f"audio/{ext.lstrip('.')}")
else:
    som_data_uri = _som_padrao_data_uri()

df_status_atual = st.session_state.get("_fragment_df_status")
if df_status_atual is not None and not df_status_atual.empty:
    n_vermelho = int((df_status_atual["nivel_chave"] == "vermelho").sum())
    n_amarelo = int((df_status_atual["nivel_chave"] == "amarelo").sum())
    if n_vermelho: pill_html = f'<span class="bo-pill" style="background:#4a1414; color:#ff8a80;">🔴 {n_vermelho} unidade(s) em alerta vermelho</span>'
    elif n_amarelo: pill_html = f'<span class="bo-pill" style="background:#463a10; color:#ffd166;">🟡 {n_amarelo} unidade(s) em alerta amarelo</span>'
    else: pill_html = '<span class="bo-pill" style="background:#123321; color:#7ee2a8;">🟢 Nenhuma unidade em alerta</span>'
else:
    pill_html = '<span class="bo-pill" style="background:#1f2733; color:#8b93a3;">⏳ carregando…</span>'

st.markdown(f"""
<div class="bo-header">
  <div class="bo-brand">
    <img class="bo-logo" src="{_logo_data_uri()}" alt="RIO" />
    <div>
      <h1>RIO — Rede Inteligente de Observação <span class="bo-sub">(de descargas atmosféricas)</span></h1>
      <p>Monitoramento de raios em tempo real (GLM/GOES-19) — by Mário Henrique</p>
    </div>
  </div>
  {pill_html}
</div>
""", unsafe_allow_html=True)

# Painel de alertas retrátil: recolhido, o mapa ocupa a largura toda. As colunas continuam as mesmas
# (só muda a proporção), então o mapa não é recarregado ao abrir/fechar o painel.
_, _col_toggle = st.columns([3, 1])
with _col_toggle:
    mostrar_painel_alertas = st.toggle("🚨 Painel de alertas", value=False, key="mostrar_painel_alertas",
                                       help="Mostra ou esconde o painel lateral de risco e alertas. Escondido, o mapa fica maior; "
                                            "os avisos de raio continuam aparecendo em pop-up.")
col_mapa, col_lado = st.columns([2.4, 1] if mostrar_painel_alertas else [1000, 1])
st.session_state["_run_completo"] = True

def _corpo_dialog_alerta_raio():
    texto = st.session_state.get("dialog_raio_texto")
    if not texto: return
    n_unidades = texto.count("* Local:")
    if st.session_state.get("dialog_raio_so_verde"):
        if n_unidades > 1:
            st.success(f"**{n_unidades} unidades** sem raios a menos de {VERDE_RAIO_KM} km (o último ponto saiu do mapa há {VERDE_MINUTOS_SEM_RAIO} min). Copie as mensagens abaixo:")
        else:
            st.success(f"Unidade sem raios a menos de {VERDE_RAIO_KM} km (o último ponto saiu do mapa há {VERDE_MINUTOS_SEM_RAIO} min). Copie a mensagem abaixo:")
    elif n_unidades > 1:
        st.warning(f"Foram detectados raios próximos de **{n_unidades} unidades** monitoradas ao mesmo tempo. Copie as mensagens abaixo:")
    else:
        st.warning("Foi detectado um raio próximo de uma unidade monitorada. Copie a mensagem abaixo:")
    st.code(texto, language=None)

def _preparar_payload_raios(raios_df, celulas_com_trajetoria):
    """Monta os pontos de raio e as células de tempestade no formato que o
    JS do mapa desenha — embutido direto no HTML (ver nota acima sobre por
    que não gravamos mais isso num arquivo estático à parte)."""
    agora = datetime.now(timezone.utc)
    raios_out = []
    if raios_df is not None and not raios_df.empty:
        # O processamento de alertas usa a série completa. Pro navegador, os raios são
        # agrupados em faixas de 5 min; em cada faixa, pontos praticamente sobrepostos
        # (mesma grade de ~3 km) viram um só e, se ainda passar do limite, é feita uma
        # amostra. Antes só os mais recentes eram enviados, e os antigos sumiam.
        df = raios_df.dropna(subset=["lat", "lon", "time"]).copy()
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["idade_min"] = ((agora - df["time"]).dt.total_seconds() / 60).clip(lower=0)
        df["faixa"] = (df["idade_min"] // 5).clip(upper=3).astype(int)
        df["gx"] = (df["lat"] / 0.03).round().astype(int)
        df["gy"] = (df["lon"] / 0.03).round().astype(int)
        df = df.sort_values("time", ascending=False).drop_duplicates(["gx", "gy", "faixa"])
        partes = []
        for _, g in df.groupby("faixa"):
            partes.append(g.sample(MAX_RAIOS_POR_FAIXA, random_state=1) if len(g) > MAX_RAIOS_POR_FAIXA else g)
        raios_mapa = pd.concat(partes).sort_values("time", kind="stable") if partes else df  # antigos primeiro, novos por cima
        for r in raios_mapa.itertuples():
            raios_out.append({
                "lat": float(r.lat), "lon": float(r.lon),
                "idade_min": round(float(r.idade_min), 1),
                "hora": utc_para_brasilia(r.time).strftime("%H:%M:%S"),
            })
    celulas_out = []
    for cel in celulas_com_trajetoria:
        traj = cel["trajetoria"]
        celulas_out.append({
            "id": cel["id"],
            "historico": [{"lat": p["lat"], "lon": p["lon"]} for p in cel["historico"]],
            "checkpoints": traj["checkpoints"],
            "vel_kmh": round(traj["vel_kmh"], 1),
            "rumo_texto": traj["rumo_texto"],
        })
    return {"raios": raios_out, "celulas": celulas_out}

def _renderizar_mapa_ao_vivo():
    """Busca os raios, agrupa em células, calcula o status de cada unidade
    e desenha o mapa inteiro já com os dados embutidos no HTML.

    Importante: essa versão não lê mais nenhum arquivo estático via fetch()
    — no Streamlit Community Cloud, arquivos GRAVADOS em disco durante a
    execução do app não têm entrega garantida pelo static file serving
    (só os arquivos que já vêm no repositório do GitHub são servidos de
    forma confiável). Era por isso que às vezes o mapa não mostrava os
    raios. Agora o mapa é reconstruído a cada ciclo (a cada N segundos,
    configurável na barra lateral) já com os dados prontos — e guarda o
    zoom/posição no localStorage do navegador pra não "pular" a cada
    atualização."""
    raios_df = pd.DataFrame()
    celulas_com_trajetoria = []
    erro = None
    try:
        raios_df = fetch_glm_flashes_recent(minutos=raios_minutos)
        st.session_state.ultima_atualizacao_raios = datetime.now(timezone.utc)
        st.session_state.ultimo_erro_raios = None
    except Exception as e:
        erro = str(e)
        st.session_state.ultimo_erro_raios = erro

    raios_alerta = raios_df
    if not raios_df.empty:
        corte_alerta = datetime.now(timezone.utc) - timedelta(minutes=JANELA_ALERTA_MIN)
        raios_alerta = raios_df[raios_df["time"] >= corte_alerta]

    if mostrar_deslocamento and not raios_alerta.empty:
        grupos = clusterizar_raios(raios_alerta)
        agora_ts = time.time()
        celulas = atualizar_celulas_raio(grupos, agora_ts)
        for cel in celulas:
            traj = calcular_trajetoria_celula(cel)
            if traj is not None: celulas_com_trajetoria.append({**cel, "trajetoria": traj})

    def _encerrados_verde():
        return {k: datetime.fromtimestamp(v["encerrado_ts"], tz=timezone.utc)
                for k, v in st.session_state.alertas_unidade.items() if v.get("encerrado_ts")}

    df_status = calcular_status_estacoes(df_stations, raios_alerta, encerrados=_encerrados_verde())

    # ---- Alerta verde ----
    # Só quando o GLM foi lido com sucesso agora (sem dados não dá pra dizer que não há raios).
    notificacoes_verde = []
    if erro is None:
        agora_utc = datetime.now(timezone.utc)
        for _, est in df_status.iterrows():
            chave_v = est["estacao"]
            sv = st.session_state.verde_estado.setdefault(chave_v, {"vermelho_ativo": False, "ultimo_raio": None})
            if est["nivel_chave"] == "vermelho":
                sv["vermelho_ativo"] = True
            if not sv["vermelho_ativo"]:
                continue
            ultimo = ultimo_raio_ate_km(raios_df, float(est["lat"]), float(est["lon"]), VERDE_RAIO_KM)
            if ultimo is not None and (sv["ultimo_raio"] is None or ultimo > sv["ultimo_raio"]):
                sv["ultimo_raio"] = ultimo
            if sv["ultimo_raio"] is None:
                continue
            # o último ponto some do mapa depois de `raios_minutos` min; a partir daí, espera mais VERDE_MINUTOS_SEM_RAIO
            if (agora_utc - sv["ultimo_raio"]) >= timedelta(minutes=raios_minutos + VERDE_MINUTOS_SEM_RAIO):
                agora_ts_v = time.time()
                texto_v = montar_mensagem_alerta_verde(est["nome"], meteorologista)
                st.session_state.alertas_raio_ativos.insert(0, {
                    "id": f"{chave_v}_verde_{agora_ts_v}", "texto": texto_v, "estacao": chave_v,
                    "nivel": "verde", "dist_km": None, "expira": agora_ts_v + 3600, "quem_recebeu": "",
                })
                notificacoes_verde.append(montar_texto_copia({"texto": texto_v, "nivel": "verde", "quem_recebeu": ""}))  # no pop-up já com a linha "Quem Recebeu o Alerta:"
                sv["vermelho_ativo"], sv["ultimo_raio"] = False, None
                reg = st.session_state.alertas_unidade.setdefault(chave_v, {
                    "nivel": "vermelho", "dist_km": None, "notificado_ts": agora_ts_v, "expira_ts": agora_ts_v + 3600})
                reg["encerrado_ts"] = agora_ts_v
        if notificacoes_verde:  # o status passa a refletir o encerramento já neste ciclo
            df_status = calcular_status_estacoes(df_stations, raios_alerta, encerrados=_encerrados_verde())
    st.session_state["_fragment_df_status"] = df_status

    estacoes_novas = []
    notificacoes_desta_rodada = []
    if not raios_alerta.empty:
        agora_ts = time.time()
        for _, est in df_status.iterrows():
            # Alerta só pode nascer de um raio REAL dentro de um dos
            # intervalos operacionais: <=30 km (vermelho) ou <=50 km (amarelo).
            nivel_atual = est["nivel_chave"]
            dist_atual = est["dist_min_km"]
            if nivel_atual not in ("vermelho", "amarelo") or pd.isna(dist_atual) or float(dist_atual) > 50:
                continue

            chave_estacao = est["estacao"]
            existente = st.session_state.alertas_unidade.get(chave_estacao)
            if existente is not None and existente.get("encerrado_ts"):
                # alerta já encerrado (verde): só volta a alertar se houver raio NOVO, depois do encerramento
                novo = ultimo_raio_ate_km(raios_df, float(est["lat"]), float(est["lon"]), 30 if nivel_atual == "vermelho" else 50)
                if novo is not None and novo.timestamp() > existente["encerrado_ts"]:
                    st.session_state.alertas_unidade.pop(chave_estacao, None)
                    existente = None
                else:
                    continue
            deve_notificar = False
            if existente is None:
                deve_notificar = True
            elif nivel_atual == "vermelho" and existente["nivel"] == "amarelo":
                deve_notificar = True
            elif agora_ts >= existente["expira_ts"]:
                deve_notificar = True

            if deve_notificar:
                st.session_state.alertas_unidade[chave_estacao] = {
                    "nivel": nivel_atual, "dist_km": float(dist_atual),
                    "notificado_ts": agora_ts, "expira_ts": agora_ts + 3600,
                }
                nivel_km = 30 if nivel_atual == "vermelho" else 50
                texto = montar_mensagem_proximidade_raio(nivel_km, est["nome"], meteorologista)
                st.session_state.alertas_raio_ativos.insert(0, {
                    "id": f"{chave_estacao}_{agora_ts}", "texto": texto, "estacao": chave_estacao,
                    "nivel": nivel_atual, "dist_km": float(dist_atual),
                    "expira": agora_ts + 3600, "quem_recebeu": "",
                })
                notificacoes_desta_rodada.append(texto)
                estacoes_novas.append(est["nome"])


    todas_notificacoes = notificacoes_desta_rodada + notificacoes_verde
    if todas_notificacoes:
        separador = "\n\n" + ("─" * 30) + "\n\n"
        st.session_state.dialog_raio_texto = separador.join(todas_notificacoes)
        st.session_state.dialog_raio_so_verde = not notificacoes_desta_rodada   # só alerta(s) verde(s) nesta rodada
        st.session_state.dialog_raio_pendente = True

    st.session_state.alertas_raio_ativos = [a for a in st.session_state.alertas_raio_ativos if a["expira"] > time.time()]

    ultima_att = st.session_state.get("ultima_atualizacao_raios")
    if ultima_att is not None:
        hora_brasilia = utc_para_brasilia(ultima_att).strftime("%H:%M:%S")
        status_texto = f"⚡ raios atualizados às {hora_brasilia}"
        st.caption(f"⚡ Raios (GLM/GOES-19) atualizados às **{hora_brasilia}** · atualiza automaticamente a cada {intervalo_raios_seg}s")
    else:
        status_texto = "⚡ carregando raios…"
    erro_raios = st.session_state.get("ultimo_erro_raios")
    if erro_raios:
        status_texto = f"⚠️ GLM indisponível: {erro_raios}"
        st.warning(f"GLM indisponível no momento: {erro_raios}")

    _salvar_estado()
    _construir_mapa(df_status, raios_df, celulas_com_trajetoria, estacoes_novas, status_texto)

    # Alerta novo surgiu numa atualização automática (só o fragmento rodou): pede uma
    # execução completa pra o pop-up ser aberto UMA vez no nível do script — assim ele
    # fica aberto até ser fechado e não reaparece nas atualizações seguintes.
    if st.session_state.get("dialog_raio_pendente") and not st.session_state.get("_run_completo"):
        st.rerun()

def _construir_mapa(df_status, raios_df, celulas_com_trajetoria, estacoes_novas, status_texto):
    estacoes_payload = [
        {
            "nome": e["nome"], "estacao": e["estacao"], "lat": e["lat"], "lon": e["lon"],
            "risco_emoji": e["risco_emoji"], "risco_label": e["risco_label"], "risco_color": e["risco_color"],
            "dist_min_km": e["dist_min_km"], "contatos": e["contatos"], "risco_score": int(e["risco_score"]),
        }
        for _, e in df_status.iterrows()
    ]
    aneis_payload = [{"km": km, "cor": cor} for km, cor in zip(DISTANCIAS_ANEIS_KM, cores_aneis) if mostrar_aneis]
    raios_payload = _preparar_payload_raios(raios_df, celulas_com_trajetoria)

    # Alertas ativos, pra aba "Alertas" do painel que fica dentro do mapa (usável em tela cheia).
    alertas_payload = [
        {"id": a["id"], "quem_recebeu": a.get("quem_recebeu", ""), "copia": montar_texto_copia(a)}
        for a in st.session_state.alertas_raio_ativos
    ]

    if estacoes_novas:
        st.session_state["som_token"] = f"{time.time():.3f}"

    evento = _mapa_raios_component(
        estacoes=estacoes_payload,
        alertas=alertas_payload,
        default=None,
        raios=raios_payload["raios"],
        celulas=raios_payload["celulas"],
        aneis=aneis_payload,
        janela_min=raios_minutos,
        tamanho_raio=TAMANHO_BOLINHA_RAIO,
        altura_pct=int(st.session_state.get("altura_mapa_pct", 86)),
        mostrar_deslocamento=bool(mostrar_deslocamento),
        status_texto=status_texto,
        estacoes_novas=estacoes_novas,
        # Token do ÚLTIMO alerta novo. Fica nos dados enviados ao mapa até surgir outro alerta: o mapa toca o
        # som quando vê um token que ainda não tocou. (Antes o token só ia na execução em que o alerta nascia,
        # e a reexecução imediata que abre o pop-up podia substituir esses dados antes do mapa tocar o som.)
        tocar_som=bool(st.session_state.get("som_token")),
        som_token=st.session_state.get("som_token"),
        som_data_uri=som_data_uri,
        key="bo_mapa_raios_live",
    )

    # Ações feitas no painel de dentro do mapa (excluir alerta, "quem recebeu"). Cada ação traz um
    # "nonce"; o componente continua devolvendo a última ação nas reexecuções, então só processa se for nova.
    if isinstance(evento, dict) and evento.get("nonce") and evento["nonce"] != st.session_state.get("_nonce_evento_mapa"):
        st.session_state["_nonce_evento_mapa"] = evento["nonce"]
        tipo = evento.get("tipo")
        if tipo == "quem_recebeu":
            for a in st.session_state.alertas_raio_ativos:
                if a.get("id") == evento.get("id"):
                    valor = str(evento.get("valor", ""))[:200]
                    a["quem_recebeu"] = valor
                    st.session_state[f"quem_recebeu_{a['id']}"] = valor  # mantém o campo do painel lateral igual
        elif tipo == "excluir":
            st.session_state.alertas_raio_ativos = [x for x in st.session_state.alertas_raio_ativos if x.get("id") != evento.get("id")]
        elif tipo == "limpar":
            st.session_state.alertas_raio_ativos = []
        _salvar_estado()
        st.rerun()

with col_mapa:
    st.fragment(run_every=intervalo_raios_seg)(_renderizar_mapa_ao_vivo)()

# Pop-up do alerta: mostrado uma única vez por alerta novo.
if st.session_state.get("dialog_raio_pendente"):
    st.session_state["dialog_raio_pendente"] = False
    _titulo_dialog = "🟢 Alerta verde — sem raios próximos" if st.session_state.get("dialog_raio_so_verde") else "⚡ Raio próximo de unidade(s)!"
    st.dialog(_titulo_dialog)(_corpo_dialog_alerta_raio)()
st.session_state["_run_completo"] = False

with col_lado:
  if mostrar_painel_alertas:
    with st.container(key="painel_lateral"):
        def _corpo_painel_lateral():
            df_status = st.session_state.get("_fragment_df_status", pd.DataFrame())
            tab_risco, tab_alertas = st.tabs(["🚨 Risco", "📋 Alertas"])

            with tab_risco:
                if df_status.empty:
                    st.info("Carregando status das unidades…")
                else:
                    em_risco = df_status[df_status["risco_score"] > 0].sort_values(["risco_score", "dist_min_km"], ascending=[False, True])
                    if em_risco.empty:
                        st.success("Nenhuma unidade em alerta amarelo/vermelho no momento.")
                    else:
                        for _, e in em_risco.iterrows():
                            with st.container(border=True):
                                chave_ui = f"unidade_{e['estacao']}"
                                if st.button(
                                    f"{e['risco_emoji']} {e['nome']}",
                                    key=chave_ui,
                                    use_container_width=True,
                                    help="Clique para visualizar os contatos da unidade",
                                ):
                                    st.session_state["unidade_contatos_selecionada"] = e["estacao"]
                                    st.rerun(scope="fragment")

                                st.markdown(
                                    f"<span style='color:{e['risco_color']}'>{e['risco_label']}</span>",
                                    unsafe_allow_html=True,
                                )

                                if st.session_state.get("unidade_contatos_selecionada") == e["estacao"]:
                                    contatos = e["contatos"]
                                    if contatos and contatos.get("numeros"):
                                        st.markdown(
                                            f"<div style='margin-top:8px;padding:10px;border-radius:8px;"
                                            f"background:#111827;border:1px solid #263244;'>"
                                            f"<b style='color:#3fc2c2;'>📞 Contatos — {contatos.get('nome', e['nome'])}</b></div>",
                                            unsafe_allow_html=True,
                                        )
                                        for item in contatos["numeros"]:
                                            desc = f" — {item['descricao']}" if item.get("descricao") else ""
                                            st.caption(f"☎️ {item['numero']}{desc}")
                                    else:
                                        st.info("Nenhum contato cadastrado para esta unidade.")

            with tab_alertas:
                if not st.session_state.alertas_raio_ativos:
                    st.success("Nenhum alerta de raio próximo ativo.")
                else:
                    if st.button("🗑️ Limpar todos os alertas", key="limpar_todos_alertas", use_container_width=True):
                        st.session_state.alertas_raio_ativos = []
                        _salvar_estado()
                        st.rerun(scope="fragment")
                    for a in st.session_state.alertas_raio_ativos:
                        with st.container(border=True):
                            col_txt, col_del = st.columns([6, 1])
                            with col_txt:
                                quem = st.text_input(
                                    "Quem recebeu o alerta:", value=a.get("quem_recebeu", ""),
                                    key=f"quem_recebeu_{a['id']}", placeholder="nome de quem confirmou o recebimento",
                                )
                                a["quem_recebeu"] = quem
                                st.code(montar_texto_copia(a), language=None)
                            with col_del:
                                if st.button("✕", key=f"excluir_alerta_{a.get('id', a['texto'])}", help="Excluir este alerta"):
                                    st.session_state.alertas_raio_ativos = [x for x in st.session_state.alertas_raio_ativos if x.get("id") != a.get("id")]
                                    _salvar_estado()
                                    st.rerun(scope="fragment")

        st.fragment(run_every=intervalo_raios_seg)(_corpo_painel_lateral)()


# ======================================================================
# BOLETINS DE PREVISÃO (formato WhatsApp)
# Usa o script boletins_bo.py exatamente como foi enviado (funções
# baixar / consenso / boletim_unidade etc. sem alterações). A geração roda
# numa thread em segundo plano: não trava o mapa nem é interrompida pelas
# atualizações automáticas dos raios.
# ======================================================================
def _worker_boletins(estado, unidades, dias):
    total = len(unidades)
    for i, (nome, (lat, lon)) in enumerate(unidades.items(), 1):
        estado["atual"] = nome
        try:
            estado["resultados"][nome] = boletins_bo.boletim_unidade(nome, lat, lon, dias)
        except Exception as e:
            estado["erros"].append((nome, str(e)))
        estado["feitos"] = i
        time.sleep(0.3)
    estado["rodando"] = False


unidades_boletim = dict(boletins_bo.UNIDADES)

_estado_boletins = st.session_state.get("boletins_estado")
_boletins_rodando = bool(_estado_boletins and _estado_boletins["rodando"])


def _secao_boletins(unidades_base):
    st.subheader("📨 Boletins de previsão")
    st.caption("ENSEMBLE (média consenso) entre ECMWF, ICON e GFS do Open-Meteo.")

    estado = st.session_state.get("boletins_estado")
    rodando = bool(estado and estado["rodando"])

    c1, c2 = st.columns([3, 1])
    with c1:
        filtro = st.text_input("Filtro (só unidades cujo nome contém…)", key="bol_filtro", placeholder="ex.: Macaé", disabled=rodando)
    with c2:
        dias = st.number_input("Dias de previsão", min_value=1, max_value=7, value=boletins_bo.DIAS_PREVISAO, key="bol_dias", disabled=rodando)

    unidades = {n: c for n, c in unidades_base.items() if not filtro or filtro.lower() in n.lower()}
    st.caption(f"{len(unidades)} unidade(s) selecionada(s).")

    if st.button(f"📨 Gerar boletins ({len(unidades)})", key="bol_gerar", type="primary", disabled=(not unidades) or rodando):
        novo = {"rodando": True, "resultados": {}, "erros": [], "feitos": 0, "total": len(unidades), "atual": "",
                "data": utc_para_brasilia(datetime.now(timezone.utc)).strftime("%Y%m%d"),
                "hoje_dd_mm": utc_para_brasilia(datetime.now(timezone.utc)).strftime("%d/%m")}
        st.session_state["boletins_estado"] = novo
        threading.Thread(target=_worker_boletins, args=(novo, unidades, int(dias)), daemon=True).start()
        st.rerun()

    if not estado: return

    if rodando:
        st.progress(min(estado["feitos"] / max(estado["total"], 1), 1.0),
                    text=f"[{estado['feitos']}/{estado['total']}] {estado['atual']}")
        return

    resultados, erros = estado["resultados"], estado["erros"]
    for nome, msg in erros: st.error(f"ERRO em {nome}: {msg}")
    if not resultados: return

    # Checagem: todos os boletins precisam começar em hoje (Brasília). Se alguma unidade sair com
    # outro dia, o boletins_bo.py em uso é a versão antiga (ou o app não foi reiniciado).
    esperado = estado.get("hoje_dd_mm")
    if esperado:
        fora = []
        for nome, txt in resultados.items():
            m_dia = re.search(r"\*Dia (\d\d/\d\d)\*", txt)
            if m_dia and m_dia.group(1) != esperado:
                fora.append(f"{nome} (começa em {m_dia.group(1)})")
        if fora:
            st.warning(f"⚠️ Boletins que não começam em hoje ({esperado}, horário de Brasília): " + "; ".join(fora) +
                       ". Isso indica que o `boletins_bo.py` em uso é a versão antiga: atualize o arquivo no GitHub "
                       "e reinicie o app (Manage app → Reboot app).")
        else:
            st.caption(f"✅ Todos os boletins começam em {esperado} (hoje, horário de Brasília).")

    consolidado = "\n\n".join(resultados.values())
    nome_consolidado = f"boletins_{estado['data']}.txt"
    buf_zip = io.BytesIO()
    with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, txt in resultados.items(): zf.writestr(f"{boletins_bo.slug(nome)}.txt", txt)
        zf.writestr(nome_consolidado, consolidado)

    d1, d2 = st.columns(2)
    with d1:
        st.download_button("⬇️ Arquivo consolidado (.txt)", data=consolidado.encode("utf-8"), file_name=nome_consolidado, mime="text/plain", key="bol_dl_txt", use_container_width=True)
    with d2:
        st.download_button("⬇️ Um .txt por unidade (.zip)", data=buf_zip.getvalue(), file_name=f"boletins_{estado['data']}.zip", mime="application/zip", key="bol_dl_zip", use_container_width=True)

    escolha = st.selectbox("Ver boletim da unidade", list(resultados), key="bol_ver")
    st.code(resultados[escolha], language=None)


# Fragmento próprio: interagir com os boletins não reconstrói o mapa. Enquanto
# a geração roda, ele se atualiza sozinho a cada 2 s pra mostrar o progresso e,
# quando termina, faz um rerun completo pra parar o auto-refresh.
def _boletins_fragmento(unidades_base):
    _secao_boletins(unidades_base)
    est = st.session_state.get("boletins_estado")
    if _boletins_rodando and est is not None and not est["rodando"]:
        st.rerun()

st.divider()
st.fragment(run_every=2 if _boletins_rodando else None)(_boletins_fragmento)(unidades_boletim)
_salvar_estado()
