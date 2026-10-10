#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera boletins de previsão do tempo (formato WhatsApp) para as unidades,
usando Open-Meteo com ENSEMBLE (MÉDIA CONSENSO) entre ECMWF, ICON e GFS.

Uso:
    python gerar_boletins.py                       # usa as 40 unidades embutidas em UNIDADES
    python gerar_boletins.py --csv unidades.csv    # CSV com colunas: nome,lat,lon
    python gerar_boletins.py --filtro Macaé        # só unidades cujo nome contém o texto
    python gerar_boletins.py --dias 4 --saida boletins

Dependências: pip install requests numpy
"""
import argparse
import csv
import math
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ----------------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------------
API_URL = "https://api.open-meteo.com/v1/forecast"
MODELOS = ["ecmwf_ifs025", "icon_seamless", "gfs_seamless"]
VARIAVEIS = [
    "temperature_2m", "precipitation", "relative_humidity_2m",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "uv_index", "cape", "lifted_index", "convective_inhibition",
]
DIAS_PREVISAO = 4
LIMITE_RAJADA_ALERTA = 40  # km/h, para o aviso de "Atenção"

# Faixas de cor (limites inferiores do amarelo e do vermelho) - ajuste à vontade
LIM_CHUVA = (20, 50)      # mm/dia
LIM_VENTO = (40, 60)      # km/h
LIM_RAJADA = (40, 70)     # km/h
LIM_UV = (6, 11)          # índice
LIM_UMID = (40, 20)       # %, INVERTIDO: abaixo de 40 amarelo, abaixo de 20 vermelho

# 40 unidades (nome, (lat, lon))
UNIDADES = {
    "UTE Termocamaçari - UTE TCA": (-12.666868, -38.314687),
    "UTE Termobahia - UTE TBA": (-12.703235, -38.564904),
    "UTE Termoceará - UTE TCE": (-3.692456, -38.870605),
    "UTE Vale do Açu - UTE VLA": (-5.381685, -36.819754),
    "Refinaria Abreu e Lima - RNEST": (-8.379661, -35.010198),
    "Unidade de Tratamento de Gás Sul Capixaba - UTGSUL": (-20.794464, -40.620910),
    "Unidade de Tratamento de Gás de Cacimbas - UTGC": (-19.463097, -39.760603),
    "Refinaria Duque de Caxias - REDUC": (-22.715100, -43.284008),
    "UTE Termorio - UTE TRI": (-22.714882, -43.254348),
    "BOAVENTURA, Itaboraí-RJ": (-22.660714, -42.853629),
    "Unidade de Tratamento de Gás de Cabiúnas - UTGCAB": (-22.285327, -41.717905),
    "UTE Termomacaé - UTE TMA": (-22.306164, -41.876702),
    "UTE Seropédica/Baixada Fluminense - UTE SRP/BF": (-22.723292, -43.647719),
    "Refinaria Gabriel Passos - REGAP": (-19.964281, -44.095138),
    "UTE Ibirité - UTE IBT": (-19.988579, -44.098207),
    "UTE Juiz de Fora - UTE JF": (-21.690619, -43.456720),
    "UTE Três Lagoas - UTE TLG": (-20.745500, -51.664590),
    "Unidade de Tratamento de Gás de Caraguatatuba - UTGCA": (-23.654191, -45.501209),
    "Refinaria Presidente Bernardes - RPBC": (-23.873326, -46.427572),
    "UTE Cubatão - UTE CBT": (-23.875735, -46.431387),
    "Refinaria Henrique Lage - REVAP": (-23.184796, -45.815806),
    "Refinaria de Capuava - RECAP": (-23.656681, -46.480883),
    "Refinaria de Paulínia - REPLAN": (-22.729589, -47.147712),
    "UTE Nova Piratininga - UTE NPI": (-23.699414, -46.673881),
    "Refinaria Presidente Getúlio Vargas - REPAR": (-25.566140, -49.369423),
    "Refinaria Alberto Pasqualini - REFAP": (-29.869901, -51.178195),
    "UTE Canoas - UTE CAN": (-29.875071, -51.145445),
    "Armazém Rio de Janeiro": (-22.810973, -43.281876),
    "CILEP - CENPES": (-22.854198, -43.233830),
    "Porto Baia de Guanabara": (-22.878942, -43.209330),
    "ARM Macaé - Armazém Macaé": (-22.415317, -41.861353),
    "Porto de Imbetiba - Macaé": (-22.386825, -41.768741),
    "Porto Açu": (-21.864737, -41.016444),
    "Porto Aratu": (-12.780132, -38.496764),
    "Porto TMIB": (-10.824129, -36.946301),
    "Porto Belém": (-1.439901, -48.494920),
    "Porto Valença": (-13.369369, -39.071252),
    "Porto Guamaré": (-5.106692, -36.319592),
    "Porto Mucuripe": (-3.713117, -38.474037),
    "Porto Paracuru": (-3.401146, -39.010896),
}

PERIODOS = [("madrugada", 0, 6), ("manhã", 6, 12), ("tarde", 12, 18), ("noite", 18, 24)]
FRASE_PERIODO = {"madrugada": "pela madrugada", "manhã": "pela manhã",
                 "tarde": "à tarde", "noite": "à noite"}
PONTOS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


# ----------------------------------------------------------------------------
# DOWNLOAD E CONSENSO
# ----------------------------------------------------------------------------
def baixar(lat, lon, dias=DIAS_PREVISAO, tentativas=4):
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(VARIAVEIS),
        "models": ",".join(MODELOS),
        "timezone": "auto",
        "forecast_days": dias,
        "wind_speed_unit": "kmh",
    }
    for i in range(tentativas):
        try:
            r = requests.get(API_URL, params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(10 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()["hourly"]
        except requests.RequestException as e:
            if i == tentativas - 1:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError("Falha ao baixar dados do Open-Meteo")


def _arr(v):
    return np.array([np.nan if x is None else x for x in v], dtype=float)


def consenso(hourly, var):
    """Média entre modelos (ignora modelos sem a variável)."""
    series = []
    for m in MODELOS:
        k = f"{var}_{m}"
        if k in hourly:
            series.append(_arr(hourly[k]))
    if not series and var in hourly:  # resposta de um único modelo
        series.append(_arr(hourly[var]))
    if not series:
        return np.full(len(hourly["time"]), np.nan)
    return np.nanmean(np.vstack(series), axis=0)


def consenso_direcao(hourly):
    """Direção por média vetorial entre modelos, ponderada pela velocidade."""
    u, v = [], []
    for m in MODELOS:
        kd, ks = f"wind_direction_10m_{m}", f"wind_speed_10m_{m}"
        if kd in hourly and ks in hourly:
            d, s = np.radians(_arr(hourly[kd])), _arr(hourly[ks])
            u.append(-s * np.sin(d))
            v.append(-s * np.cos(d))
    if not u:
        return np.full(len(hourly["time"]), np.nan)
    um, vm = np.nanmean(np.vstack(u), axis=0), np.nanmean(np.vstack(v), axis=0)
    return (np.degrees(np.arctan2(-um, -vm)) + 360) % 360


# ----------------------------------------------------------------------------
# PROBABILIDADE DE RAIOS (heurística simples - TROQUE PELA SUA DO RUSBÉ/PDEA)
# ----------------------------------------------------------------------------
def prob_raios_horaria(cape, li, cin):
    cape_s = np.clip(cape / 2500.0, 0, 1)
    li_s = np.clip((2.0 - li) / 8.0, 0, 1)
    base = np.where(np.isnan(li_s), cape_s, 0.6 * cape_s + 0.4 * li_s)
    pen = 1 - 0.6 * np.clip(np.abs(np.nan_to_num(cin)) / 200.0, 0, 1)
    return np.nan_to_num(100.0 * base * pen)


# ----------------------------------------------------------------------------
# FORMATAÇÃO
# ----------------------------------------------------------------------------
def cor(v, lim, invertido=False):
    if np.isnan(v):
        return "⚪"
    if invertido:
        return "🔴" if v < lim[1] else ("🟡" if v < lim[0] else "🟢")
    return "🔴" if v >= lim[1] else ("🟡" if v >= lim[0] else "🟢")


def fmt(v, casas=0):
    return "s/d" if np.isnan(v) else f"{v:.{casas}f}"


def pontos_cardeais(graus):
    return PONTOS[int((graus + 22.5) // 45) % 8]


def periodo_de(hora):
    for nome, a, b in PERIODOS:
        if a <= hora < b:
            return nome
    return "noite"


def periodos_em(horas_sel):
    ordem = [p[0] for p in PERIODOS]
    achados = {periodo_de(h) for h in horas_sel}
    return [p for p in ordem if p in achados]


def juntar(periodos, cap=False):
    txt = "/".join(periodos)
    return txt.title() if cap else txt


def boletim_unidade(nome, lat, lon, dias=DIAS_PREVISAO):
    h = baixar(lat, lon, dias)
    tempo = h["time"]
    datas = [t[:10] for t in tempo]
    horas = np.array([int(t[11:13]) for t in tempo])

    temp = consenso(h, "temperature_2m")
    chuva = consenso(h, "precipitation")
    umid = consenso(h, "relative_humidity_2m")
    vento = consenso(h, "wind_speed_10m")
    direc = consenso_direcao(h)
    rajada = consenso(h, "wind_gusts_10m")
    uv = consenso(h, "uv_index")
    raios = prob_raios_horaria(consenso(h, "cape"), consenso(h, "lifted_index"),
                               consenso(h, "convective_inhibition"))

    dias_unicos = list(dict.fromkeys(datas))[:dias]
    linhas = [f"_*Boletim de previsão do tempo - {nome}*_", ""]
    alerta = None

    for idx, d in enumerate(dias_unicos):
        m = np.array([x == d for x in datas])
        hh = horas[m]
        dd = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m")

        tmax, tmin = np.nanmax(temp[m]), np.nanmin(temp[m])

        # Chuva
        ch = np.nansum(chuva[m])
        per_chuva = ""
        if ch >= 1:
            por_per = {p: np.nansum(chuva[m][[periodo_de(x) == p for x in hh]])
                       for p, _, _ in PERIODOS}
            sel = [p for p, _, _ in PERIODOS if por_per[p] >= 0.2 * ch]
            per_chuva = f" ({juntar(sel)})"

        # Vento (média do dia; direção pela média vetorial)
        v_med = np.nanmean(vento[m])
        sp, dr = vento[m], np.radians(direc[m])
        ok = ~np.isnan(sp) & ~np.isnan(dr)
        if ok.any():
            um, vm = np.mean(-sp[ok] * np.sin(dr[ok])), np.mean(-sp[ok] * np.cos(dr[ok]))
            graus = (math.degrees(math.atan2(-um, -vm)) + 360) % 360
            txt_dir = f"{pontos_cardeais(graus)} ({graus:.0f}°)"
        else:
            txt_dir = "s/d"

        # Rajadas
        raj_dia = rajada[m]
        raj_max = np.nanmax(raj_dia)
        per_raj = FRASE_PERIODO[periodo_de(int(hh[int(np.nanargmax(raj_dia))]))]

        # Raios
        rr = raios[m]
        r_max = np.max(rr)
        corte = max(20.0, 0.75 * r_max)
        sel_r = periodos_em(hh[rr >= corte]) or periodos_em([hh[int(np.argmax(rr))]])

        # UV e umidade
        uv_max = np.nanmax(uv[m]) if not np.all(np.isnan(uv[m])) else np.nan
        um_med = np.nanmean(umid[m])

        linhas += [
            f"*Dia {dd}*",
            f"🌡️ Máxima: {fmt(tmax)}°C Mínima: {fmt(tmin)}°C",
            f"{cor(ch, LIM_CHUVA)} Chuva: {fmt(ch)} mm/dia{per_chuva}",
            f"⚡ Probabilidade de raios: {r_max:.0f}% ({juntar(sel_r, cap=True)})",
            f"{cor(v_med, LIM_VENTO)} Vento: {fmt(v_med)} km/h {txt_dir}",
            f"{cor(raj_max, LIM_RAJADA)} Rajadas: {fmt(raj_max)} km/h ({per_raj})",
            f"{cor(um_med, LIM_UMID, invertido=True)} Umidade: {fmt(um_med)}%",
            f"{cor(uv_max, LIM_UV)} Índice UV: {fmt(uv_max)}",
            "",
        ]

        # Alerta de rajadas (somente hoje)
        if idx == 0:
            fortes = periodos_em(hh[raj_dia > LIMITE_RAJADA_ALERTA])
            if fortes:
                if len(fortes) == 1:
                    txt_p = f"no período da {fortes[0]}"
                else:
                    txt_p = "nos períodos de " + ", ".join(fortes[:-1]) + f" e {fortes[-1]}"
                alerta = (
                    "‐------‐---------------------------------\n"
                    f"⚠️ *Atenção*⚠️: *Hoje ({dd})*, há previsão de rajadas acima de "
                    f"{LIMITE_RAJADA_ALERTA} km/h {txt_p} para a sua unidade. "
                    "Seguimos em monitoramento e, em caso de intensificação, "
                    "avisaremos imediatamente."
                )

    if alerta:
        linhas.append(alerta)
    return "\n".join(linhas).rstrip() + "\n"


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def carregar_unidades(caminho_csv):
    if not caminho_csv:
        return dict(UNIDADES)
    un = {}
    with open(caminho_csv, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            un[r["nome"].strip()] = (float(r["lat"]), float(r["lon"]))
    return un


def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="CSV com colunas nome,lat,lon")
    ap.add_argument("--filtro", help="Gera só unidades cujo nome contém este texto")
    ap.add_argument("--dias", type=int, default=DIAS_PREVISAO)
    ap.add_argument("--saida", default="boletins")
    # parse_known_args: funciona também dentro do Jupyter/Spyder (ignora o '-f kernel.json')
    a, _ = ap.parse_known_args(argv)

    unidades = carregar_unidades(a.csv)
    if a.filtro:
        unidades = {n: c for n, c in unidades.items() if a.filtro.lower() in n.lower()}

    pasta = Path(a.saida)
    pasta.mkdir(exist_ok=True)
    todos = []
    for i, (nome, (lat, lon)) in enumerate(unidades.items(), 1):
        try:
            txt = boletim_unidade(nome, lat, lon, a.dias)
        except Exception as e:
            print(f"[{i}/{len(unidades)}] ERRO em {nome}: {e}", file=sys.stderr)
            continue
        (pasta / f"{slug(nome)}.txt").write_text(txt, encoding="utf-8")
        todos.append(txt)
        print(f"[{i}/{len(unidades)}] {nome} ok")
        time.sleep(0.3)

    geral = pasta / f"boletins_{datetime.now():%Y%m%d}.txt"
    geral.write_text("\n\n".join(todos), encoding="utf-8")
    print(f"\nArquivo consolidado: {geral}")


if __name__ == "__main__":
    main()