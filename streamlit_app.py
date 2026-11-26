# ======================================================================
# BLUEOCEAN — MONITOR DE RAIOS (versão web / Streamlit)
# Versão focada só em raios (GLM/GOES-19), por Mário Henrique.
# ======================================================================
import base64
import copy
import hashlib
import hmac
import io
import json
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

try:   # chave paga do Open-Meteo (opcional): Settings > Secrets:  OPEN_METEO_API_KEY = "..."
    if "OPEN_METEO_API_KEY" in st.secrets:
        os.environ["OPEN_METEO_API_KEY"] = str(st.secrets["OPEN_METEO_API_KEY"])
except Exception:
    pass
import boletins_bo  # script de boletins (WhatsApp), incorporado sem alterações
import relatorios_mensais as rm  # relatórios mensais em PDF (upload → identificação → PDFs)
import boletim_horario as bh  # boletim horário (próximas 12 h, de 3 em 3 h)

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
_bo_fetch_boletins = components.declare_component(
    "bo_fetch_boletins", path=os.path.join(_APP_DIR_COMPONENTE, "bo_fetch_component")
)
_botoes_envio = components.declare_component(
    "bo_botoes_envio", path=os.path.join(_APP_DIR_COMPONENTE, "bo_botoes_component")
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
CONTATOS_UNIDADES = {'REGAP': {'nome': 'REGAP', 'numeros': [{'numero': '(31) 3529 4470'}, {'numero': '(31) 3529 4405'}, {'numero': '(31) 3529 4508'}]}, 'CILEP_CENPES': {'nome': 'CILEP CENPES', 'numeros': [{'numero': '(21) 9 9700 6335'}, {'numero': '(21) 9 7968 0027'}]}, 'TMIB COQUEIROS': {'nome': 'TMIB COQUEIROS', 'numeros': [{'numero': '(79) 3212 5101'}, {'numero': '(79) 9 9630 8427'}]}, 'ARM RIO': {'nome': 'ARM RIO', 'numeros': [{'numero': '(21) 9 6576-0066'}, {'numero': '(21) 9 6576-0142'}, {'numero': '(21) 9 9649 4019'}]}, 'UTE_Canoas': {'nome': 'UTE Canoas', 'numeros': [{'numero': '(51) 3415-3939'}, {'numero': '(51) 99866-6449'}]}, 'Guamaré': {'nome': 'Guamaré', 'numeros': [{'numero': '(85) 98830.3729'}, {'numero': '(84) 99984.7020'}, {'numero': '85) 99207.7804'}]}, 'REFAP': {'nome': 'REFAP', 'numeros': [{'numero': '(51) 3415-2080'}, {'numero': '(51) 99982-0520'}, {'numero': '(51) 99617-3964'}]}, 'REPAR': {'nome': 'REPAR', 'numeros': [{'numero': '(41) 3641-2987'}, {'numero': '(41) 99157-6902'}, {'numero': '(41) 99241-5443'}]}, 'UTC_Nova_Piratininga': {'nome': 'UTE Nova Piratininga', 'numeros': [{'numero': '(11) 3523-5856'}, {'numero': '(11) 3523 5876'}, {'numero': '(11) 98393-0913'}]}, 'RPBC': {'nome': 'RPBC', 'numeros': [{'numero': '(13) 3328-4074'}, {'numero': '(13) 99712-4788'}, {'numero': '(13) 3328-4253'}]}, 'RECAP': {'nome': 'RECAP', 'numeros': [{'numero': '(11) 3795-9314'}, {'numero': '(11) 96183-2809'}, {'numero': '(11) 3795-9130'}]}, 'UTG_Caraguatatuba': {'nome': 'UTGCA - Caraguatatuba', 'numeros': [{'numero': '(12) 3886-5050', 'descricao': 'Opção 1'}, {'numero': '(12) 3886-5117', 'descricao': 'Opção 2'}, {'numero': '(12) 3886-5066', 'descricao': 'Opção 3'}]}, 'REVAP': {'nome': 'REVAP', 'numeros': [{'numero': '(12) 3928-6304'}, {'numero': '(12) 3928-6499'}, {'numero': '(12) 9 9130-6608'}]}, 'REPLAN': {'nome': 'REPLAN', 'numeros': [{'numero': '(19) 2116-6892 e (19) 99772-1201', 'descricao': 'celular melhor'}, {'numero': '(19) 2116-6542 e (19) 99602-8522'}, {'numero': '(19) 2116--6183'}]}, 'UTE_Tres_lagoas': {'nome': 'UTE Três Lagoas', 'numeros': [{'numero': '(67) 3509-3275', 'descricao': 'Opção 1 - Sala de Controle'}, {'numero': '(67) 3509 - 3234', 'descricao': 'Opção 2 - Supervisor de Turno'}, {'numero': '(67) 9 - 9847 - 3567', 'descricao': 'Opção 3 - Celular da Operação'}]}, 'UTE_Seropedica': {'nome': 'UTE Seropédica', 'numeros': [{'numero': '(21) 2665-9221', 'descricao': 'supervisao op'}, {'numero': '(21) 2665-9234'}, {'numero': '(21) 98330 0979.'}]}, 'UTE_Termorio': {'nome': 'UTE Termorio', 'numeros': [{'numero': '(21) 3227-5746'}, {'numero': '(21) 98055-0569'}, {'numero': '(21) 9 6720 8088'}]}, 'REDUC': {'nome': 'REDUC', 'numeros': [{'numero': '(21) 2677-2232', 'descricao': 'Opção 1'}, {'numero': '(21) 2677-2975', 'descricao': 'Opção 2'}, {'numero': '(21) 9 - 9872 - 4188', 'descricao': 'Fernanda Neves (Gerente do Setor)'}]}, 'UTG_Itaborai': {'nome': 'UTG Itaboraí', 'numeros': [{'numero': '(21) 2133-4199', 'descricao': 'ligar neste'}, {'numero': '(21) 2133-4202'}, {'numero': '(21) 99700-6571'}]}, 'Arm Macaé': {'nome': 'Arm Macaé', 'numeros': [{'numero': '(22) 9 9824-6085'}, {'numero': '(22) 9 9940-2957'}]}, 'UTE Juiz de Fora': {'nome': 'UTE Juiz de Fora', 'numeros': [{'numero': '(32) 3239-8431', 'descricao': 'sala op'}, {'numero': '(32) 3239-8423', 'descricao': 'sala op'}, {'numero': '(32) 99804-4943'}]}, 'UTE_Termomacae': {'nome': 'UTE Termomacaé', 'numeros': [{'numero': '(22) 3379-6134'}, {'numero': '(22) 3379-6135'}, {'numero': '(22) 98817-2571'}]}, 'UTG_Cabiunas': {'nome': 'UTG Cabiunas', 'numeros': [{'numero': '(22) 9 - 9981-1678 / Ramal: 2759 - 5280', 'descricao': 'Opção 1'}, {'numero': '(22) 9 - 9778-7616 / Ramal: 2797 - 5248 / 2797 - 5249', 'descricao': 'Opção 2'}]}, 'UTE_Ibirite': {'nome': 'UTE Ibirité', 'numeros': [{'numero': '(31) 3472-2230'}, {'numero': '(31) 99704-5869'}, {'numero': '(11) 96857-9818'}]}, 'UTG Sul_Capixaba': {'nome': 'UTG Sul Capixaba', 'numeros': [{'numero': '(28) 3360-6065', 'descricao': 'CISP'}, {'numero': '(27) 99297-9464', 'descricao': 'CISP'}]}, 'UTG_Cacimbas': {'nome': 'UTG C - Cacimbas', 'numeros': [{'numero': '(27) 3048-9107 / 9903', 'descricao': 'Supervisão da Operação (K-45)'}, {'numero': '(27) 3048-9300 / 9909'}, {'numero': '(27)3048-9152', 'descricao': 'Coordenador de Turno da Operação (K-45)'}, {'numero': '(27) 3048-9131', 'descricao': 'SMS (k-32)'}, {'numero': '(27)3048-9140', 'descricao': 'Controle de CFTV - 24h (k-04)'}]}, 'RNEST': {'nome': 'RNEST', 'numeros': [{'numero': '(81) 3879 - 4530'}, {'numero': '(81) 3879 - 3220'}, {'numero': '(81) 3879 - 4525'}]}, 'UTE_Termobahia': {'nome': 'UTE Termobahia', 'numeros': [{'numero': '(71) 3348-5006', 'descricao': 'Opção 1'}, {'numero': '(71) 9 - 9988-5704', 'descricao': 'Opção 2'}, {'numero': '(71) 9 - 9918 - 3933 / 9 -9672 - 4400', 'descricao': 'Opção 3'}]}, 'Porto Belém': {'nome': 'PORTO BELÉM', 'numeros': [{'numero': '(91) 99150.0369'}, {'numero': '(79) 99163.0089'}, {'numero': '(85) 99207.7804'}]}, 'Mucuripe_Paracuru': {'nome': 'Mucuripe Paracuru', 'numeros': [{'numero': '(85) 98147.6460'}, {'numero': '(85) 98829.9818'}, {'numero': '(85) 98126.3018'}, {'numero': '85) 99207.7804'}]}, 'UTE_Vale_ACU': {'nome': 'UTE Vale do Açu', 'numeros': [{'numero': '(84) 3235-6033', 'descricao': 'Opção 1'}, {'numero': '(84) 3235-6034', 'descricao': 'Opção 2'}, {'numero': '(84)  9 9609 - 9675', 'descricao': 'Opção 3'}]}, 'UTE_Termoceara': {'nome': 'UTE Termoceara', 'numeros': [{'numero': '(85) 3411 - 4420 / 4440', 'descricao': 'Sala de Controle da Unidade'}, {'numero': '(85) 9 9957-4422', 'descricao': 'Cristiano Freire - Gerente de Operação'}, {'numero': '(85) 998490019', 'descricao': 'Thiago Gerente de SMS'}]}, 'Porto Aratu': {'nome': 'Porto Aratu', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Valença': {'nome': 'UTE Porto VALENÇA', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Imbetiba': {'nome': 'Porto de Imbetiba', 'numeros': [{'numero': '(22) 9 9736-9161'}]}, 'Porto Açu': {'nome': 'UTE Porto AÇU', 'numeros': [{'numero': '(22) 9 9613-0611'}, {'numero': '(22) 2101 5960'}]}, 'Porto B Guanabara': {'nome': 'UTE PORTO BAIA DE  GUANABARA', 'numeros': [{'numero': '(21) 9 9519 4346'}, {'numero': '(21) 2144 0051'}, {'numero': '(21) 9 8145 4321'}]}}

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
    "UTG_Caraguatatuba": ["UTGCA"], "TMIB COQUEIROS": ["TMIB"], "Mucuripe_Paracuru": ["Mucuripe", "Paracuru"], "Porto Imbetiba": ["Imbetiba"],
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
def _chave_alfabetica(nome_completo):
    """Chave de ordem alfabética pelo nome mostrado (antes do " - "), sem acento nem diferença de maiúsculas."""
    t = unicodedata.normalize("NFKD", str(nome_completo).split(" - ")[0]).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", t.lower()).strip()


ESTACOES_PADRAO = [
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
    {"estacao": "Porto Belém", "lat": -1.3414761262854806, "lon": -48.48130866694849},
    {"estacao": "Porto Valença", "lat": -13.36937, "lon": -39.07125},
    {"estacao": "Porto Guamaré", "lat": -5.10669, "lon": -36.31959},
    {"estacao": "Porto Mucuripe", "lat": -3.71312, "lon": -38.47404},
    {"estacao": "Porto Paracuru", "lat": -3.40115, "lon": -39.0109},
]
ESTACOES_PADRAO.sort(key=lambda e: _chave_alfabetica(e["estacao"]))   # unidades em ordem alfabética em todo o app

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

def calcular_status_estacoes(df_stations, raios_df, encerrados=None, km_encerrados=None):
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
                # (encerramento manual limpa até 50 km; o automático, só até VERDE_RAIO_KM)
                km_limpar = (km_encerrados or {}).get(nome_completo, VERDE_RAIO_KM)
                ignorar = (dists <= km_limpar) & (raio_t <= np.datetime64(corte.replace(tzinfo=None)))
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

@st.cache_resource
def _glm_store():
    """Memória compartilhada dos raios já baixados, por arquivo GLM (cada arquivo = 20 s).
    Um arquivo que baixou uma vez fica guardado até sair da janela: se a próxima atualização
    falhar (timeout, 503, listagem da AWS incompleta), os pontos que já estavam no mapa NÃO somem."""
    return {"arquivos": {}, "lock": threading.Lock(), "df": None, "ts": 0.0}

_COLUNAS_GLM = ["lat", "lon", "energy_j", "time"]
_TTL_GLM_SEG = 90

def fetch_glm_flashes_recent(minutos=15):
    import netCDF4
    store = _glm_store()
    with store["lock"]:
        if store["df"] is not None and (time.time() - store["ts"]) < _TTL_GLM_SEG:
            return store["df"].copy()

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
        if falhas == len(horas) and not store["arquivos"]:
            raise RuntimeError("não foi possível conectar ao bucket GLM na AWS")

        # só baixa o que ainda não está guardado; o que falhar fica de fora e é tentado de novo no próximo ciclo
        novos = sorted(c for c in chaves
                       if c not in store["arquivos"] and (ts := _parse_glm_timestamp(c)) is not None and ts >= inicio)
        b = SOUTH_AMERICA_BOUNDS
        for chave in novos:
            try:
                r = session.get(f"{GLM_BASE_URL}/{chave}", timeout=30)
                r.raise_for_status()
                with netCDF4.Dataset("inmemory.nc", memory=r.content) as ds:
                    lats = np.asarray(ds.variables["flash_lat"][:], dtype=float)
                    lons = np.asarray(ds.variables["flash_lon"][:], dtype=float)
                    energias = np.asarray(ds.variables["flash_energy"][:], dtype=float)
                ts_arquivo = _parse_glm_timestamp(chave)
                dfa = pd.DataFrame({"lat": lats, "lon": lons, "energy_j": energias, "time": ts_arquivo})
                dfa = dfa[(dfa["lat"] >= b["lat_min"]) & (dfa["lat"] <= b["lat_max"]) &
                          (dfa["lon"] >= b["lon_min"]) & (dfa["lon"] <= b["lon_max"])]
                store["arquivos"][chave] = (ts_arquivo, dfa)   # arquivo vazio também é guardado (não baixa de novo)
            except Exception:
                continue

        # descarta só o que já saiu da janela
        for chave in [k for k, (ts, _) in store["arquivos"].items() if ts < inicio]:
            store["arquivos"].pop(chave, None)

        partes = [d for _, d in store["arquivos"].values() if not d.empty]
        df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=_COLUNAS_GLM)
        store["df"], store["ts"] = df, time.time()
        return df.copy()

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

_HTML_PREPARAR = """<!doctype html><html><head><meta charset="utf-8"><style>
  html, body { margin:0; padding:0; background:transparent; }
  button { cursor:pointer; border-radius:8px; border:1px solid #25d366; background:#25d366; color:#06210f; padding:7px 14px; font:600 14px 'Segoe UI', Arial, sans-serif; }
  button:hover { background:#3be07b; }
</style></head><body><button id="b">🤖 Preparar no WhatsApp</button><script>
  var ESTACAO = __ESTACAO__, TEXTO = __TEXTO__, ID = __ID__, MIN = __MIN__;
  function partes(ms) {
    var f = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
                                               hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ms));
    var o = {}; f.forEach(function (p) { o[p.type] = p.value; });
    return { data: o.day + "/" + o.month + "/" + o.year, hora: o.hour + ":" + o.minute };
  }
  function atual(t) {
    var a = partes(Date.now()), fim = partes(Date.now() + MIN * 60000);
    return t.replace(/\\d{2}\\/\\d{2}\\/\\d{4} - \\d{2}:\\d{2}/, a.data + " - " + a.hora).replace(/Válido até as \\d{2}:\\d{2}/, "Válido até as " + fim.hora);
  }
  var btn = document.getElementById("b");
  btn.addEventListener("click", function () {
    var texto = atual(TEXTO), confirmou = false;
    function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
    window.addEventListener("message", ack);
    try { (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "preparar", id: ID, estacao: ESTACAO, texto: texto }, "*"); } catch (e) {}
    setTimeout(function () {
      window.removeEventListener("message", ack);
      if (confirmou) { btn.textContent = "✔ Enviado ao WhatsApp - confira la e de Enter"; }
      else {
        var t = document.createElement("textarea"); t.value = texto; t.style.position = "fixed"; t.style.opacity = "0";
        document.body.appendChild(t); t.select(); try { document.execCommand("copy"); } catch (e) {} document.body.removeChild(t);
        btn.textContent = "Script nao detectado - texto copiado (Ctrl+V)";
      }
      setTimeout(function () { btn.textContent = "🤖 Preparar no WhatsApp"; }, 4000);
    }, 1200);
  });
</script></body></html>"""

def botao_preparar_whatsapp(estacao, texto, alerta_id, minutos=60):
    """Botão 'Preparar no WhatsApp' (script do Tampermonkey): abre o grupo na aba já aberta e deixa o texto digitado."""
    def js(v): return json.dumps(str(v), ensure_ascii=False).replace("</", "<\\/")
    html = (_HTML_PREPARAR.replace("__ESTACAO__", js(estacao)).replace("__TEXTO__", js(texto)).replace("__ID__", js(alerta_id)).replace("__MIN__", str(int(minutos))))
    components.html(html, height=44)

_HTML_REGISTRAR = """<!doctype html><html><head><meta charset="utf-8"><style>
  html, body { margin:0; padding:0; background:transparent; }
  button { cursor:pointer; border-radius:8px; border:1px solid #1d70b8; background:#1d70b8; color:#fff; padding:7px 14px; font:600 14px 'Segoe UI', Arial, sans-serif; }
  button:hover { background:#2a86d6; }
</style></head><body><button id="b">📝 Registrar no site</button><script>
  var ESTACAO = __ESTACAO__, NIVEL = __NIVEL__, MIN = __MIN__;
  var btn = document.getElementById("b");
  btn.addEventListener("click", function () {
    var confirmou = false;
    function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
    window.addEventListener("message", ack);
    try { (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "registrar", estacao: ESTACAO, nivel: NIVEL, minutos: MIN }, "*"); } catch (e) {}
    setTimeout(function () {
      window.removeEventListener("message", ack);
      btn.textContent = confirmou ? "✔ Enviado - confira o formulario na aba do site e salve" : "Script nao detectado (atualize o Tampermonkey)";
      setTimeout(function () { btn.textContent = "📝 Registrar no site"; }, 4000);
    }, 1200);
  });
</script></body></html>"""

def botao_registrar_site(estacao, nivel, minutos=60):
    """Botão 'Registrar no site': o Tampermonkey preenche o formulário 'Novo evento' da BlueOcean (aba /alerts já aberta). Você confere e salva."""
    def js(v): return json.dumps(str(v), ensure_ascii=False).replace("</", "<\\/")
    html = _HTML_REGISTRAR.replace("__ESTACAO__", js(estacao)).replace("__NIVEL__", js(nivel)).replace("__MIN__", str(int(minutos)))
    components.html(html, height=44)

# ======================================================================
# FINALIZAR ALERTA (manual) — emite o alerta verde da unidade na hora, igual ao automático.
# ======================================================================
def _alertas_finalizaveis():
    """IDs dos alertas que mostram o botão \"Finalizar\": o alerta MAIS RECENTE de cada unidade, se for
    vermelho/amarelo. Se o mais recente já é verde (unidade finalizada), ninguém daquela unidade mostra o botão."""
    vistos, ids = set(), set()
    for a in st.session_state.alertas_raio_ativos:  # mais novos primeiro (insert(0))
        est = a.get("estacao")
        if est in vistos:
            continue
        vistos.add(est)
        if a.get("nivel") in ("vermelho", "amarelo"):
            ids.add(a.get("id"))
    return ids

def _finalizar_alerta_unidade(chave_estacao):
    """Emite o alerta verde (FIM DO ALERTA DE RAIOS) da unidade e libera o status dela, como no encerramento automático."""
    agora_ts = time.time()
    nome = str(chave_estacao).split(" - ")[0]
    texto_v = montar_mensagem_alerta_verde(nome, st.session_state.get("meteorologista_nome", ""))
    st.session_state.alertas_raio_ativos.insert(0, {
        "id": f"{chave_estacao}_verde_{agora_ts}", "texto": texto_v, "estacao": chave_estacao,
        "nivel": "verde", "dist_km": None, "expira": agora_ts + 3600, "quem_recebeu": "",
    })
    sv = st.session_state.verde_estado.setdefault(chave_estacao, {"vermelho_ativo": False, "ultimo_raio": None})
    sv["vermelho_ativo"], sv["ultimo_raio"] = False, None   # evita um segundo verde automático depois
    reg = st.session_state.alertas_unidade.setdefault(chave_estacao, {
        "nivel": "vermelho", "dist_km": None, "notificado_ts": agora_ts, "expira_ts": agora_ts + 3600})
    reg["encerrado_ts"] = agora_ts
    reg["encerrado_km"] = 50   # finalizado à mão: raios até 50 km anteriores a agora deixam de contar
    _quadro_remover(estacao=chave_estacao)   # some do quadro compartilhado
    _quadro_marcar_verde(chave_estacao)
    _salvar_estado()

def _emitir_verde_manual(chave_estacao):
    """Botão 'Emitir alerta verde' do painel da unidade: gera o card verde (fim do alerta) para QUALQUER unidade, mesmo sem alerta ativo."""
    chave = str(chave_estacao or "").strip()
    if not chave:
        return
    st.session_state.alertas_raio_ativos = [x for x in st.session_state.alertas_raio_ativos
                                            if not (x.get("estacao") == chave and x.get("nivel") == "verde")]   # sem cards verdes repetidos
    if chave in st.session_state.alertas_unidade:
        _finalizar_alerta_unidade(chave)      # havia alerta nesta unidade: encerra como sempre
        return
    agora_ts = time.time()
    nome = chave.split(" - ")[0]
    st.session_state.alertas_raio_ativos.insert(0, {
        "id": f"{chave}_verde_{agora_ts}", "texto": montar_mensagem_alerta_verde(nome, st.session_state.get("meteorologista_nome", "")),
        "estacao": chave, "nivel": "verde", "dist_km": None, "expira": agora_ts + 3600, "quem_recebeu": "",
    })
    _quadro_remover(estacao=chave, motivo="alerta verde emitido")
    _quadro_marcar_verde(chave)
    _salvar_estado()

def _emitir_nivel_manual(chave_estacao, nivel):
    """Botões 'Emitir alerta amarelo/vermelho/verde' do painel da unidade: gera o card do nível escolhido, mesmo sem raio por perto."""
    chave = str(chave_estacao or "").strip()
    if not chave:
        return
    if nivel == "verde":
        _emitir_verde_manual(chave)
        return
    if nivel not in ("amarelo", "vermelho"):
        return
    agora_ts = time.time()
    nome = chave.split(" - ")[0]
    km = 30 if nivel == "vermelho" else 50
    st.session_state.alertas_raio_ativos = [x for x in st.session_state.alertas_raio_ativos
                                            if not (x.get("estacao") == chave and x.get("nivel") == nivel)]   # sem cards repetidos do mesmo nível
    st.session_state.alertas_raio_ativos.insert(0, {
        "id": f"{chave}_{nivel}_manual_{agora_ts}", "texto": montar_mensagem_proximidade_raio(km, nome, st.session_state.get("meteorologista_nome", "")),
        "estacao": chave, "nivel": nivel, "dist_km": None, "expira": agora_ts + 3600, "quem_recebeu": "", "acionado": True,
    })
    st.session_state.alertas_unidade[chave] = {"nivel": nivel, "dist_km": None, "notificado_ts": agora_ts, "expira_ts": agora_ts + 3600}
    _salvar_estado()

def _antecipar_para_vermelho(alerta):
    """Gera um alerta VERMELHO para a unidade de um alerta amarelo (antecipação manual, sem esperar o raio chegar a 30 km)."""
    chave = alerta["estacao"]
    agora_ts = time.time()
    nome = str(chave).split(" - ")[0]
    texto = montar_mensagem_proximidade_raio(30, nome, st.session_state.get("meteorologista_nome", ""))
    st.session_state.alertas_raio_ativos.insert(0, {
        "id": f"{chave}_antecipado_{agora_ts}", "texto": texto, "estacao": chave, "nivel": "vermelho",
        "dist_km": alerta.get("dist_km"), "expira": agora_ts + 3600, "quem_recebeu": "", "antecipado": True, "acionado": True,
    })
    st.session_state.alertas_unidade[chave] = {
        "nivel": "vermelho", "dist_km": alerta.get("dist_km"), "notificado_ts": agora_ts, "expira_ts": agora_ts + 3600,
    }
    _salvar_estado()

def _rebaixar_para_amarelo(alerta):
    """Gera um alerta AMARELO para a unidade de um alerta vermelho (o risco diminuiu, mas o alerta segue ativo até você encerrar)."""
    chave = alerta["estacao"]
    agora_ts = time.time()
    nome = str(chave).split(" - ")[0]
    texto = montar_mensagem_proximidade_raio(50, nome, st.session_state.get("meteorologista_nome", ""))
    st.session_state.alertas_raio_ativos.insert(0, {
        "id": f"{chave}_rebaixado_{agora_ts}", "texto": texto, "estacao": chave, "nivel": "amarelo",
        "dist_km": alerta.get("dist_km"), "expira": agora_ts + 3600, "quem_recebeu": "", "acionado": True,
    })
    st.session_state.alertas_unidade[chave] = {
        "nivel": "amarelo", "dist_km": alerta.get("dist_km"), "notificado_ts": agora_ts, "expira_ts": agora_ts + 3600,
    }
    _salvar_estado()

DURACOES_ALERTA_MIN = (60, 90, 120)   # 1 h, 1 h 30 e 2 h
AUTO_REMOVER_APOS_FIM_MIN = 10        # alerta que passou do fim da validade e não foi renovado nem encerrado some 10 min depois

def _min_ate_hm(hm):
    """Minutos de agora (Brasília) até o próximo HH:MM informado (1 a 1440). None se o horário for inválido."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(hm or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    agora = datetime.now(timezone.utc) - timedelta(hours=3)
    delta = (int(m.group(1)) * 60 + int(m.group(2))) - (agora.hour * 60 + agora.minute)
    if delta <= 0:
        delta += 1440
    return delta

def _definir_validade(alerta_id, minutos, fim_hm=None):
    """Alerta passa a durar `minutos` a partir de AGORA. Com `fim_hm` (HH:MM), o fim foi escolhido à mão.
    O alerta continua ativo até o meteorologista encerrar; isto só muda o horário informado na mensagem/site."""
    fim_hm = str(fim_hm or "").strip()
    if fim_hm:
        calc = _min_ate_hm(fim_hm)
        if calc is None:
            return
        minutos = calc
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        return
    if not (1 <= minutos <= 1440):
        return
    for a in st.session_state.alertas_raio_ativos:
        if a.get("id") != alerta_id or a.get("nivel") == "verde":
            continue
        agora_ts = time.time()
        a["acionado"] = True
        a["expira"] = agora_ts + minutos * 60
        if fim_hm:
            a["fim_hm"] = ("0" + fim_hm)[-5:]
        else:
            a.pop("fim_hm", None)
            if minutos in DURACOES_ALERTA_MIN:
                a["duracao_min"] = minutos
        reg = st.session_state.alertas_unidade.get(a.get("estacao"))
        if reg and not reg.get("encerrado_ts") and reg.get("nivel") == a.get("nivel"):
            reg["expira_ts"] = agora_ts + minutos * 60
        _salvar_estado()
        return

# ======================================================================
# QUADRO COMPARTILHADO (todos os meteorologistas que abrirem o app veem o mesmo)
# ======================================================================
# Fica na memória do servidor (st.cache_resource = um só para todas as sessões) e é gravado em arquivo a cada
# mudança, então sobrevive a um reinício simples do app. Contém:
#   - "emitidos": alertas amarelo/vermelho já enviados (WhatsApp / site / copiados), um por unidade; somem quando o
#     alerta é finalizado (verde), excluído, removido do quadro ou vence;
#   - "escala": escala dos meteorologistas (dia da semana + horário, ou data específica para trocas pontuais);
#   - "historico": registro de tudo que aconteceu (emitido, renovado, finalizado, vencido...), com exportação em CSV.
import tempfile
_ARQ_QUADRO = os.path.join(tempfile.gettempdir(), "rio_raios_quadro.json")
_ARQ_ESCALA_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "escala.json")
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
AVISO_FIM_ALERTA_SEG = 5 * 60
AVISO_ULTIMO_MIN_SEG = 60
RENOVAR_QUADRO_MIN = 30
HISTORICO_MAX = 500
PONTO_MAX = 1000
SAIDA_SEM_REENTRADA_SEG = 60 * 60   # após "Saindo do Turno", não reabre o turno sozinho por 1 h
TURNO_MAX_H = 16                    # turno aberto há mais que isso é fechado sozinho (esqueceram de sair)
PRESENCA_SEG = 75   # sem sinal de vida por mais que isso = saiu do site

@st.cache_resource
def _quadro():
    q = {"lock": threading.RLock(), "emitidos": {}, "escala": [], "historico": [], "ponto": [], "online": {}, "enviados": {}, "verdes": {}}
    try:
        with open(_ARQ_ESCALA_PADRAO, encoding="utf-8") as f:   # escala "de fábrica" (opcional, vinda do GitHub)
            q["escala"] = json.load(f)
    except Exception:
        pass
    try:
        with open(_ARQ_QUADRO, encoding="utf-8") as f:
            d = json.load(f)
        q["emitidos"] = d.get("emitidos", {})
        q["historico"] = d.get("historico", [])
        q["ponto"] = d.get("ponto", [])
        q["enviados"] = d.get("enviados", {})
        q["verdes"] = d.get("verdes", {})
        if d.get("escala") is not None:
            q["escala"] = d["escala"]
    except Exception:
        pass
    return q

def _quadro_gravar(q):
    try:
        with open(_ARQ_QUADRO, "w", encoding="utf-8") as f:
            json.dump({"emitidos": q["emitidos"], "escala": q["escala"], "historico": q["historico"], "ponto": q["ponto"],
                       "enviados": q.get("enviados", {}), "verdes": q.get("verdes", {})}, f, ensure_ascii=False)
    except Exception:
        pass   # gravar nunca pode derrubar o app

def _quadro_log(q, evento, estacao, nivel="", quem="", via=""):
    """Acrescenta uma linha ao histórico (chamar com o lock do quadro já tomado)."""
    q["historico"].append({"ts": time.time(), "evento": evento, "estacao": estacao, "nivel": nivel, "meteorologista": quem, "via": via})
    if len(q["historico"]) > HISTORICO_MAX:
        del q["historico"][:len(q["historico"]) - HISTORICO_MAX]

def _nome_atual():
    return str(st.session_state.get("meteorologista_nome", "")).strip()

JANELA_DUPLICADO_SEG = 30 * 60   # mesma mensagem (unidade + nível) enviada ao WhatsApp há menos que isso = possível duplicada
_NIVEL_ORDEM = {"verde": 0, "amarelo": 1, "vermelho": 2}

def _quadro_ativo(estacao):
    q = _quadro()
    with q["lock"]:
        v = q["emitidos"].get(estacao)
        return dict(v) if v else None

def _quadro_marcar_verde(estacao):
    """Registra no quadro (compartilhado) que a unidade foi finalizada: as outras sessões não recriam o alerta com raios antigos."""
    q = _quadro()
    with q["lock"]:
        q.setdefault("verdes", {})[estacao] = time.time()
        _quadro_gravar(q)

def _quadro_verde_ts(estacao):
    q = _quadro()
    with q["lock"]:
        return q.get("verdes", {}).get(estacao)

def _quadro_enviado_recente(estacao, nivel):
    """Quem já mandou (WhatsApp/cópia) esta mesma mensagem (unidade + nível) há pouco tempo, ou None."""
    q = _quadro()
    with q["lock"]:
        r = q.get("enviados", {}).get(f"{estacao}|{nivel}")
        if r and time.time() - r.get("ts", 0) < JANELA_DUPLICADO_SEG:
            return dict(r)
    return None

def _quadro_emitir(alerta, via, minutos):
    """Publica (ou atualiza) o alerta da unidade no quadro. Alerta verde = fim do alerta: tira a unidade do quadro."""
    q, agora, est = _quadro(), time.time(), alerta.get("estacao")
    with q["lock"]:
        if via in ("WhatsApp", "Copiado"):
            q.setdefault("enviados", {})[f"{est}|{alerta.get('nivel')}"] = {"ts": agora, "por": _nome_atual(), "via": via, "id": alerta.get("id")}
        if alerta.get("nivel") == "verde":
            if q["emitidos"].pop(est, None) is not None:
                _quadro_log(q, "finalizado", est, "verde", _nome_atual(), via)
        else:
            antigo = q["emitidos"].get(est) or {}
            mesmo = antigo.get("id") == alerta.get("id")
            vias = list(antigo.get("vias", [])) if mesmo else []
            if via and via not in vias:
                vias.append(via)
            q["emitidos"][est] = {
                "id": alerta.get("id"), "estacao": est, "nivel": alerta.get("nivel"), "meteorologista": _nome_atual(),
                "emitido_ts": antigo.get("emitido_ts", agora) if mesmo else agora,
                "expira_ts": agora + int(minutos or 60) * 60, "vias": vias,
            }
            _quadro_log(q, "renovado" if mesmo else "emitido", est, alerta.get("nivel"), _nome_atual(), via)
        _quadro_gravar(q)

def _quadro_remover(estacao=None, alerta_id=None, motivo="finalizado"):
    q = _quadro()
    with q["lock"]:
        alvos = [k for k, v in q["emitidos"].items() if k == estacao or (alerta_id is not None and v.get("id") == alerta_id)]
        for k in alvos:
            v = q["emitidos"].pop(k)
            _quadro_log(q, motivo, k, v.get("nivel", ""), _nome_atual())
        if alvos:
            _quadro_gravar(q)

def _quadro_renovar(estacao, minutos=RENOVAR_QUADRO_MIN):
    """Estende a validade de um alerta do quadro (qualquer meteorologista pode fazer)."""
    q = _quadro()
    with q["lock"]:
        v = q["emitidos"].get(estacao)
        if v:
            v["expira_ts"] = max(v["expira_ts"], time.time()) + minutos * 60
            _quadro_log(q, f"renovado +{minutos} min", estacao, v.get("nivel", ""), _nome_atual(), "Quadro")
            _quadro_gravar(q)

def _quadro_listar():
    """Alertas ativos do quadro. Ficam até o meteorologista encerrar (verde, "Tirar" ou excluir) ou renovar a validade;
    se o fim da validade passar e ninguém renovar nem encerrar, saem sozinhos AUTO_REMOVER_APOS_FIM_MIN minutos depois."""
    q = _quadro()
    with q["lock"]:
        agora = time.time()
        vencidos = [k for k, v in q["emitidos"].items() if agora > v.get("expira_ts", 0) + AUTO_REMOVER_APOS_FIM_MIN * 60]
        for k in vencidos:
            v = q["emitidos"].pop(k)
            _quadro_log(q, "vencido (removido sozinho)", k, v.get("nivel", ""), "", "Automático")
        if vencidos:
            _quadro_gravar(q)
        return sorted((dict(v) for v in q["emitidos"].values()), key=lambda v: v.get("expira_ts", 0))

def _emitir_alerta_evento(alerta_id, minutos, via, fim_hm=None):
    """Chamado quando alguém clica em copiar / preparar no WhatsApp / registrar no site."""
    alvo = next((x for x in st.session_state.alertas_raio_ativos if x.get("id") == alerta_id), None)
    if alvo is None:
        return
    alvo["acionado"] = True
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        minutos = alvo.get("duracao_min", 60)
    if alvo.get("nivel") != "verde":
        _definir_validade(alerta_id, minutos, fim_hm)
        minutos = max(1, int((alvo.get("expira", time.time() + 3600) - time.time()) / 60))
    else:
        minutos = 60
    _quadro_emitir(alvo, via, minutos)

def _agora_brasilia():
    return datetime.now(timezone.utc) - timedelta(hours=3)

def _hm_para_min(t):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(t or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))

def _data_valida(t):
    try:
        return datetime.strptime(str(t).strip(), "%d/%m/%Y").strftime("%d/%m/%Y")
    except Exception:
        return None

def _plantao_agora(escala):
    """Nomes de quem está de plantão agora (horário de Brasília). Linha com DATA vale só naquele dia (troca pontual);
    sem data vale pelo dia da semana (ou todos os dias). Turnos que viram a noite (ex.: 22:00–06:00) valem até o fim
    no dia seguinte."""
    agora = _agora_brasilia()
    dia, min_agora = DIAS_SEMANA[agora.weekday()], agora.hour * 60 + agora.minute
    ontem = DIAS_SEMANA[(agora.weekday() - 1) % 7]
    data_hoje, data_ontem = agora.strftime("%d/%m/%Y"), (agora - timedelta(days=1)).strftime("%d/%m/%Y")
    nomes = []
    for e in escala:
        ini, fim = _hm_para_min(e.get("inicio")), _hm_para_min(e.get("fim"))
        nome = str(e.get("nome", "")).strip()
        if ini is None or fim is None or not nome:
            continue
        if e.get("data"):
            hoje_ok, ontem_ok = e["data"] == data_hoje, e["data"] == data_ontem
        else:
            d = e.get("dia", "Todos os dias")
            hoje_ok, ontem_ok = d in ("Todos os dias", dia), d in ("Todos os dias", ontem)
        if ini < fim:
            ativo = hoje_ok and ini <= min_agora < fim
        elif ini > fim:   # vira a noite
            ativo = (hoje_ok and min_agora >= ini) or (ontem_ok and min_agora < fim)
        else:             # início == fim: dia inteiro
            ativo = hoje_ok
        if ativo and nome not in nomes:
            nomes.append(nome)
    return nomes

# ---- Ponto (entrada/saída) e presença online ----
def _ponto_abertos():
    q = _quadro()
    with q["lock"]:
        return [dict(r) for r in q["ponto"] if not r.get("saida_ts")]

def _ponto_entrar(nome, forcar=False, automatica=False):
    nome = str(nome or "").strip()
    if not nome:
        return False
    q = _quadro()
    with q["lock"]:
        if automatica and not forcar:
            # saiu do turno há pouco (ex.: apertou "Saindo do Turno" e atualizou a página): não reabre sozinho
            for r in q["ponto"]:
                if r["nome"].strip().lower() == nome.lower() and r.get("saida_ts") and time.time() - r["saida_ts"] < SAIDA_SEM_REENTRADA_SEG:
                    return False
        if any(not r.get("saida_ts") and r["nome"].strip().lower() == nome.lower() for r in q["ponto"]):
            return False   # já está com a entrada batida
        q["ponto"].append({"nome": nome, "entrada_ts": time.time(), "saida_ts": None, "saida_por": ""})
        if len(q["ponto"]) > PONTO_MAX:
            del q["ponto"][:len(q["ponto"]) - PONTO_MAX]
        _quadro_log(q, "entrada no turno", "", "", nome)
        _quadro_gravar(q)
    return True

def _ponto_sair(nome):
    nome = str(nome or "").strip().lower()
    q = _quadro()
    with q["lock"]:
        for r in q["ponto"]:
            if not r.get("saida_ts") and r["nome"].strip().lower() == nome:
                r["saida_ts"] = time.time()
                r["saida_por"] = _nome_atual()
                _quadro_log(q, "saída do turno", "", "", r["nome"])
                _quadro_gravar(q)
                return True
    return False

def _turno_entrada_automatica(nome):
    return _ponto_entrar(nome, automatica=True)

def _turno_fechar_esquecidos():
    q, agora = _quadro(), time.time()
    with q["lock"]:
        mudou = False
        for r in q["ponto"]:
            if not r.get("saida_ts") and agora - r["entrada_ts"] > TURNO_MAX_H * 3600:
                r["saida_ts"], r["saida_por"] = r["entrada_ts"] + TURNO_MAX_H * 3600, "automático (16 h)"
                _quadro_log(q, "saída do turno (automática após 16 h)", "", "", r["nome"])
                mudou = True
        if mudou:
            _quadro_gravar(q)

def _fmt_duracao(seg):
    seg = max(int(seg), 0)
    return f"{seg // 3600}h{(seg % 3600) // 60:02d}"

def _presenca_batimento():
    """Marca esta sessão como online e devolve os nomes de quem está no site (inclui esta sessão)."""
    q, agora = _quadro(), time.time()
    sid = st.session_state.setdefault("_presenca_id", uuid.uuid4().hex[:10])
    nome = _nome_atual() or "(sem nome)"
    with q["lock"]:
        antigo = q["online"].get(sid, {})
        q["online"][sid] = {"nome": nome, "ts": agora, "desde": antigo.get("desde", agora)}
        for k in [k for k, v in q["online"].items() if agora - v["ts"] > PRESENCA_SEG * 3]:
            q["online"].pop(k, None)
        vivos = [v for v in q["online"].values() if agora - v["ts"] <= PRESENCA_SEG]
    por_nome = {}
    for v in sorted(vivos, key=lambda v: v["desde"]):
        por_nome.setdefault(v["nome"], v)
    return list(por_nome.values())

def _quadro_ponto_expander():
    with st.expander("🕒 Registro de turnos (entradas e saídas)"):
        q = _quadro()
        with q["lock"]:
            regs = [dict(r) for r in q["ponto"]]
        linhas = []
        for r in reversed(regs):
            ent = datetime.fromtimestamp(r["entrada_ts"], tz=timezone.utc) - timedelta(hours=3)
            sai = r.get("saida_ts")
            linhas.append({"Meteorologista": r["nome"], "Data": ent.strftime("%d/%m/%Y"), "Entrada": ent.strftime("%H:%M"),
                           "Saída": _fmt_hm(sai) if sai else "— em plantão —",
                           "Duração": _fmt_duracao((sai or time.time()) - r["entrada_ts"]),
                           "Observação": r.get("saida_por", "") if str(r.get("saida_por", "")).startswith("auto") else ""})
        if not linhas:
            st.caption("Ainda sem registros de turnos.")
        else:
            df = pd.DataFrame(linhas)
            st.dataframe(df.head(100), hide_index=True, use_container_width=True)
            st.download_button("⬇️ Baixar turnos (CSV)", df.to_csv(index=False).encode("utf-8-sig"), file_name="turnos_meteorologistas.csv", mime="text/csv")
        st.caption("A entrada é registrada sozinha ao abrir o site com seu nome; a saída, no botão “Saindo do Turno”. Turnos esquecidos são fechados sozinhos após 16 h.")

_HTML_PONTE_QUADRO = """<!doctype html><html><body><script>
  var D = __DADOS__, t0 = Date.now();
  function enviar() {
    var itens = D.map(function (i) { return Object.assign({}, i, { resta: Math.max(0, i.resta - (Date.now() - t0) / 1000) }); });
    var msg = { fonte: "rio-quadro", itens: itens };
    try { var p = window.parent; for (var k = 0; k < p.frames.length; k++) { try { p.frames[k].postMessage(msg, "*"); } catch (e) {} } } catch (e) {}
  }
  enviar(); setInterval(enviar, 2000);
</script></body></html>"""

_HTML_BIP_5MIN = """<!doctype html><html><body><script>
  // token: __T__   modo: __M__
  (function () {
    try {
      var C = window.AudioContext || window.webkitAudioContext; if (!C) return;
      var ctx = new C(); if (ctx.state === "suspended") ctx.resume();
      var tempos = "__M__" === "urgente" ? [0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1] : [0, 0.45, 0.9, 1.6, 2.05, 2.5];
      tempos.forEach(function (t, i) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "sine"; o.frequency.value = ("__M__" === "urgente") ? 1320 : (i % 3 === 2 ? 1175 : 880); o.connect(g); g.connect(ctx.destination);
        var t0 = ctx.currentTime + t; g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.4, t0 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.25); o.start(t0); o.stop(t0 + 0.3);
      });
    } catch (e) {}
  })();
</script></body></html>"""

def _rerun_fragmento():
    try:
        st.rerun(scope="fragment")
    except Exception as e:
        if type(e).__name__ in ("StreamlitInvalidLayoutContextError", "StreamlitAPIException"):
            st.rerun()
        else:
            raise

def _fmt_hm(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) - timedelta(hours=3)).strftime("%H:%M")

def _quadro_fragmento():
    """Alertas emitidos por qualquer meteorologista + quem está de plantão. Atualiza sozinho a cada 5 s.
    Avisos (mensagem + sinal sonoro), uma vez por alerta em cada sessão: alerta novo emitido por outra pessoa,
    faltando 5 min e faltando 1 min para o fim."""
    q = _quadro()
    itens, agora = _quadro_listar(), time.time()
    previsto = _plantao_agora(q["escala"])
    meu = _nome_atual().lower()
    # --- presença online ---
    online = _presenca_batimento()
    nomes_on = [("Você (" + v["nome"] + ")" if v["nome"].strip().lower() == meu else v["nome"]) for v in online]
    st.markdown(f"**🟢 Online agora ({len(online)}):** " + (", ".join(f"`{n}`" for n in nomes_on) if nomes_on else "_só você_"))
    vistos_on = st.session_state.get("_online_vistos")
    atuais_on = {v["nome"].strip().lower() for v in online}
    if vistos_on is not None:
        for v in online:
            n = v["nome"].strip().lower()
            if n not in vistos_on and n != meu:
                st.toast(f"👋 {v['nome']} entrou no site", icon="🟢")
        for n in vistos_on - atuais_on:
            st.toast(f"👋 {n.title()} saiu do site", icon="⚪")
    st.session_state["_online_vistos"] = atuais_on
    avisados = st.session_state.setdefault("_avisados_quadro", set())
    primeira = "_quadro_iniciado" not in st.session_state
    st.session_state["_quadro_iniciado"] = True
    toques = []   # (modo, mensagem)
    for it in itens:
        resta = int(it["expira_ts"] - agora)
        nome = str(it["estacao"]).split(" - ")[0]
        emoji = "🔴" if it.get("nivel") == "vermelho" else "🟡"
        cor = "#ff8a80" if it.get("nivel") == "vermelho" else "#ffd166"
        quem = it.get("meteorologista") or "(sem nome)"
        vias = " · ".join(it.get("vias", [])) or "—"
        # alerta novo emitido por OUTRA pessoa
        chave_novo = f"novo:{it['id']}:{int(it['emitido_ts'])}"
        if chave_novo not in avisados:
            avisados.add(chave_novo)
            if not primeira and str(it.get("meteorologista", "")).strip().lower() != meu:
                toques.append(("normal", f"{emoji} {quem} emitiu alerta {'vermelho' if it.get('nivel') == 'vermelho' else 'amarelo'} para {nome}"))
        if 0 < resta <= AVISO_FIM_ALERTA_SEG:
            ch5 = f"5min:{it['id']}:{int(it['expira_ts'])}"
            if ch5 not in avisados:
                avisados.add(ch5)
                toques.append(("normal", f"⏰ Faltam 5 minutos para encerrar o alerta de {nome}"))
        if 0 < resta <= AVISO_ULTIMO_MIN_SEG:
            ch1 = f"1min:{it['id']}:{int(it['expira_ts'])}"
            if ch1 not in avisados:
                avisados.add(ch1)
                toques.append(("urgente", f"🚨 Falta 1 minuto para encerrar o alerta de {nome}"))
    for modo, msg in toques:
        st.toast(msg, icon="⏰")
    if toques:
        st.session_state["_bip_ate"] = agora + 30
        st.session_state["_bip_token"] = f"{agora:.2f}"
        st.session_state["_bip_modo"] = "urgente" if any(m == "urgente" for m, _ in toques) else "normal"
    for it in itens:
        resta = int(it["expira_ts"] - agora)
        if 0 < resta <= AVISO_FIM_ALERTA_SEG:
            st.warning(f"⏰ Faltam {resta // 60:02d}:{resta % 60:02d} para encerrar o alerta de **{str(it['estacao']).split(' - ')[0]}**. "
                       "Finalize (alerta verde) ou renove a validade se ainda houver risco.")
    # Os alertas ativos aparecem no painel lateral do mapa (aba "Ativos"): este quadro invisível os entrega ao mapa.
    dados_ponte = [{"estacao": it["estacao"], "nivel": it.get("nivel", "amarelo"), "quem": it.get("meteorologista", ""),
                    "emitido_hm": _fmt_hm(it["emitido_ts"]), "expira_hm": _fmt_hm(it["expira_ts"]),
                    "vias": " · ".join(it.get("vias", [])), "resta": max(int(it["expira_ts"] - agora), 0)} for it in itens]
    components.html(_HTML_PONTE_QUADRO.replace("__DADOS__", json.dumps(dados_ponte, ensure_ascii=False).replace("</", "<\\/")), height=0)
    if st.session_state.get("som_quadro", True) and agora < st.session_state.get("_bip_ate", 0):
        components.html(_HTML_BIP_5MIN.replace("__T__", st.session_state.get("_bip_token", "")).replace("__M__", st.session_state.get("_bip_modo", "normal")), height=0)

def _quadro_historico_df():
    q = _quadro()
    with q["lock"]:
        h = list(q["historico"])
    linhas = [{"Data": (datetime.fromtimestamp(x["ts"], tz=timezone.utc) - timedelta(hours=3)).strftime("%d/%m/%Y"),
               "Hora": _fmt_hm(x["ts"]), "Evento": x.get("evento", ""), "Unidade": x.get("estacao", ""),
               "Nível": x.get("nivel", ""), "Meteorologista": x.get("meteorologista", ""), "Via": x.get("via", "")} for x in reversed(h)]
    return pd.DataFrame(linhas, columns=["Data", "Hora", "Evento", "Unidade", "Nível", "Meteorologista", "Via"])

def _quadro_escala_editor():
    q = _quadro()
    with st.expander("📅 Escala prevista dos meteorologistas (compartilhada)"):
        st.caption("Qualquer pessoa que use o app vê e pode editar. Horários em Brasília; turnos que viram a noite "
                   "(ex.: 22:00 → 06:00) são aceitos. “Todos os dias” vale para a semana inteira. Preencha **Data** "
                   "(DD/MM/AAAA) para uma troca pontual: a linha vale só naquele dia e o dia da semana é ignorado.")
        base = pd.DataFrame(q["escala"] or [], columns=["nome", "dia", "data", "inicio", "fim"]).fillna("").rename(
            columns={"nome": "Meteorologista", "dia": "Dia", "data": "Data (opcional)", "inicio": "Início", "fim": "Fim"})
        with st.form("form_escala", border=False):
            ed = st.data_editor(
                base, num_rows="dynamic", use_container_width=True, hide_index=True, key="editor_escala",
                column_config={
                    "Meteorologista": st.column_config.TextColumn(required=True),
                    "Dia": st.column_config.SelectboxColumn(options=["Todos os dias"] + DIAS_SEMANA, default="Todos os dias", required=True),
                    "Data (opcional)": st.column_config.TextColumn(help="DD/MM/AAAA — troca pontual"),
                    "Início": st.column_config.TextColumn(help="HH:MM", default="08:00", required=True),
                    "Fim": st.column_config.TextColumn(help="HH:MM", default="17:00", required=True),
                })
            salvar = st.form_submit_button("💾 Salvar escala", type="primary")
        if salvar:
            novas, erros = [], []
            for _, r in ed.iterrows():
                nome = str(r.get("Meteorologista") or "").strip()
                if not nome:
                    continue
                ini, fim = str(r.get("Início") or "").strip(), str(r.get("Fim") or "").strip()
                data_txt = str(r.get("Data (opcional)") or "").strip()
                data = _data_valida(data_txt) if data_txt else ""
                if _hm_para_min(ini) is None or _hm_para_min(fim) is None or (data_txt and not data):
                    erros.append(nome)
                    continue
                novas.append({"nome": nome, "dia": str(r.get("Dia") or "Todos os dias"), "data": data, "inicio": ini, "fim": fim})
            if erros:
                st.error("Horário ou data inválidos (use HH:MM e DD/MM/AAAA) para: " + ", ".join(erros))
            else:
                with q["lock"]:
                    q["escala"] = novas
                    _quadro_log(q, "escala atualizada", "", "", _nome_atual())
                    _quadro_gravar(q)
                st.success("Escala salva para todos.")
        if q["escala"]:
            cols = {}
            for d in DIAS_SEMANA:
                cols[d] = [f"{e['nome']} {e['inicio']}–{e['fim']}" for e in q["escala"] if not e.get("data") and e.get("dia") in (d, "Todos os dias")]
            alt = max((len(v) for v in cols.values()), default=0)
            st.markdown("**Agenda da semana**")
            st.dataframe(pd.DataFrame({d: v + [""] * (alt - len(v)) for d, v in cols.items()}), hide_index=True, use_container_width=True)
            pontuais = sorted((e for e in q["escala"] if e.get("data")), key=lambda e: (e["data"][6:], e["data"][3:5], e["data"][:2], e["inicio"]))
            if pontuais:
                st.markdown("**Trocas pontuais**")
                st.dataframe(pd.DataFrame([{"Data": e["data"], "Meteorologista": e["nome"], "Horário": f"{e['inicio']}–{e['fim']}"} for e in pontuais]),
                             hide_index=True, use_container_width=True)

def _quadro_historico_expander():
    with st.expander("🕘 Histórico de alertas"):
        df = _quadro_historico_df()
        if df.empty:
            st.caption("Ainda sem registros.")
        else:
            st.dataframe(df.head(100), hide_index=True, use_container_width=True)
            st.download_button("⬇️ Baixar histórico (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="historico_alertas.csv", mime="text/csv")
        st.caption("Guarda os últimos 500 registros: emitido, renovado, finalizado, vencido, removido do quadro e mudanças na escala.")

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
_CHAVES_PERSISTENTES = ("meteorologista_nome", "rio_autenticado", "alertas_raio_ativos", "alertas_unidade", "verde_estado", "som_token", "altura_mapa_pct", "espessura_aneis", "modo_aviso_alerta", "avisos_canto", "hor_ativo", "hor_unidades")

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

if "alertas_raio_ativos" not in st.session_state: st.session_state.alertas_raio_ativos = []
if "alertas_unidade" not in st.session_state: st.session_state.alertas_unidade = {}
if "verde_estado" not in st.session_state: st.session_state.verde_estado = {}

_SENHA_SHA256 = "bb487cbc9f95cb2894adaf8d1a39771c601077eb7299814b21f7b70778da8194"  # SHA-256 da senha de acesso (a senha em si não fica no código)

# Na primeira abertura, identifica imediatamente o meteorologista responsável.
# O restante da interface só é exibido depois da confirmação do nome.
if (not st.session_state.get("rio_autenticado")
        or "meteorologista_nome" not in st.session_state
        or not str(st.session_state.get("meteorologista_nome", "")).strip()):
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
        senha = st.text_input("Senha", type="password", key="rio_senha_input", placeholder="Digite a senha")
        if st.button("Entrar no monitoramento", type="primary", use_container_width=True):
            nome = str(nome).strip()
            if not nome:
                st.warning("Digite o nome do meteorologista para continuar.")
            elif not hmac.compare_digest(hashlib.sha256(senha.encode("utf-8")).hexdigest(), _SENHA_SHA256):
                st.error("Senha incorreta.")
            else:
                st.session_state.meteorologista_nome = nome
                st.session_state.rio_autenticado = True
                st.session_state.pop("rio_senha_input", None)
                _salvar_estado()
                st.rerun()

    _dialog_meteorologista_inicial()
    st.stop()

# O nome NÃO vai mais na URL: quem receber o link precisa informar o próprio nome (e remove "nome" de links antigos).
if "nome" in st.query_params:
    del st.query_params["nome"]

with st.sidebar:
    st.header("⚙ Configuração")
    meteorologista = st.text_input(
        "Meteorologista responsável",
        value=st.session_state.get("meteorologista_nome", ""),
        key="meteorologista_responsavel",
    )
    if meteorologista.strip() != st.session_state.get("meteorologista_nome", ""):
        st.session_state.meteorologista_nome = meteorologista.strip()

    # Boletim horário: logo abaixo do nome do meteorologista
    st.toggle("⏰ Boletim horário (3 em 3 h)", key="hor_ativo",
              help="Gera sozinho, 5 min antes de cada horário (00h, 03h, 06h … 21h), o boletim das próximas 12 h para as unidades escolhidas, "
                   "no formato do boletim clássico, com ênfase em vento e rajada, e avisa no canto direito da tela.")
    if st.session_state.get("hor_ativo"):
        _opc_hor = sorted(boletins_bo.UNIDADES, key=_chave_alfabetica)
        st.session_state["hor_unidades"] = [n for n in st.session_state.get("hor_unidades", []) if n in _opc_hor]
        st.multiselect("Unidades do boletim horário", _opc_hor, key="hor_unidades", placeholder="Escolha uma ou mais unidades",
                       help="Só estas unidades são baixadas e geradas (2 consultas por unidade), sem fila.")

    df_stations = pd.DataFrame(ESTACOES_PADRAO)

    st.subheader("⚡ Raios ao vivo (GLM/GOES-19)")
    raios_minutos = 20  # janela exibida no mapa (cores: 0–5 · 5–10 · 10–15 · 15–20 min)
    intervalo_raios_seg = 120
    st.caption("🔄 Atualização automática: a cada 2 minutos")
    st.caption("🔊 O som e o aviso automático de alerta (pop-up ou canto, veja 🔔 abaixo) ficam sempre ativos.")
    arquivo_som = st.file_uploader("Trocar o som de alerta (opcional)", type=["mp3", "wav", "ogg", "m4a"])
    mostrar_deslocamento = st.checkbox("Mostrar deslocamento das células de tempestade", value=True)

    st.subheader("📏 Anéis de distância no mapa")
    mostrar_aneis = st.checkbox("Mostrar anéis de distância ao redor das unidades", value=True)
    paleta_escolhida = st.selectbox("Cores dos anéis", list(PALETAS_ANEIS), disabled=not mostrar_aneis)
    cores_aneis = PALETAS_ANEIS[paleta_escolhida]
    st.caption("Anéis visíveis (desmarque para tirar do mapa):")
    _cols_an = st.columns(len(DISTANCIAS_ANEIS_KM))
    aneis_visiveis = set()
    for _c, _km in zip(_cols_an, DISTANCIAS_ANEIS_KM):
        if _c.checkbox(f"{_km} km", value=True, key=f"anel_visivel_{_km}", disabled=not mostrar_aneis):
            aneis_visiveis.add(_km)
    if "espessura_aneis" not in st.session_state:
        st.session_state["espessura_aneis"] = 3       # médio
    espessura_aneis = st.slider("Espessura das linhas dos anéis", min_value=1, max_value=5, step=1, key="espessura_aneis",
                                disabled=not mostrar_aneis, help="1 = mais fino · 3 = médio (padrão) · 5 = mais grosso")

    st.subheader("🔔 Aviso de alerta de raio")
    MODOS_AVISO = ["Pop-up no meio da tela (padrão)", "Canto esquerdo (com rolagem)", "Canto direito (com rolagem)"]
    if st.session_state.get("modo_aviso_alerta") not in MODOS_AVISO:
        st.session_state["modo_aviso_alerta"] = MODOS_AVISO[0]
    st.radio("Como mostrar o alerta novo", MODOS_AVISO, key="modo_aviso_alerta",
             help="Pop-up: janela no meio da tela, como sempre foi. Canto: um painel fixo num dos lados, com rolagem, que acumula os avisos "
                  "até você fechar (✕) e não cobre o mapa.")

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

with st.container(border=True):
    _cq1, _cq2 = st.columns([5, 1.5], vertical_alignment="center")
    _cq1.markdown("##### 📡 Quadro de operação")
    _cq2.toggle("🔔 Som do quadro", value=True, key="som_quadro", help="Sinal sonoro para alerta novo de outra pessoa e para os avisos de 5 min e 1 min do fim do alerta.")
    st.fragment(run_every=5)(_quadro_fragmento)()
    st.fragment(run_every=5)(_quadro_historico_expander)()   # atualiza sozinho, sem precisar recarregar a página

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
        # Mostra TODOS os raios da janela: sem remover pontos sobrepostos e sem limite/amostra.
        df = raios_df.dropna(subset=["lat", "lon", "time"]).copy()
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["idade_min"] = ((agora - df["time"]).dt.total_seconds() / 60).clip(lower=0)
        raios_mapa = df.sort_values("time", kind="stable")  # antigos primeiro, novos por cima
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

    def _km_encerrados_verde():
        return {k: v.get("encerrado_km", VERDE_RAIO_KM)
                for k, v in st.session_state.alertas_unidade.items() if v.get("encerrado_ts")}

    df_status = calcular_status_estacoes(df_stations, raios_alerta, encerrados=_encerrados_verde(), km_encerrados=_km_encerrados_verde())

    # ---- Alerta verde ----
    # SÓ MANUAL: o alerta continua ativo mesmo que a unidade saia do alerta (os raios se afastem ou parem);
    # quem encerra é o meteorologista, em "Finalizar alerta" / "Emitir alerta verde" / "Tirar".
    notificacoes_verde = []
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
            # (sem renotificar por vencimento: o alerta só termina quando o meteorologista encerra)

            if deve_notificar:
                # Outro meteorologista (outra sessão) já emitiu alerta igual/maior para esta unidade, ou já finalizou e
                # o raio é o mesmo de antes: não cria card nem toca som de novo (evita mensagem duplicada no WhatsApp).
                _q_ativo = _quadro_ativo(chave_estacao)
                if _q_ativo and _NIVEL_ORDEM.get(_q_ativo.get("nivel"), 0) >= _NIVEL_ORDEM.get(nivel_atual, 0):
                    continue
                _v_ts = _quadro_verde_ts(chave_estacao)
                if _v_ts:
                    _ult = ultimo_raio_ate_km(raios_df, float(est["lat"]), float(est["lon"]), 30 if nivel_atual == "vermelho" else 50)
                    if _ult is None or _ult.timestamp() <= _v_ts:
                        continue
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

    # Alerta cujo fim da validade já passou há mais de 10 min e não foi renovado (nova emissão / nova validade) nem encerrado: some.
    _agora_lim = time.time()
    _quadro_listar()   # também limpa do quadro compartilhado os vencidos
    def _fim_efetivo(a):
        _qa = _quadro_ativo(a.get("estacao"))
        return max(a["expira"], _qa["expira_ts"]) if _qa and _qa.get("nivel") == a.get("nivel") else a["expira"]
    _vencidos = [a for a in st.session_state.alertas_raio_ativos
                 if a.get("nivel") != "verde" and _agora_lim > _fim_efetivo(a) + AUTO_REMOVER_APOS_FIM_MIN * 60]
    for a in _vencidos:
        _reg = st.session_state.alertas_unidade.get(a.get("estacao"))
        if _reg and not _reg.get("encerrado_ts"):
            st.session_state.alertas_unidade.pop(a.get("estacao"), None)   # libera a unidade para um novo alerta se houver novos raios
    st.session_state.alertas_raio_ativos = [a for a in st.session_state.alertas_raio_ativos
                                            if a not in _vencidos and (a.get("nivel") != "verde" or a["expira"] > time.time())]

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

def _aviso_duplicado(a):
    """Texto de aviso se esta mesma mensagem (unidade + nível) já foi enviada recentemente por alguém; senão ''."""
    r = _quadro_enviado_recente(a.get("estacao"), a.get("nivel"))
    if not r:
        return ""
    hm = (datetime.fromtimestamp(r["ts"], tz=timezone.utc) - timedelta(hours=3)).strftime("%H:%M")
    return f"{r.get('por') or 'alguém'} às {hm}"

def _construir_mapa(df_status, raios_df, celulas_com_trajetoria, estacoes_novas, status_texto):
    estacoes_payload = [
        {
            "nome": e["nome"], "estacao": e["estacao"], "lat": e["lat"], "lon": e["lon"],
            "risco_emoji": e["risco_emoji"], "risco_label": e["risco_label"], "risco_color": e["risco_color"],
            "dist_min_km": e["dist_min_km"], "contatos": e["contatos"], "risco_score": int(e["risco_score"]),
        }
        for _, e in df_status.iterrows()
    ]
    aneis_payload = [{"km": km, "cor": cor} for km, cor in zip(DISTANCIAS_ANEIS_KM, cores_aneis) if mostrar_aneis and km in aneis_visiveis]
    raios_payload = _preparar_payload_raios(raios_df, celulas_com_trajetoria)

    # Alertas ativos, pra aba "Alertas" do painel que fica dentro do mapa (usável em tela cheia).
    _finalizaveis = _alertas_finalizaveis()
    alertas_payload = [
        {"id": a["id"], "estacao": a.get("estacao"), "quem_recebeu": a.get("quem_recebeu", ""),
         "copia": montar_texto_copia(a), "base": a["texto"], "nivel": a.get("nivel"), "finalizavel": a["id"] in _finalizaveis,
         "anteciparvel": a.get("nivel") == "amarelo" and a["id"] in _finalizaveis,
         "rebaixavel": a.get("nivel") == "vermelho" and a["id"] in _finalizaveis, "duracao_min": a.get("duracao_min", 60),
         "fim_hm": a.get("fim_hm", ""), "ja_enviado": _aviso_duplicado(a)}
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
        espessura_aneis=int(espessura_aneis),
        meteorologista=str(st.session_state.get("meteorologista_nome", "")).strip(),
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
                    if valor.strip():
                        a["acionado"] = True
                    st.session_state[f"quem_recebeu_{a['id']}"] = valor  # mantém o campo do painel lateral igual
        elif tipo == "finalizar":
            alvo = next((x for x in st.session_state.alertas_raio_ativos if x.get("id") == evento.get("id")), None)
            if alvo is not None and alvo["id"] in _alertas_finalizaveis():
                _finalizar_alerta_unidade(alvo["estacao"])
        elif tipo == "antecipar":
            alvo = next((x for x in st.session_state.alertas_raio_ativos if x.get("id") == evento.get("id")), None)
            if alvo is not None and alvo.get("nivel") == "amarelo" and alvo["id"] in _alertas_finalizaveis():
                _antecipar_para_vermelho(alvo)
        elif tipo == "rebaixar":
            alvo = next((x for x in st.session_state.alertas_raio_ativos if x.get("id") == evento.get("id")), None)
            if alvo is not None and alvo.get("nivel") == "vermelho" and alvo["id"] in _alertas_finalizaveis():
                _rebaixar_para_amarelo(alvo)
        elif tipo == "validade":
            _definir_validade(evento.get("id"), evento.get("minutos"), evento.get("fim"))
        elif tipo == "emitir":
            _emitir_alerta_evento(evento.get("id"), evento.get("minutos"), evento.get("via"), evento.get("fim"))
        elif tipo == "excluir":
            _quadro_remover(alerta_id=evento.get("id"), motivo="excluído")
            st.session_state.alertas_raio_ativos = [x for x in st.session_state.alertas_raio_ativos if x.get("id") != evento.get("id")]
        elif tipo == "emitir_verde":
            _emitir_verde_manual(evento.get("estacao"))
        elif tipo == "emitir_nivel":
            _emitir_nivel_manual(evento.get("estacao"), evento.get("nivel"))
        elif tipo == "tirar_quadro":
            _quadro_remover(estacao=evento.get("estacao"), motivo="removido do quadro")
        elif tipo == "limpar":
            st.session_state.alertas_raio_ativos = []
        _salvar_estado()
        st.rerun()

with col_mapa:
    st.fragment(run_every=intervalo_raios_seg)(_renderizar_mapa_ao_vivo)()

def _painel_avisos_canto(lado):
    """Avisos de alerta num painel fixo no canto (esquerdo/direito), com rolagem. Cada aviso fica até ser fechado (✕)."""
    avisos = st.session_state.get("avisos_canto") or []
    if not avisos:
        return
    try:
        escuro = getattr(st.context.theme, "type", "light") == "dark"
    except Exception:
        escuro = False
    fundo, borda = ("#10151d", "#2b3444") if escuro else ("#ffffff", "#c9d1dc")
    st.markdown(
        "<style>.st-key-avisos_canto_box{position:fixed;bottom:16px;%s:16px;width:min(430px,92vw);max-height:72vh;overflow-y:auto;"
        "z-index:999990;background:%s;border:1px solid %s;border-radius:12px;padding:10px 12px;box-shadow:0 8px 28px rgba(0,0,0,.35);}"
        ".st-key-avisos_canto_box pre{white-space:pre-wrap;word-break:break-word;}</style>" % (lado, fundo, borda),
        unsafe_allow_html=True)
    with st.container(key="avisos_canto_box"):
        _h1, _h2 = st.columns([4, 2], vertical_alignment="center")
        _h1.markdown(f"**🔔 Alertas novos ({len(avisos)})**")
        if _h2.button("Fechar todos", key="fechar_todos_avisos", use_container_width=True):
            st.session_state["avisos_canto"] = []
            st.rerun()
        for av in list(avisos):
            with st.container(border=True):
                _c1, _c2 = st.columns([6, 1], vertical_alignment="center")
                _c1.markdown(f"**{av['titulo']}** · {av['hm']}")
                if _c2.button("✕", key=f"fechar_aviso_{av['id']}", help="Fechar este aviso"):
                    st.session_state["avisos_canto"] = [x for x in st.session_state["avisos_canto"] if x["id"] != av["id"]]
                    st.rerun()
                st.code(av["texto"], language=None)

# Aviso do alerta: mostrado uma única vez por alerta novo, como pop-up (padrão) ou no canto da tela (opção nas configurações).
_modo_aviso = st.session_state.get("modo_aviso_alerta", "")
if st.session_state.get("dialog_raio_pendente"):
    st.session_state["dialog_raio_pendente"] = False
    _titulo_dialog = "🟢 Alerta verde — sem raios próximos" if st.session_state.get("dialog_raio_so_verde") else "⚡ Raio próximo de unidade(s)!"
    if _modo_aviso.startswith("Canto"):
        _hm_av = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")
        _lista = st.session_state.get("avisos_canto") or []
        _lista.insert(0, {"id": f"{time.time():.3f}", "titulo": _titulo_dialog, "hm": _hm_av,
                          "texto": st.session_state.get("dialog_raio_texto", "")})
        st.session_state["avisos_canto"] = _lista[:30]
    else:
        st.dialog(_titulo_dialog)(_corpo_dialog_alerta_raio)()
if _modo_aviso.startswith("Canto"):
    _painel_avisos_canto("left" if "esquerdo" in _modo_aviso else "right")
st.session_state["_run_completo"] = False

def _painel_alertas_ativos():
    """Aba 'Ativos' do painel lateral: alertas emitidos por qualquer meteorologista (quadro compartilhado)."""
    itens, agora = _quadro_listar(), time.time()
    if not itens:
        st.success("Nenhum alerta ativo no momento.")
        return
    for it in itens:
        resta = max(int(it["expira_ts"] - agora), 0)
        nome = str(it["estacao"]).split(" - ")[0]
        verm = it.get("nivel") == "vermelho"
        emoji, cor = ("🔴", "#ff8a80") if verm else ("🟡", "#ffd166")
        quem = it.get("meteorologista") or "(sem nome)"
        vias = " · ".join(it.get("vias", []))
        corcont = "#ff8a80" if resta <= AVISO_FIM_ALERTA_SEG else "#e5e7eb"
        with st.container(border=True):
            st.markdown(
                f"<div style='border-left:4px solid {cor};padding-left:10px'>"
                f"<div style='font-weight:700'>{emoji} {nome}</div>"
                f"<div style='color:{cor};font-size:13px'>Alerta {'vermelho' if verm else 'amarelo'}</div>"
                f"<div style='font-size:13px;margin-top:2px'>Emitido por <b>{quem}</b> às {_fmt_hm(it['emitido_ts'])}" + (f" ({vias})" if vias else "") + "</div>"
                f"<div style='font-size:13px'>Válido até <b>{_fmt_hm(it['expira_ts'])}</b> · "
                + (f"faltam <b style='color:{corcont}'>{resta // 60:02d}:{resta % 60:02d}</b>" if resta > 0
                   else "<b style='color:#ff8a80'>⏰ prazo vencido: sai sozinho 10 min após o fim se não renovar</b>") + "</div></div>", unsafe_allow_html=True)
            if st.button("✖ Tirar", key=f"ativo_tirar_{it['estacao']}", help="Remove do quadro (alerta encerrado)"):
                _quadro_remover(estacao=it["estacao"], motivo="removido do quadro")
                _rerun_fragmento()

with col_lado:
  if mostrar_painel_alertas:
    with st.container(key="painel_lateral"):
        def _corpo_painel_lateral():
            df_status = st.session_state.get("_fragment_df_status", pd.DataFrame())
            tab_ativos, tab_risco, tab_alertas = st.tabs(["📡 Ativos", "🚨 Risco", "📋 Alertas"])

            with tab_ativos:
                st.fragment(run_every=5)(_painel_alertas_ativos)()   # alertas de todos os meteorologistas; atualiza a cada 5 s

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
                    _finalizaveis = _alertas_finalizaveis()
                    for a in list(st.session_state.alertas_raio_ativos):
                        with st.container(border=True):
                            col_txt, col_del = st.columns([6, 1])
                            with col_txt:
                                quem = st.text_input(
                                    "Quem recebeu o alerta:", value=a.get("quem_recebeu", ""),
                                    key=f"quem_recebeu_{a['id']}", placeholder="nome de quem confirmou o recebimento",
                                )
                                a["quem_recebeu"] = quem
                                if quem.strip():
                                    a["acionado"] = True
                                st.code(montar_texto_copia(a), language=None)
                                _dur, _fim = 60, ""
                                if a.get("nivel") != "verde":
                                    _opc = list(DURACOES_ALERTA_MIN) + [0]
                                    _idx = len(_opc) - 1 if a.get("fim_hm") else (_opc.index(a.get("duracao_min", 60)) if a.get("duracao_min", 60) in DURACOES_ALERTA_MIN else 0)
                                    _dur = st.radio("Validade do alerta", _opc, index=_idx,
                                                    format_func=lambda m: {60: "1 hora", 90: "1 hora e meia", 120: "2 horas", 0: "Fim manual"}[m],
                                                    horizontal=True, key=f"dur_{a['id']}")
                                    if _dur == 0:
                                        _fim = st.text_input("Fim do alerta (HH:MM, Brasília)", value=a.get("fim_hm", ""), max_chars=5,
                                                             key=f"fim_{a['id']}", placeholder="ex.: 15:30").strip()
                                        _calc = _min_ate_hm(_fim)
                                        if _fim and _calc is None:
                                            st.warning("Horário inválido. Use HH:MM, por exemplo 15:30.")
                                        if _calc is not None and _fim.zfill(5) != a.get("fim_hm"):
                                            _definir_validade(a["id"], _calc, _fim)
                                        _dur = _calc or 60
                                    elif a.get("fim_hm") or _dur != a.get("duracao_min", 60):
                                        _definir_validade(a["id"], _dur)
                                _ev_b = _botoes_envio(estacao=a.get("estacao", ""), texto=montar_texto_copia(a), id=a.get("id", ""),
                                                      minutos=_dur, fim=_fim, nivel=a.get("nivel", "vermelho"), meteorologista=_nome_atual(),
                                                      ja_enviado=_aviso_duplicado(a), default=None, key=f"botoes_{a['id']}")
                                if isinstance(_ev_b, dict) and _ev_b.get("nonce") and _ev_b["nonce"] != st.session_state.get(f"_nonce_botoes_{a['id']}"):
                                    st.session_state[f"_nonce_botoes_{a['id']}"] = _ev_b["nonce"]
                                    _emitir_alerta_evento(a["id"], _ev_b.get("minutos"), _ev_b.get("via"), _ev_b.get("fim"))
                                    _salvar_estado()
                                    st.rerun()
                                if a.get("nivel") == "amarelo" and a.get("id") in _finalizaveis:
                                    if st.button("🔴 Antecipar para vermelho", key=f"antecipar_{a['id']}",
                                                 help="Gera um alerta vermelho para esta unidade, sem esperar o raio chegar a 30 km"):
                                        _antecipar_para_vermelho(a)
                                        st.rerun()
                                if a.get("nivel") == "vermelho" and a.get("id") in _finalizaveis:
                                    if st.button("🟡 Alterar para amarelo", key=f"rebaixar_{a['id']}",
                                                 help="Gera um alerta amarelo para esta unidade (o risco diminuiu, mas o alerta segue ativo até você encerrar)"):
                                        _rebaixar_para_amarelo(a)
                                        st.rerun()
                                if a.get("id") in _finalizaveis:
                                    if st.button("🟢 Finalizar alerta", key=f"finalizar_alerta_{a['id']}",
                                                 help="Emite o alerta verde (fim do alerta de raios) para esta unidade"):
                                        _finalizar_alerta_unidade(a["estacao"])
                                        st.rerun()  # rerun completo: o mapa e o status da unidade já voltam verdes
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
def _worker_boletins(estado, unidades, dias, usar_servidor=True):
    total = len(unidades)
    seguidas = 0
    for i, (nome, (lat, lon)) in enumerate(unidades.items(), 1):
        estado["atual"] = nome
        if not usar_servidor and not boletins_bo.em_cache(lat, lon, dias):
            estado["erros"].append((nome, "Os dados desta unidade não foram baixados pelo navegador (veja o aviso acima)."))
            estado["feitos"] = i
            continue
        try:
            estado["resultados"][nome] = boletins_bo.boletim_unidade(nome, lat, lon, dias)
            seguidas = 0
        except Exception as e:
            estado["erros"].append((nome, str(e)))
            seguidas += 1
        estado["feitos"] = i
        if seguidas >= 2 and not estado["resultados"]:
            # Open-Meteo não está respondendo (ex.: limite 429): não adianta insistir nas outras unidades
            estado["erros"].append(("Geração interrompida", "O Open-Meteo não respondeu para as primeiras unidades (veja o erro acima). Tente de novo em alguns minutos."))
            break
        time.sleep(0.3)
    boletins_bo.STATUS_DOWNLOAD["msg"] = ""
    estado["rodando"] = False


unidades_boletim = dict(boletins_bo.UNIDADES)


_HTML_WHATSAPP = """<!doctype html><html><head><meta charset="utf-8"><style>
  html, body { margin:0; padding:0; background:transparent; color:#e6e6e6; font:14px 'Segoe UI', Arial, sans-serif; }
  .topo { display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:2px 2px 10px; }
  button { cursor:pointer; border-radius:8px; border:1px solid #3a4150; background:#232834; color:#f1f1f1; padding:8px 14px; font:inherit; }
  button:hover { background:#2e3544; }
  button.principal { background:#25d366; border-color:#25d366; color:#06210f; font-weight:600; }
  button.principal:hover { background:#3be07b; }
  .linha { display:flex; align-items:center; gap:12px; padding:7px 10px; border:1px solid #2a303b; border-radius:9px; margin-bottom:6px; background:#161a22; }
  .linha.aberto { border-color:#25d366; background:#142019; }
  .nome { flex:1; font-weight:600; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  label { display:flex; align-items:center; gap:6px; color:#c9cdd6; white-space:nowrap; cursor:pointer; }
  #aviso { display:none; margin:0 0 8px; padding:8px 10px; border-radius:8px; background:#3a2b12; border:1px solid #8a6417; color:#ffd78a; }
  .nota { color:#8b93a3; font-size:12.5px; margin:2px 2px 10px; }
</style></head><body>
<div class="topo">
  <button class="principal" id="fila" title="Prepara os boletins um grupo por vez; quando voce envia um, o script abre o proximo. Precisa do script do Tampermonkey.">🤖 Preparar todos (fila)</button>
  <button id="filaSite" style="background:#1d70b8;border-color:#1d70b8;color:#fff;font-weight:600" title="Manda todos os boletins para uma fila no site: o painel na aba /newsletter preenche um por vez; voce confere, clica em Adicionar boletim e o proximo e preenchido sozinho.">📝 Registrar todos no site (fila)</button>
  <span class="nota" id="nota"></span>
</div>
<div id="aviso"></div>
<div id="lista"></div>
<script>
  var ITENS = __ITENS__;
  var GERACAO = "__GERACAO__";
  var NOME_ABA = "rio_whatsapp_web";          // o app abre o WhatsApp Web nesta aba e reaproveita a MESMA aba nos próximos cliques
  var celular = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  function lerFlag(k) { try { return sessionStorage.getItem(k) === "1"; } catch (e) { return false; } }
  function gravarFlag(k, v) { try { sessionStorage.setItem(k, v ? "1" : "0"); } catch (e) {} }
  function aviso(t) { var a = document.getElementById("aviso"); a.textContent = t; a.style.display = t ? "block" : "none"; }
  document.getElementById("nota").textContent = "Use com o WhatsApp Web já aberto em outra aba.";
  document.getElementById("fila").addEventListener("click", function () {
    var btn = this, rot = "🤖 Preparar todos (fila)", confirmou = false;
    if (!confirm("Preparar " + ITENS.length + " boletins em fila? Um grupo por vez: voce confere e aperta Enter em cada um; o proximo abre sozinho.")) return;
    function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
    window.addEventListener("message", ack);
    try {
      (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "fila",
        itens: ITENS.map(function (i) { return { id: i.id, estacao: i.estacao, texto: i.texto }; }) }, "*");
    } catch (e) {}
    setTimeout(function () {
      window.removeEventListener("message", ack);
      btn.textContent = confirmou ? "✔ Fila enviada ao WhatsApp - va para a aba dele" : "Script nao detectado - instale o Tampermonkey";
      setTimeout(function () { btn.textContent = rot; }, 5000);
    }, 1200);
  });
  document.getElementById("filaSite").addEventListener("click", function () {
    var btn = this, rot = "📝 Registrar todos no site (fila)", confirmou = false;
    if (!confirm("Criar a fila de " + ITENS.length + " boletins no site? Abra a aba 'Histórico de Boletins' (/newsletter). Um painel preenche um boletim por vez; voce confere e clica em 'Adicionar boletim'.")) return;
    function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
    window.addEventListener("message", ack);
    try {
      (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "fila_site",
        itens: ITENS.map(function (i) { return { id: i.id, estacao: i.estacao, status: i.status, titulo: i.titulo, resumo: i.resumo, texto: i.texto_site }; }) }, "*");
    } catch (e) {}
    setTimeout(function () {
      window.removeEventListener("message", ack);
      btn.textContent = confirmou ? "✔ Fila criada - va para a aba /newsletter do site" : "Script nao detectado (atualize o Tampermonkey para v2.3)";
      setTimeout(function () { btn.textContent = rot; }, 6000);
    }, 1200);
  });
  var PORID = {};
  window.addEventListener("message", function (ev) {     // o site avisa os boletins ja salvos: marca o check "Site"
    var d = ev.data; if (!d || d.fonte !== "rio-raios-prog-site" || !Array.isArray(d.feitos)) return;
    d.feitos.forEach(function (id) { var r = PORID[id]; if (r) { r.cb.checked = true; gravarFlag(r.k, true); } });
  });
  var lista = document.getElementById("lista");
  ITENS.forEach(function (it) {
    var kAberto = "rio_wa_aberto_" + GERACAO + "_" + it.id, kWa = "rio_wa_check_" + GERACAO + "_" + it.id, kSite = "rio_site_check_" + GERACAO + "_" + it.id;
    var linha = document.createElement("div"); linha.className = "linha" + (lerFlag(kAberto) ? " aberto" : "");
    var nome = document.createElement("div"); nome.className = "nome"; nome.textContent = it.nome; nome.title = it.nome;
    function marcador(chave, texto) {
      var l = document.createElement("label"); var c = document.createElement("input"); c.type = "checkbox"; c.checked = lerFlag(chave);
      c.addEventListener("change", function () { gravarFlag(chave, c.checked); });
      l.appendChild(c); l.appendChild(document.createTextNode(texto)); return { lab: l, cb: c };
    }
    var mWa = marcador(kWa, "WhatsApp"), mSite = marcador(kSite, "Site");
    var cbWa = mWa.cb, cbSite = mSite.cb, labWa = mWa.lab, labSite = mSite.lab;
    PORID[it.id] = { cb: cbSite, k: kSite };
    var b2 = document.createElement("button"); b2.className = "principal"; b2.textContent = "🤖 Preparar no WhatsApp";
    b2.title = "Precisa do script do Tampermonkey (pasta whatsapp_assistente): abre o grupo da unidade no WhatsApp Web e deixa o boletim digitado para voce conferir e apertar Enter.";
    b2.addEventListener("click", function () {
      var confirmou = false;
      function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
      window.addEventListener("message", ack);
      try { (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "preparar", id: it.id, estacao: it.estacao, texto: it.texto }, "*"); } catch (e) {}
      setTimeout(function () {
        window.removeEventListener("message", ack);
        if (confirmou) { gravarFlag(kAberto, true); linha.classList.add("aberto"); cbWa.checked = true; gravarFlag(kWa, true); b2.textContent = "✔ Enviado ao WhatsApp - confira la e de Enter"; }
        else {
          var t = document.createElement("textarea"); t.value = it.texto; t.style.position = "fixed"; t.style.opacity = "0";
          document.body.appendChild(t); t.select(); try { document.execCommand("copy"); } catch (e) {} document.body.removeChild(t);
          b2.textContent = "Script nao detectado - texto copiado (Ctrl+V)";
        }
        setTimeout(function () { b2.textContent = "🤖 Preparar no WhatsApp"; }, 4000);
      }, 1200);
    });
    var b3 = document.createElement("button"); b3.textContent = "📝 Registrar no site";
    b3.title = "Preenche 'Novo boletim' no site da BlueOcean (aba Histórico de Boletins aberta). Você confere e clica em Adicionar boletim.";
    b3.style.cssText = "background:#1d70b8;border-color:#1d70b8;color:#fff";
    b3.addEventListener("click", function () {
      var confirmou = false;
      function ack(ev) { if (ev.data && ev.data.fonte === "rio-raios-ack") confirmou = true; }
      window.addEventListener("message", ack);
      try { (window.top || window.parent).postMessage({ fonte: "rio-raios", tipo: "boletim", estacao: it.estacao, status: it.status,
                                                         titulo: it.titulo, resumo: it.resumo, texto: it.texto_site }, "*"); } catch (e) {}
      setTimeout(function () {
        window.removeEventListener("message", ack);
        if (confirmou) { cbSite.checked = true; gravarFlag(kSite, true); }
        b3.textContent = confirmou ? "✔ Enviado - confira o formulario na aba do site" : "Script nao detectado (atualize o Tampermonkey)";
        setTimeout(function () { b3.textContent = "📝 Registrar no site"; }, 4000);
      }, 1200);
    });
    linha.appendChild(nome); linha.appendChild(b2); linha.appendChild(labWa); linha.appendChild(b3); linha.appendChild(labSite); lista.appendChild(linha);
  });
</script></body></html>"""


def _dados_site_boletim(nome, texto):
    """Campos do formulário 'Novo boletim' do site: status pelas bolinhas (qualquer 🔴 = vermelho; senão qualquer 🟡 = amarelo; senão verde),
    título = primeira linha da mensagem no formato "<unidade> - Boletim de previsão do tempo" e texto = resto da mensagem sem a marcação do WhatsApp. Sem resumo."""
    status = "vermelho" if "🔴" in texto else ("amarelo" if "🟡" in texto else "verde")
    linhas = []
    for l in texto.splitlines():
        l = l.replace("*", "")
        if l.startswith("_") and l.endswith("_"):
            l = l[1:-1]
        linhas.append(l)
    return {"status": status, "titulo": f"{nome} - Boletim de previsão do tempo", "resumo": "",
            "texto_site": "\n".join(linhas[1:]).strip()}


def _secao_whatsapp_manual(resultados, geracao_id):
    """Lista de unidades; cada botão abre o WhatsApp Web (numa aba que o app reaproveita) com o boletim já escrito.
    Quem escolhe o grupo e aperta "enviar" é a pessoa: nenhuma automação, sem risco de banimento."""
    with st.expander("📲 Enviar pelo WhatsApp Web (assistido)", expanded=True):
        st.markdown(
            "Com o script do Tampermonkey instalado (pasta `whatsapp_assistente`), clique em **🤖 Preparar no WhatsApp** "
            "na linha da unidade (ou em **🤖 Preparar todos (fila)**): o grupo abre na aba do WhatsApp Web que **já está aberta** "
            "e o boletim fica digitado; é só conferir e apertar Enter. Depois marque **enviado** para controlar."
        )
        st.caption("Mantenha o WhatsApp Web aberto e logado em uma aba. O WhatsApp só funciona em uma aba por vez, "
                   "então o app não abre outra aba por conta própria. Sem o script, o botão apenas copia o boletim para você colar no grupo.")
        itens = [dict({"id": boletins_bo.slug(n), "nome": n.split(" - ")[0], "estacao": n, "texto": t}, **_dados_site_boletim(n, t)) for n, t in resultados.items()]
        html = (_HTML_WHATSAPP
                .replace("__ITENS__", json.dumps(itens, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__GERACAO__", re.sub(r"[^0-9A-Za-z]", "", str(geracao_id))))
        components.html(html, height=min(110 + 50 * len(itens), 650), scrolling=True)


_estado_boletins = st.session_state.get("boletins_estado")
_boletins_rodando = bool(_estado_boletins and _estado_boletins["rodando"])


def _secao_boletins(unidades_base):
    st.subheader("📨 Boletins de previsão")
    st.caption("ENSEMBLE (média consenso) entre ECMWF, ICON e GFS do Open-Meteo.")

    estado = st.session_state.get("boletins_estado")
    rodando = bool(estado and estado["rodando"]) or bool(st.session_state.get("bol_pre"))

    c1, c2 = st.columns([3, 1])
    with c1:
        filtro = st.text_input("Filtro (só unidades cujo nome contém…)", key="bol_filtro", placeholder="ex.: Macaé", disabled=rodando)
    with c2:
        dias = st.number_input("Dias de previsão", min_value=1, max_value=7, value=boletins_bo.DIAS_PREVISAO, key="bol_dias", disabled=rodando)

    unidades = {n: c for n, c in sorted(unidades_base.items(), key=lambda kv: _chave_alfabetica(kv[0]))
                if not filtro or filtro.lower() in n.lower()}   # ordem alfabética: vale para a geração, o arquivo e a lista do WhatsApp
    st.caption(f"{len(unidades)} unidade(s) selecionada(s).")

    def _iniciar(unidades_, dias_, usar_servidor):
        novo = {"rodando": True, "resultados": {}, "erros": [], "feitos": 0, "total": len(unidades_), "atual": "",
                "data": utc_para_brasilia(datetime.now(timezone.utc)).strftime("%Y%m%d"),
                "hoje_dd_mm": utc_para_brasilia(datetime.now(timezone.utc)).strftime("%d/%m")}
        novo["gerado_id"] = f"{int(time.time())}"   # muda a cada geração: o "enviado/aberto" da lista recomeça
        st.session_state["boletins_estado"] = novo
        threading.Thread(target=_worker_boletins, args=(novo, unidades_, int(dias_), usar_servidor), daemon=True).start()

    pre = st.session_state.get("bol_pre")
    if st.button(f"📨 Gerar boletins ({len(unidades)})", key="bol_gerar", type="primary", disabled=(not unidades) or rodando or bool(pre)):
        faltam = {n: c for n, c in unidades.items() if not boletins_bo.em_cache(c[0], c[1], int(dias))}
        if boletins_bo.API_KEY or not faltam:
            _iniciar(unidades, dias, True)          # chave paga no servidor, ou tudo já em cache
        else:
            # Sem chave: o NAVEGADOR de quem clicou baixa do Open-Meteo (o limite diário conta no IP dessa pessoa,
            # não no IP compartilhado do servidor). Os dados caem no cache e o gerador de boletins roda em seguida.
            reqs = [{"id": n, "url": boletins_bo.montar_url(lat, lon, int(dias))} for n, (lat, lon) in faltam.items()]
            st.session_state["bol_pre"] = {"id": f"{time.time():.3f}", "reqs": reqs, "unidades": unidades, "dias": int(dias)}
            st.session_state.pop("boletins_estado", None)
        st.rerun()

    if pre:
        st.caption("⬇️ Baixando a previsão do Open-Meteo pelo seu navegador…")
        val = _bo_fetch_boletins(reqs=pre["reqs"], pausa_ms=300, assinatura=pre["id"], key=f"bolfetch_{pre['id']}", default=None)
        feitos = (val or {}).get("feitos", 0)
        st.progress(min(feitos / max(len(pre["reqs"]), 1), 1.0), text=f"[{feitos}/{len(pre['reqs'])}] {(val or {}).get('atual', 'iniciando…')}")
        if val and val.get("tipo") == "fim":
            for n, dados in val["results"].items():
                lat, lon = pre["unidades"][n]
                if isinstance(dados, dict) and "hourly" in dados:
                    boletins_bo.guardar_em_cache(lat, lon, pre["dias"], dados["hourly"])
            st.session_state.pop("bol_pre", None)
            if val.get("abortado"):
                st.session_state["bol_pre_aviso"] = ("O Open-Meteo recusou o acesso a partir do SEU navegador/rede (" + val["abortado"] +
                                                      "). Se o limite diário foi atingido, tente de novo depois do reset (cerca de 21h, horário de Brasília) ou use outra rede.")
            elif val.get("erros"):
                st.session_state["bol_pre_aviso"] = f"{len(val['erros'])} unidade(s) não baixaram: " + "; ".join(f"{k}: {v}" for k, v in list(val["erros"].items())[:3])
            else:
                st.session_state.pop("bol_pre_aviso", None)
            _iniciar({n: c for n, c in pre["unidades"].items()}, pre["dias"], False)
            st.rerun()
        return

    if st.session_state.get("bol_pre_aviso"):
        st.warning(st.session_state["bol_pre_aviso"])

    if not estado: return

    if rodando:
        st.progress(min(estado["feitos"] / max(estado["total"], 1), 1.0),
                    text=f"[{estado['feitos']}/{estado['total']}] {estado['atual']}")
        if boletins_bo.STATUS_DOWNLOAD.get("msg"):
            st.warning(boletins_bo.STATUS_DOWNLOAD["msg"])
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

    _secao_whatsapp_manual(resultados, estado.get("gerado_id", estado.get("data", "")))


# Fragmento próprio: interagir com os boletins não reconstrói o mapa. Enquanto
# a geração roda, ele se atualiza sozinho a cada 2 s pra mostrar o progresso e,
# quando termina, faz um rerun completo pra parar o auto-refresh.
def _boletins_fragmento(unidades_base):
    _secao_boletins(unidades_base)
    est = st.session_state.get("boletins_estado")
    if _boletins_rodando and est is not None and not est["rodando"]:
        st.rerun()

# ======================================================================
# BOLETIM HORÁRIO (próximas 12 h, de 3 em 3 h) + lembrete no canto direito
# ======================================================================
_HTML_HOR_BOTOES = """<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:transparent;font:13px 'Segoe UI',Arial,sans-serif}
  button{cursor:pointer;border-radius:8px;border:1px solid #3a4150;background:#232834;color:#f1f1f1;padding:7px 11px;font:inherit}
  button:hover{background:#2e3544} button.p{background:#25d366;border-color:#25d366;color:#06210f;font-weight:600} button.p:hover{background:#3be07b}
</style></head><body><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="p" id="wa">🤖 Preparar no WhatsApp</button><button id="cp">📋 Copiar texto</button></div>
<script>
  var IT = __ITEM__;
  function copiar(t){ var x=document.createElement("textarea"); x.value=t; x.style.cssText="position:fixed;opacity:0"; document.body.appendChild(x); x.select();
    try{document.execCommand("copy");}catch(e){} document.body.removeChild(x); }
  document.getElementById("wa").addEventListener("click", function(){
    var b=this, rot="🤖 Preparar no WhatsApp", ok=false;
    function ack(ev){ if(ev.data && ev.data.fonte==="rio-raios-ack") ok=true; }
    window.addEventListener("message", ack);
    try{ (window.top||window.parent).postMessage({fonte:"rio-raios",tipo:"preparar",id:IT.id,estacao:IT.estacao,texto:IT.texto},"*"); }catch(e){}
    setTimeout(function(){ window.removeEventListener("message",ack);
      if(!ok){ copiar(IT.texto); b.textContent="Script não detectado - texto copiado (Ctrl+V)"; } else { b.textContent="✔ Enviado ao WhatsApp - confira lá e dê Enter"; }
      setTimeout(function(){ b.textContent=rot; },4500); },1200);
  });
  document.getElementById("cp").addEventListener("click", function(){ var b=this; copiar(IT.texto); b.textContent="✔ Copiado"; setTimeout(function(){ b.textContent="📋 Copiar texto"; },2000); });
</script></body></html>"""


def _hor_estado():
    return st.session_state.setdefault("hor", {"slots": {}, "pre": None, "ver": None, "dispensado": "", "avisado": {}})


def _hor_botoes_whatsapp(chave, nome, texto, altura=46):
    """Botões: preparar o texto no WhatsApp e copiar o texto."""
    item = {"id": f"hor{chave}{boletins_bo.slug(nome)}"[:80], "estacao": nome, "texto": texto}
    html = _HTML_HOR_BOTOES.replace("__ITEM__", json.dumps(item, ensure_ascii=False).replace("</", "<\\/"))
    components.html(html, height=altura)


def _hor_gerar_unidade(chave, nome, somente_cache):
    """Calcula o texto de UMA unidade a partir dos dados já baixados (cache) e guarda no slot."""
    hor = _hor_estado()
    slot = hor["slots"][chave]
    lat, lon = unidades_boletim[nome]
    reg = {"status": "gerando", "enviado": False}
    slot["unidades"][nome] = reg
    try:
        h_bm, h_mod = bh.baixar_unidade(lat, lon, somente_cache=somente_cache)
        d = bh.calcular(nome, h_bm, h_mod, slot["inicio"])
        agora = bh.agora_brasilia()
        reg.update(status="pronto", texto=bh.texto_whatsapp(d, agora), emitido=agora, enviado=False)
    except Exception as e:
        reg.update(status="erro", erro=str(e)[:200])


def _hor_iniciar(chave, inicio, envio, nomes):
    """Começa a gerar o boletim horário das unidades `nomes` (sem fila: só as escolhidas, 2 consultas por unidade)."""
    hor = _hor_estado()
    slot = hor["slots"].setdefault(chave, {"inicio": inicio, "envio": envio, "unidades": {}})
    for n in nomes:
        slot["unidades"][n] = {"status": "gerando", "enviado": False}
    for velha in sorted(hor["slots"])[:-4]:      # guarda só os 4 últimos horários (memória)
        hor["slots"].pop(velha, None)
    if boletins_bo.API_KEY:                      # chave paga: o servidor baixa (e gera) na hora
        for n in nomes:
            _hor_gerar_unidade(chave, n, somente_cache=False)
        return
    reqs, urls = [], {}
    for n in nomes:
        lat, lon = unidades_boletim[n]
        for tag, u in (("bm", bh.url_best_match(lat, lon)), ("mod", bh.url_modelos(lat, lon))):
            if not bh.em_cache(u):
                rid = f"{n}||{tag}"
                reqs.append({"id": rid, "url": u})
                urls[rid] = u
    if not reqs:
        for n in nomes:
            _hor_gerar_unidade(chave, n, somente_cache=True)
        return
    # sem chave: o NAVEGADOR de quem está com o app aberto baixa (o limite do Open-Meteo conta no IP dessa pessoa)
    hor["pre"] = {"id": f"{time.time():.3f}", "chave": chave, "nomes": list(nomes), "reqs": reqs, "urls": urls}


def _hor_processar_download():
    hor = _hor_estado()
    pre = hor.get("pre")
    if not pre:
        return
    val = _bo_fetch_boletins(reqs=pre["reqs"], pausa_ms=250, assinatura=pre["id"], key=f"horfetch_{pre['id']}", default=None)
    if val and val.get("tipo") == "fim":
        for rid, dados in (val.get("results") or {}).items():
            if isinstance(dados, dict) and "hourly" in dados:
                bh.guardar(pre["urls"][rid], dados)
        hor["pre"] = None
        for n in pre["nomes"]:
            _hor_gerar_unidade(pre["chave"], n, somente_cache=True)
        if val.get("abortado"):
            st.session_state["hor_aviso"] = "O Open-Meteo recusou o acesso a partir do seu navegador/rede (" + str(val["abortado"])[:140] + ")."
        else:
            st.session_state.pop("hor_aviso", None)
        _rerun_fragmento()


def _cores_painel():
    try:
        escuro = getattr(st.context.theme, "type", "light") == "dark"
    except Exception:
        escuro = False
    return ("#10151d", "#2b3444") if escuro else ("#ffffff", "#c9d1dc")


def _hor_lembrete(agora, envio, gerar_em, chave, nomes_sel):
    """Painel fixo no canto direito: lembra de enviar os boletins horários."""
    hor = _hor_estado()
    slot = hor["slots"].get(chave)
    # O lembrete só aparece a partir de 5 min antes do envio (e até 30 min depois, ou até todos serem marcados como enviados).
    if not nomes_sel or agora < gerar_em or hor.get("oculto") == chave:
        return
    fundo, borda = _cores_painel()
    st.markdown(
        "<style>.st-key-lembrete_horario{position:fixed;top:72px;right:16px;width:min(400px,92vw);max-height:78vh;overflow-y:auto;z-index:999991;"
        "background:%s;border:1px solid %s;border-radius:12px;padding:10px 12px;box-shadow:0 8px 28px rgba(0,0,0,.35);}</style>" % (fundo, borda),
        unsafe_allow_html=True)
    janela = agora >= gerar_em
    todos_env = bool(slot) and all(slot["unidades"].get(n, {}).get("enviado") for n in nomes_sel) and bool(nomes_sel)
    with st.container(key="lembrete_horario"):
        if hor.get("dispensado") == chave or todos_env:
            c1, c2 = st.columns([6, 1], vertical_alignment="center")
            if todos_env:
                c1.markdown(f"**⏰ Boletim das {envio:%H:%M}** ✅ enviado. Próximo em {bh.INTERVALO_H} h.")
            else:
                c1.markdown(f"**⏰ Boletim das {envio:%H:%M}** · lembrete fechado")
            if c2.button("✕", key="hor_remover", help="Tirar este aviso"):
                hor["oculto"] = chave
                _rerun_fragmento()
            if not todos_env and st.button("Reabrir", key="hor_reabrir"):
                hor["dispensado"] = ""
                _rerun_fragmento()
            return
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"**⏰ Hora de enviar o boletim das {envio:%H:%M}**")
        if c2.button("✕", key="hor_fechar", help="Tirar este lembrete (volta no próximo horário)"):
            hor["oculto"] = chave
            _rerun_fragmento()
        if st.session_state.get("hor_aviso"):
            st.warning(st.session_state["hor_aviso"])
        for n in nomes_sel:
            reg = (slot or {}).get("unidades", {}).get(n)
            curto = n.split(" - ")[0]
            with st.container(border=True):
                if not reg or reg["status"] == "gerando":
                    st.markdown(f"⏳ **{curto}** — gerando…")
                elif reg["status"] == "erro":
                    st.markdown(f"⚠️ **{curto}** — {reg.get('erro', 'erro')}")
                    if st.button("Tentar de novo", key=f"hor_retry_{chave}_{boletins_bo.slug(n)}"):
                        _hor_iniciar(chave, slot["inicio"], slot["envio"], [n])
                        _rerun_fragmento()
                else:
                    st.markdown(f"{'✅' if reg.get('enviado') else '🟢'} **{curto}** — pronto ({reg['emitido']:%H:%M})")
                    _hor_botoes_whatsapp(chave, n, reg["texto"])
                    _k1, _k2 = st.columns(2)
                    if _k1.button("👁 Ver texto", key=f"hor_ver_{chave}_{boletins_bo.slug(n)}"):
                        hor["ver"] = (chave, n)
                    nova = _k2.checkbox("Enviado", value=bool(reg.get("enviado")), key=f"hor_env_{chave}_{boletins_bo.slug(n)}")
                    if nova != bool(reg.get("enviado")):
                        reg["enviado"] = nova
                        _rerun_fragmento()


def _hor_secao(nomes_sel):
    hor = _hor_estado()
    st.subheader("⏰ Boletim horário")
    st.caption("Boletim clássico (dia a dia) enviado de 3 em 3 h, com destaque para vento e rajada nas próximas 12 h. Vento: ICON · Chuva: maior valor entre ICON e ECMWF · "
               "Raios: previsão heurística · Granizo: código de trovoada com granizo / instabilidade forte · Demais: best match.")
    if not nomes_sel:
        st.info("Escolha uma ou mais unidades em **Boletim horário**, na barra lateral.")
        return
    agora = bh.agora_brasilia()
    a1, a2 = st.columns([3, 2], vertical_alignment="center")
    envio, gerar_em = bh.proximo_envio(agora)
    a1.markdown(f"Próximo envio: **{envio:%H:%M}** (gera às {gerar_em:%H:%M}) · {len(nomes_sel)} unidade(s) selecionada(s)")
    if a2.button("⚡ Gerar agora (a partir desta hora)", key="hor_agora", use_container_width=True, disabled=bool(hor.get("pre"))):
        inicio = agora.replace(minute=0, second=0, microsecond=0)
        _hor_iniciar(f"agora{int(time.time())}", inicio, inicio, nomes_sel)
        _rerun_fragmento()
    opcoes = [(c, n) for c in sorted(hor["slots"], reverse=True) for n, r in hor["slots"][c]["unidades"].items() if r.get("status") == "pronto"]
    if not opcoes:
        st.caption("Nenhum boletim horário gerado ainda nesta sessão.")
        return
    ver = hor.get("ver")
    idx = opcoes.index(ver) if ver in opcoes else 0

    def _rot(o):
        sl = hor["slots"][o[0]]
        return f"{sl['inicio']:%d/%m %Hh} · {o[1]}"
    esc = st.selectbox("Boletim", opcoes, index=idx, format_func=_rot, key="hor_sel")
    hor["ver"] = esc
    reg = hor["slots"][esc[0]]["unidades"][esc[1]]
    _hor_botoes_whatsapp(esc[0] + "v", esc[1], reg["texto"])
    st.code(reg["texto"], language=None)


def _horario_fragmento():
    """Roda a cada 20 s: 5 min antes de cada horário de envio, gera o boletim das unidades escolhidas e mostra o lembrete."""
    if not st.session_state.get("hor_ativo"):
        return
    nomes_sel = [n for n in st.session_state.get("hor_unidades", []) if n in unidades_boletim]
    hor = _hor_estado()
    agora = bh.agora_brasilia()
    envio, gerar_em = bh.proximo_envio(agora)
    chave = envio.strftime("%Y%m%d%H")
    # Só gera/avisa se o app já estava aberto (com unidades escolhidas) ANTES do horário de geração: quem entra depois não recebe
    # geração automática nem lembrete daquele horário (o botão "Gerar agora" continua disponível).
    armados = hor.setdefault("armado", {})
    if nomes_sel and agora < gerar_em:
        armados[chave] = True
    armado = bool(armados.get(chave))
    if nomes_sel and armado and agora >= gerar_em and not hor.get("pre"):
        slot = hor["slots"].get(chave)
        faltam = [n for n in nomes_sel if not (slot and n in slot["unidades"])]
        if faltam:
            _hor_iniciar(chave, envio, envio, faltam)
    slot = hor["slots"].get(chave)
    if slot and nomes_sel and not hor["avisado"].get(chave) and all(slot["unidades"].get(n, {}).get("status") in ("pronto", "erro") for n in nomes_sel):
        hor["avisado"][chave] = True
        st.toast(f"⏰ Boletim horário das {envio:%H:%M} pronto — hora de enviar!", icon="⏰")
    _hor_processar_download()          # baixa pelo navegador (quando não há chave paga); gera os boletins ao terminar
    if armado:
        _hor_lembrete(agora, envio, gerar_em, chave, nomes_sel)
    _hor_secao(nomes_sel)


st.divider()
st.fragment(run_every=20)(_horario_fragmento)()
st.divider()
st.fragment(run_every=2 if _boletins_rodando else None)(_boletins_fragmento)(unidades_boletim)

# ======================================================================
# RELATÓRIOS MENSAIS (PDF)
# ======================================================================
def _rel_secao():
    with st.expander("📄 Relatórios mensais (PDF)", expanded=False):
        st.caption("Envie os arquivos do mês (o .zip com as pastas das unidades, ou os arquivos soltos: CSVs de boletins, "
                   "dados de 3 h e alertas, e as telas de previsão e de raios). O RIO reconhece cada arquivo e gera um PDF por unidade, "
                   "no mesmo layout dos relatórios anteriores.")
        envios = st.file_uploader("Arquivos do mês", accept_multiple_files=True, type=["zip", "csv", "png", "jpg", "jpeg", "webp"], key="rel_upload")
        if not envios:
            return
        modo_txt = st.radio("Quando a unidade tem só uma imagem (sem 'raio' ou 'previsão' no nome), ela é:",
                            ["Detectar sozinho", "Tela de raios", "Tela de previsão"], horizontal=True, key="rel_modo_img")
        modo = {"Detectar sozinho": "auto", "Tela de raios": "raio", "Tela de previsão": "prev"}[modo_txt]
        assinatura = (tuple((e.name, e.size) for e in envios), modo)
        if st.session_state.get("rel_assinatura") != assinatura:
            with st.spinner("Identificando os arquivos..."):
                st.session_state["rel_res"] = rm.identificar([(e.name, e.getvalue()) for e in envios], modo)
            st.session_state["rel_assinatura"] = assinatura
            st.session_state.pop("rel_saida", None)
        res = st.session_state["rel_res"]
        un = res["unidades"]
        if not un:
            st.warning("Não reconheci nenhuma unidade nesses arquivos.")
            return

        # arquivos que não souberam de qual unidade são
        if res.get("ocr_lidas"):
            st.info(f"{res['ocr_lidas']} captura(s) de tela tiveram a unidade identificada pelo título da própria tela.")
        elif any(i["tipo"] == "imagem" for i in res["sem_unidade"]) and not rm.ocr_disponivel():
            st.caption("Dica: instale o Tesseract (pacote `tesseract-ocr`) para o RIO ler o título das capturas de tela e identificar a unidade sozinho.")
        if res["sem_unidade"]:
            st.warning(f"{len(res['sem_unidade'])} arquivo(s) sem unidade reconhecida. Indique a qual unidade pertencem:")
            for i, item in enumerate(list(res["sem_unidade"])):
                c1, c2, c3 = st.columns([3, 3, 1])
                if item["tipo"] == "imagem":
                    c1.image(item["bytes"], caption=item["nome"], width=220)
                else:
                    c1.write(f"📄 {item['nome']}")
                escolha = c2.selectbox("Unidade", ["—"] + rm.UNIDADES, key=f"rel_sem_{i}_{item['nome']}", label_visibility="collapsed")
                if c3.button("Atribuir", key=f"rel_atr_{i}_{item['nome']}") and escolha != "—":
                    rm.atribuir_sem_unidade(res, i, escolha)
                    st.session_state.pop("rel_saida", None)
                    st.rerun()

        linhas = []
        for u in rm.UNIDADES:
            d = un.get(u)
            if not d:
                linhas.append({"Unidade": u, "Situação": "❌ sem arquivos", "Boletins": "—", "Dados 3 h": "—", "Alertas": "—", "Previsão": "—", "Raios": "—"})
                continue
            ok, falta, opc = rm.situacao(d)
            situ = ("❌ falta " + ", ".join(falta)) if not ok else ("✅ pronta" if not opc else "✅ pronta (sem " + ", ".join(opc) + ")")
            linhas.append({"Unidade": u, "Situação": situ,
                           "Boletins": "✔" if d["boletins"] else "—", "Dados 3 h": "✔" if d["dados"] else "—",
                           "Alertas": "✔" if d["alertas"] else ("vazio" if d["alertas_vazio"] else "nenhum"),
                           "Previsão": "✔" if d["img_prev"] else "—", "Raios": "✔" if d["img_raio"] else "—"})
        tabela = pd.DataFrame(linhas)
        prontas = [u for u in rm.UNIDADES if u in un and rm.situacao(un[u])[0]]
        st.write(f"**{len(prontas)} de {len(rm.UNIDADES)}** unidades prontas · logo {'encontrada nos arquivos' if res['logo'] else 'padrão do RIO'}")
        st.dataframe(tabela, hide_index=True, width="stretch", height=min(520, 36 + 35 * len(tabela)))
        avisos = [f"{u}: {a}" for u, d in un.items() for a in d["avisos"]]
        if avisos:
            with st.expander(f"Observações ({len(avisos)})"):
                for a in avisos:
                    st.write("• " + a)
        if res["ignorados"]:
            with st.expander(f"Arquivos ignorados ({len(res['ignorados'])})"):
                st.write("\n".join(f"- {n}" for n in res["ignorados"][:200]))

        # dados da capa
        ini, fim = res["periodo"] or (None, None)
        c1, c2 = st.columns(2)
        contratante = c1.text_input("Contratante", "Petrobrás", key="rel_contratante")
        local = c2.text_input("Local (capa)", "Macaé, RJ, Brasil", key="rel_local")
        c3, c4 = st.columns(2)
        periodo = c3.text_input("Período", rm.formatar_periodo(ini, fim) if ini else "", key=f"rel_periodo_{ini}_{fim}")
        data_cap = c4.text_input("Data da capa", rm.data_capa(fim) if fim else "", key=f"rel_datacapa_{ini}_{fim}")
        logo_up = st.file_uploader("Logo (opcional — se não enviar, uso a que veio nos arquivos ou a padrão)", type=["png", "jpg", "jpeg"], key="rel_logo")
        escolhidas = st.multiselect("Unidades a gerar", [u for u in rm.UNIDADES if u in un], default=prontas, key=f"rel_sel_{len(prontas)}")

        def _gerar(chave, troca, rotulo):
            logo = logo_up.getvalue() if logo_up else res["logo"]
            barra = st.progress(0.0, text="Gerando...")
            pdfs, erros = {}, []
            for i, u in enumerate(escolhidas):
                barra.progress(i / len(escolhidas), text=f"Gerando {u} ({i + 1}/{len(escolhidas)})")
                try:
                    pdfs[rm.nome_arquivo_pdf(u)] = rm.gerar_da_identificacao(u, un[u], logo, contratante, periodo, local, data_cap, troca)
                except Exception as e:  # noqa: BLE001
                    erros.append(f"{u}: {e}")
            barra.progress(1.0, text="Pronto")
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for nome, b in pdfs.items():
                    z.writestr(nome, b)
            st.session_state[chave] = {"pdfs": pdfs, "zip": buf.getvalue(), "erros": erros, "rotulo": rotulo}

        pode = bool(escolhidas and periodo and data_cap)
        cb1, cb2 = st.columns(2)
        if cb1.button("Gerar relatórios", type="primary", disabled=not pode, key="rel_gerar"):
            _gerar("rel_saida", None, "padrão")
        if cb2.button("Gerar versão alternativa", disabled=not pode, key="rel_gerar_alt"):
            _gerar("rel_saida_alt", rm.TROCA_ALTERNATIVA, "versão alternativa")

        for chave, sufixo in (("rel_saida", ""), ("rel_saida_alt", "_ALTERNATIVA")):
            saida = st.session_state.get(chave)
            if not saida:
                continue
            for e in saida["erros"]:
                st.error(e)
            if saida["pdfs"]:
                st.success(f"{len(saida['pdfs'])} relatório(s) gerado(s) — {saida['rotulo']}.")
                st.download_button(f"⬇️ Baixar todos (.zip) — {saida['rotulo']}", saida["zip"], file_name=f"RELATORIOS_MENSAIS{sufixo}.zip",
                                   mime="application/zip", key=f"rel_dl_zip{sufixo}")
                with st.expander(f"Baixar individualmente — {saida['rotulo']}"):
                    for nome, b in saida["pdfs"].items():
                        st.download_button(f"📄 {nome}", b, file_name=nome, mime="application/pdf", key=f"rel_dl{sufixo}_{nome}")

st.divider()
_rel_secao()

_salvar_estado()
