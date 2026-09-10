# ======================================================================
# BLUEOCEAN — MONITOR DE RAIOS (versão web / Streamlit)
# Versão focada só em raios (GLM/GOES-19), por Mário Henrique.
# ======================================================================
import base64
import io
import math
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="BlueOcean — Monitor de Raios", layout="wide", page_icon="⚡")

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


def utc_para_brasilia(dt_utc):
    return dt_utc - timedelta(hours=3)

# ======================================================================
# CONTATOS POR UNIDADE
# ======================================================================
CONTATOS_UNIDADES = {'REGAP': {'nome': 'REGAP', 'numeros': [{'numero': '(31) 3529 4470'}, {'numero': '(31) 3529 4405'}, {'numero': '(31) 3529 4508'}]}, 'CILEP_CENPES': {'nome': 'CILEP CENPES', 'numeros': [{'numero': '(21) 9 9700 6335'}, {'numero': '(21) 9 7968 0027'}]}, 'TMIB COQUEIROS': {'nome': 'TMIB COQUEIROS', 'numeros': [{'numero': '(79) 3212 5101'}, {'numero': '(79) 9 9630 8427'}]}, 'ARM RIO': {'nome': 'ARM RIO', 'numeros': [{'numero': '(21) 9 6576-0066'}, {'numero': '(21) 9 6576-0142'}, {'numero': '(21) 9 9649 4019'}]}, 'UTE_Canoas': {'nome': 'UTE Canoas', 'numeros': [{'numero': '(51) 3415-3939'}, {'numero': '(51) 99866-6449'}]}, 'Guamaré': {'nome': 'Guamaré', 'numeros': [{'numero': '(85) 98830.3729'}, {'numero': '(84) 99984.7020'}, {'numero': '85) 99207.7804'}]}, 'REFAP': {'nome': 'REFAP', 'numeros': [{'numero': '(51) 3415-2080'}, {'numero': '(51) 99982-0520'}, {'numero': '(51) 99617-3964'}]}, 'REPAR': {'nome': 'REPAR', 'numeros': [{'numero': '(41) 3641-2987'}, {'numero': '(41) 99157-6902'}, {'numero': '(41) 99241-5443'}]}, 'UTC_Nova_Piratininga': {'nome': 'UTE Nova Piratininga', 'numeros': [{'numero': '(11) 3523-5856'}, {'numero': '(11) 3523 5876'}, {'numero': '(11) 98393-0913'}]}, 'RPBC': {'nome': 'RPBC', 'numeros': [{'numero': '(13) 3328-4074'}, {'numero': '(13) 99712-4788'}, {'numero': '(13) 3328-4253'}]}, 'RECAP': {'nome': 'RECAP', 'numeros': [{'numero': '(11) 3795-9314'}, {'numero': '(11) 96183-2809'}, {'numero': '(11) 3795-9130'}]}, 'UTG_Caraguatatuba': {'nome': 'UTGCA - Caraguatatuba', 'numeros': [{'numero': '(12) 3886-5050', 'descricao': 'Opção 1'}, {'numero': '(12) 3886-5117', 'descricao': 'Opção 2'}, {'numero': '(12) 3886-5066', 'descricao': 'Opção 3'}]}, 'REVAP': {'nome': 'REVAP', 'numeros': [{'numero': '(12) 3928-6304'}, {'numero': '(12) 3928-6499'}, {'numero': '(12) 9 9130-6608'}]}, 'REPLAN': {'nome': 'REPLAN', 'numeros': [{'numero': '(19) 2116-6892 e (19) 99772-1201', 'descricao': 'celular melhor'}, {'numero': '(19) 2116-6542 e (19) 99602-8522'}, {'numero': '(19) 2116--6183'}]}, 'UTE_Tres_lagoas': {'nome': 'UTE Três Lagoas', 'numeros': [{'numero': '(67) 3509-3275', 'descricao': 'Opção 1 - Sala de Controle'}, {'numero': '(67) 3509 - 3234', 'descricao': 'Opção 2 - Supervisor de Turno'}, {'numero': '(67) 9 - 9847 - 3567', 'descricao': 'Opção 3 - Celular da Operação'}]}, 'UTE_Seropedica': {'nome': 'UTE Seropédica', 'numeros': [{'numero': '(21) 2665-9221', 'descricao': 'supervisao op'}, {'numero': '(21) 2665-9234'}, {'numero': '(21) 98330 0979.'}]}, 'UTE_Termorio': {'nome': 'UTE Termorio', 'numeros': [{'numero': '(21) 3227-5746'}, {'numero': '(21) 98055-0569'}, {'numero': '(21) 9 6720 8088'}]}, 'REDUC': {'nome': 'REDUC', 'numeros': [{'numero': '(21) 2677-2232', 'descricao': 'Opção 1'}, {'numero': '(21) 2677-2975', 'descricao': 'Opção 2'}, {'numero': '(21) 9 - 9872 - 4188', 'descricao': 'Fernanda Neves (Gerente do Setor)'}]}, 'UTG_Itaborai': {'nome': 'UTG Itaboraí', 'numeros': [{'numero': '(21) 2133-4199', 'descricao': 'ligar neste'}, {'numero': '(21) 2133-4202'}, {'numero': '(21) 99700-6571'}]}, 'Arm Macaé': {'nome': 'Arm Macaé', 'numeros': [{'numero': '(22) 9 9824-6085'}, {'numero': '(22) 9 9940-2957'}]}, 'UTE Juiz de Fora': {'nome': 'UTE Juiz de Fora', 'numeros': [{'numero': '(32) 3239-8431', 'descricao': 'sala op'}, {'numero': '(32) 3239-8423', 'descricao': 'sala op'}, {'numero': '(32) 99804-4943'}]}, 'UTE_Termomacae': {'nome': 'UTE Termomacaé', 'numeros': [{'numero': '(22) 3379-6134'}, {'numero': '(22) 3379-6135'}, {'numero': '(22) 98817-2571'}]}, 'UTG_Cabiunas': {'nome': 'UTG Cabiunas', 'numeros': [{'numero': '(22) 9 - 9981-1678 / Ramal: 2759 - 5280', 'descricao': 'Opção 1'}, {'numero': '(22) 9 - 9778-7616 / Ramal: 2797 - 5248 / 2797 - 5249', 'descricao': 'Opção 2'}]}, 'UTE_Ibirite': {'nome': 'UTE Ibirité', 'numeros': [{'numero': '(31) 3472-2230'}, {'numero': '(31) 99704-5869'}, {'numero': '(11) 96857-9818'}]}, 'UTG Sul_Capixaba': {'nome': 'UTG Sul Capixaba', 'numeros': [{'numero': '(28) 3360-6065', 'descricao': 'CISP'}, {'numero': '(27) 99297-9464', 'descricao': 'CISP'}]}, 'UTG_Cacimbas': {'nome': 'UTG C - Cacimbas', 'numeros': [{'numero': '(27) 3048-9107 / 9903', 'descricao': 'Supervisão da Operação (K-45)'}, {'numero': '(27) 3048-9300 / 9909'}, {'numero': '(27)3048-9152', 'descricao': 'Coordenador de Turno da Operação (K-45)'}, {'numero': '(27) 3048-9131', 'descricao': 'SMS (k-32)'}, {'numero': '(27)3048-9140', 'descricao': 'Controle de CFTV - 24h (k-04)'}]}, 'RNEST': {'nome': 'RNEST', 'numeros': [{'numero': '(81) 3879 - 4530'}, {'numero': '(81) 3879 - 3220'}, {'numero': '(81) 3879 - 4525'}]}, 'UTE_Termobahia': {'nome': 'UTE Termobahia', 'numeros': [{'numero': '(71) 3348-5006', 'descricao': 'Opção 1'}, {'numero': '(71) 9 - 9988-5704', 'descricao': 'Opção 2'}, {'numero': '(71) 9 - 9918 - 3933 / 9 -9672 - 4400', 'descricao': 'Opção 3'}]}, 'Porto Belém': {'nome': 'PORTO BELÉM', 'numeros': [{'numero': '(91) 99150.0369'}, {'numero': '(79) 99163.0089'}, {'numero': '(85) 99207.7804'}]}, 'Mucuripe_Paracuru': {'nome': 'Mucuripe Paracuru', 'numeros': [{'numero': '(85) 98147.6460'}, {'numero': '(85) 98829.9818'}, {'numero': '(85) 98126.3018'}, {'numero': '85) 99207.7804'}]}, 'UTE_Vale_ACU': {'nome': 'UTE Vale do Açu', 'numeros': [{'numero': '(84) 3235-6033', 'descricao': 'Opção 1'}, {'numero': '(84) 3235-6034', 'descricao': 'Opção 2'}, {'numero': '(84)  9 9609 - 9675', 'descricao': 'Opção 3'}]}, 'UTE_Termoceara': {'nome': 'UTE Termoceara', 'numeros': [{'numero': '(85) 3411 - 4420 / 4440', 'descricao': 'Sala de Controle da Unidade'}, {'numero': '(85) 9 9957-4422', 'descricao': 'Cristiano Freire - Gerente de Operação'}, {'numero': '(85) 998490019', 'descricao': 'Thiago Gerente de SMS'}]}, 'Porto Aratu': {'nome': 'Porto Aratu', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Macaé': {'nome': 'UTE Porto Macaé', 'numeros': [{'numero': '(22) 9 8113-0416'}, {'numero': '(22) 9 8183-0096'}, {'numero': '(22) 9 9736-9161'}]}, 'Porto Valença': {'nome': 'UTE Porto VALENÇA', 'numeros': [{'numero': '(71) 9 9649 4961'}]}, 'Porto Açu': {'nome': 'UTE Porto AÇU', 'numeros': [{'numero': '(22) 9 9944 9292'}, {'numero': '(22) 9 9962 7159'}]}, 'Porto B Guanabara': {'nome': 'UTE PORTO BAIA DE  GUANABARA', 'numeros': [{'numero': '(21) 9 9519 4346'}, {'numero': '(21) 2144 0051'}, {'numero': '(21) 9 8145 4321'}]}}

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

RAIOS_ALERTA_KM = [(30, "#3b82f6"), (50, "#22c55e"), (100, "#f97316"), (200, "#ef4444")]

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

def classificar_risco_raio(dist_min_km):
    """Classifica o risco somente quando existe raio dentro de 50 km."""
    if dist_min_km is None or not np.isfinite(dist_min_km):
        return 0, "Sem raios próximos", "🟢", "#22c55e", None
    if dist_min_km <= 30:
        return 2, "Alto — raio a menos de 30 km", "🔴", "#ef4444", "vermelho"
    if dist_min_km <= 50:
        return 1, "Médio — raio a menos de 50 km", "🟡", "#eab308", "amarelo"
    return 0, "Sem raios próximos", "🟢", "#22c55e", None

def calcular_status_estacoes(df_stations, raios_df):
    """Calcula a distância geodésica real até o raio mais próximo da janela atual."""
    linhas = []
    tem_raios = raios_df is not None and not raios_df.empty
    if tem_raios:
        raio_lat = pd.to_numeric(raios_df["lat"], errors="coerce").to_numpy(dtype=float)
        raio_lon = pd.to_numeric(raios_df["lon"], errors="coerce").to_numpy(dtype=float)
        valido = np.isfinite(raio_lat) & np.isfinite(raio_lon)
        raio_lat = np.radians(raio_lat[valido])
        raio_lon = np.radians(raio_lon[valido])

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
            dist_min = float((2.0 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))).min())

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
        alvo["hull_atual"] = _hull_convexo(grupo)
        usadas.add(alvo["id"])
    celulas = [c for c in celulas if agora_ts - c["ultima_atualizacao"] <= 600]
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
    linhas.insert(-1, f"* Quem recebeu o alerta: {quem}")
    return "\n".join(linhas)

# ======================================================================
# BOLETIM EM PDF
# ======================================================================
def gerar_boletim_pdf_bytes(df_status, alertas_ativos, meteorologista_nome=""):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("T", parent=styles["Title"], textColor=colors.HexColor("#0d1117"))
    estilo_secao = ParagraphStyle("S", parent=styles["Heading2"], textColor=colors.HexColor("#0f5c5c"), spaceBefore=14, spaceAfter=6)
    estilo_normal = styles["Normal"]
    estilo_alerta = ParagraphStyle("A", parent=styles["Normal"], fontSize=9.5, backColor=colors.HexColor("#f5f5f5"), borderPadding=6, spaceAfter=8)

    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.6 * cm, bottomMargin=1.6 * cm, leftMargin=1.6 * cm, rightMargin=1.6 * cm)
    story = []
    agora_brasilia = utc_para_brasilia(datetime.now(timezone.utc))

    story.append(Paragraph(f"Boletim de Raios — {EMPRESA}", estilo_titulo))
    story.append(Paragraph(
        f"Gerado em: <b>{agora_brasilia.strftime('%d/%m/%Y %H:%M')}</b> (horário de Brasília)<br/>"
        f"Fonte: GLM / GOES-19 (raios ao vivo)<br/>"
        f"Meteorologista: <b>{meteorologista_nome or '(não informado)'}</b>",
        estilo_normal,
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Unidades em alerta agora", estilo_secao))
    em_risco = df_status[df_status["risco_score"] > 0].sort_values(["risco_score", "dist_min_km"], ascending=[False, True])
    if not em_risco.empty:
        linhas = [["Nível", "Unidade", "Distância do raio mais próximo"]]
        for _, e in em_risco.iterrows():
            linhas.append([e["risco_label"].split(" — ")[0].upper(), e["nome"], f"{e['dist_min_km']:.0f} km"])
        t = Table(linhas, colWidths=[2.6 * cm, 9 * cm, 6 * cm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ef4444")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccc")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")])]))
        story.append(t)
    else:
        story.append(Paragraph("Nenhuma unidade em alerta amarelo/vermelho no momento.", estilo_normal))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Alertas ativos (mensagens geradas)", estilo_secao))
    emoji_pat = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\uFE0F\u200d]+")
    if alertas_ativos:
        for a in alertas_ativos:
            story.append(Paragraph(emoji_pat.sub("", montar_texto_copia(a)).strip(), estilo_alerta))
    else:
        story.append(Paragraph("Nenhum alerta ativo.", estilo_normal))
    doc.build(story)
    return buf.getvalue()

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
.bo-header h1 { margin: 0; font-size: 1.5rem; color: #eaf6f6; }
.bo-header p { margin: 2px 0 0; color: #8b93a3; font-size: 0.85rem; }
.bo-pill { display: inline-block; padding: 6px 16px; border-radius: 999px; font-weight: 600; font-size: 0.85rem; white-space: nowrap; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px !important; }
.stButton>button[kind="primary"] { background-color: #3fc2c2; border-color: #3fc2c2; }
</style>
""", unsafe_allow_html=True)

if "alertas_raio_ativos" not in st.session_state: st.session_state.alertas_raio_ativos = []
if "alertas_unidade" not in st.session_state: st.session_state.alertas_unidade = {}

with st.sidebar:
    st.header("⚙ Configuração")
    meteorologista = st.text_input("Meteorologista responsável", value="")

    st.subheader("📁 Unidades monitoradas")
    df_stations = pd.DataFrame(ESTACOES_PADRAO)
    st.caption(f"{len(df_stations)} unidades já cadastradas no app.")
    with st.expander("Usar outra planilha (opcional)"):
        arquivo_estacoes = st.file_uploader("Envie um .xlsx (colunas: estacao, lat, lon)", type=["xlsx"])
        if arquivo_estacoes is not None:
            df_custom = pd.read_excel(arquivo_estacoes)
            if df_custom.shape[1] != 3: st.error(f"Esperava 3 colunas (estação/lat/lon), encontrei {df_custom.shape[1]}.")
            else:
                df_custom.columns = ["estacao", "lat", "lon"]
                df_stations = df_custom
                st.success(f"Usando {len(df_stations)} estações da planilha enviada.")

    st.subheader("⚡ Raios ao vivo (GLM/GOES-19)")
    raios_minutos = st.slider("Janela de tempo (min)", 5, 60, 15, step=5)
    intervalo_raios_seg = 120
    st.caption("🔄 Atualização automática: a cada 2 minutos")
    st.caption("🔊 O som e o pop-up automático de alerta ficam sempre ativos.")
    arquivo_som = st.file_uploader("Trocar o som de alerta (opcional)", type=["mp3", "wav", "ogg", "m4a"])
    mostrar_deslocamento = st.checkbox("Mostrar deslocamento das células de tempestade", value=True)
    st.caption("🔄 Só os raios (pontos, células e alertas) atualizam sozinhos — o mapa em si (zoom, posição, pop-ups abertos) não é recarregado.")

    st.subheader("📏 Anéis de distância no mapa")
    mostrar_aneis = st.checkbox("Mostrar anéis de distância ao redor das unidades", value=True)
    distancias_aneis = st.multiselect("Distâncias (km)", [30, 50, 100, 200], default=[30, 50, 100, 200], disabled=not mostrar_aneis)

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
  <div>
    <h1>⚡ BlueOcean — Monitor de Raios</h1>
    <p>Monitoramento de raios em tempo real (GLM/GOES-19) — by Mário Henrique</p>
  </div>
  {pill_html}
</div>
""", unsafe_allow_html=True)

col_mapa, col_lado = st.columns([2.4, 1])

@st.dialog("⚡ Raio próximo de unidade(s)!")
def _dialog_alerta_raio():
    texto = st.session_state.get("dialog_raio_texto")
    if not texto: return
    n_unidades = texto.count("* Local:")
    if n_unidades > 1:
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
        for _, r in raios_df.iterrows():
            idade_min = max((agora - r["time"]).total_seconds() / 60, 0) if pd.notna(r["time"]) else 0
            raios_out.append({
                "lat": float(r["lat"]), "lon": float(r["lon"]),
                "idade_min": round(idade_min, 1),
                "hora": utc_para_brasilia(r["time"]).strftime("%H:%M:%S") if pd.notna(r["time"]) else "?",
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
            "hull": cel.get("hull_atual", []),
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

    if mostrar_deslocamento and not raios_df.empty:
        grupos = clusterizar_raios(raios_df)
        agora_ts = time.time()
        celulas = atualizar_celulas_raio(grupos, agora_ts)
        for cel in celulas:
            traj = calcular_trajetoria_celula(cel)
            if traj is not None: celulas_com_trajetoria.append({**cel, "trajetoria": traj})

    df_status = calcular_status_estacoes(df_stations, raios_df)
    st.session_state["_fragment_df_status"] = df_status

    estacoes_novas = []
    if not raios_df.empty:
        notificacoes_desta_rodada = []
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

        if notificacoes_desta_rodada:
            separador = "\n\n" + ("─" * 30) + "\n\n"
            st.session_state.dialog_raio_texto = separador.join(notificacoes_desta_rodada)
            st.session_state.dialog_raio_ts = time.time()

    st.session_state.alertas_raio_ativos = [a for a in st.session_state.alertas_raio_ativos if a["expira"] > time.time()]

    dialog_ts = st.session_state.get("dialog_raio_ts")
    janela_dialog_seg = max(intervalo_raios_seg * 1.5, 20)
    if dialog_ts and (time.time() - dialog_ts) < janela_dialog_seg and st.session_state.get("dialog_raio_texto"):
        _dialog_alerta_raio()

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

    _construir_mapa(df_status, raios_df, celulas_com_trajetoria, estacoes_novas, status_texto)

def _construir_mapa(df_status, raios_df, celulas_com_trajetoria, estacoes_novas, status_texto):
    estacoes_payload = [
        {
            "nome": e["nome"], "estacao": e["estacao"], "lat": e["lat"], "lon": e["lon"],
            "risco_emoji": e["risco_emoji"], "risco_label": e["risco_label"], "risco_color": e["risco_color"],
            "dist_min_km": e["dist_min_km"], "contatos": e["contatos"],
        }
        for _, e in df_status.iterrows()
    ]
    aneis_payload = [{"km": km, "cor": cor} for km, cor in RAIOS_ALERTA_KM if mostrar_aneis and km in distancias_aneis]
    raios_payload = _preparar_payload_raios(raios_df, celulas_com_trajetoria)

    _mapa_raios_component(
        estacoes=estacoes_payload,
        raios=raios_payload["raios"],
        celulas=raios_payload["celulas"],
        aneis=aneis_payload,
        janela_min=raios_minutos,
        mostrar_deslocamento=bool(mostrar_deslocamento),
        status_texto=status_texto,
        estacoes_novas=estacoes_novas,
        tocar_som=bool(estacoes_novas),
        som_data_uri=som_data_uri,
        key="bo_mapa_raios_live",
    )

with col_mapa:
    st.fragment(run_every=intervalo_raios_seg)(_renderizar_mapa_ao_vivo)()

with col_lado:
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
                                st.markdown(f"{e['risco_emoji']} **{e['nome']}** — <span style='color:{e['risco_color']}'>{e['risco_label']}</span>", unsafe_allow_html=True)
                                if e["contatos"]:
                                    numeros = ", ".join(n["numero"] for n in e["contatos"]["numeros"][:2])
                                    st.caption(f"📞 {numeros}")

            with tab_alertas:
                if not st.session_state.alertas_raio_ativos:
                    st.success("Nenhum alerta de raio próximo ativo.")
                else:
                    if st.button("🗑️ Limpar todos os alertas", key="limpar_todos_alertas", use_container_width=True):
                        st.session_state.alertas_raio_ativos = []
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
                                    st.rerun(scope="fragment")

        st.fragment(run_every=intervalo_raios_seg)(_corpo_painel_lateral)()

st.divider()
col_pdf, _ = st.columns([1, 3])
with col_pdf:
    df_status_pdf = st.session_state.get("_fragment_df_status", pd.DataFrame())
    if df_status_pdf.empty:
        df_status_pdf = calcular_status_estacoes(df_stations, pd.DataFrame())
    pdf_bytes = gerar_boletim_pdf_bytes(df_status_pdf, st.session_state.alertas_raio_ativos, meteorologista_nome=meteorologista)
    agora_arquivo = utc_para_brasilia(datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M")
    st.download_button("📄 Baixar boletim de raios em PDF", data=pdf_bytes, file_name=f"boletim_raios_{agora_arquivo}.pdf", mime="application/pdf", use_container_width=True)
