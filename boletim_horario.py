# -*- coding: utf-8 -*-
"""
Boletim HORÁRIO: próximas 12 horas, hora a hora, para uma unidade.

Fontes (Open-Meteo):
  * VENTO ........ ICON (icon_seamless): vento médio, direção e rajadas
  * CHUVA ........ o MAIOR valor entre ICON e ECMWF (ecmwf_ifs025), hora a hora
  * RAIOS ........ previsão heurística (CAPE / Lifted Index / CIN), a mesma do boletim diário
  * GRANIZO ...... código WMO 96/99 do best match; "possível" quando CAPE >= 2000 e LI <= -5
  * DEMAIS ....... best match (temperatura, umidade, nuvens, UV)

Cada unidade usa só 2 consultas (best match + ICON/ECMWF). Tudo em horário de Brasília.
Saídas: texto para o WhatsApp (texto_whatsapp) e imagem PNG com os gráficos (grafico_png).
"""
import io
import os
import math
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import requests

import boletins_bo

FUSO = ZoneInfo("America/Sao_Paulo")
HORAS_A_FRENTE = 12
PASSO_TEXTO = 3          # o texto do WhatsApp mostra uma linha a cada 3 h (os gráficos seguem hora a hora)
INTERVALO_H = 3                 # boletins de 3 em 3 horas, a partir das 00:00
ANTECEDENCIA_MIN = 5            # gera 5 minutos antes do horário de envio
MODELO_VENTO = "icon_seamless"
MODELO_ICON, MODELO_ECMWF = "icon_seamless", "ecmwf_ifs025"
VARS_BEST_MATCH = ["temperature_2m", "relative_humidity_2m", "cloud_cover", "uv_index", "weather_code",
                   "cape", "lifted_index", "convective_inhibition"]
VARS_MODELOS = ["precipitation", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
_CACHE = {}                      # (url) -> (instante, dados)
_CACHE_SEG = 20 * 60


# ----------------------------------------------------------------------------
# HORÁRIOS
# ----------------------------------------------------------------------------
def agora_brasilia():
    return datetime.now(FUSO).replace(tzinfo=None)


def proximo_envio(agora=None):
    """Próximo horário de envio (00, 03, 06 ... 21) estritamente depois de `agora`... ou o que ainda está na janela
    de 30 min depois do horário. Devolve (horario_de_envio, instante_de_geracao)."""
    agora = agora or agora_brasilia()
    base = agora.replace(minute=0, second=0, microsecond=0)
    base -= timedelta(hours=base.hour % INTERVALO_H)
    # candidatos: o horário atual de 3 em 3 h e o seguinte
    for k in (0, 1, 2):
        envio = base + timedelta(hours=INTERVALO_H * k)
        if agora <= envio + timedelta(minutes=30):
            return envio, envio - timedelta(minutes=ANTECEDENCIA_MIN)
    envio = base + timedelta(hours=INTERVALO_H * 3)
    return envio, envio - timedelta(minutes=ANTECEDENCIA_MIN)


# ----------------------------------------------------------------------------
# DOWNLOAD
# ----------------------------------------------------------------------------
def _params_base(lat, lon):
    return {"latitude": round(float(lat), 4), "longitude": round(float(lon), 4), "timezone": "America/Sao_Paulo",
            "forecast_days": boletins_bo.DIAS_PREVISAO, "wind_speed_unit": "kmh"}


def url_best_match(lat, lon):
    p = _params_base(lat, lon)
    p["hourly"] = ",".join(VARS_BEST_MATCH)
    return requests.Request("GET", "https://api.open-meteo.com/v1/forecast", params=p).prepare().url


def url_modelos(lat, lon):
    p = _params_base(lat, lon)
    p["hourly"] = ",".join(VARS_MODELOS)
    p["models"] = f"{MODELO_ICON},{MODELO_ECMWF}"
    return requests.Request("GET", "https://api.open-meteo.com/v1/forecast", params=p).prepare().url


def guardar(url, dados):
    _CACHE[url] = (time.time(), dados)


def em_cache(url):
    g = _CACHE.get(url)
    return bool(g and time.time() - g[0] < _CACHE_SEG)


def _baixar(url, tentativas=3, somente_cache=False):
    g = _CACHE.get(url)
    if g and time.time() - g[0] < _CACHE_SEG:
        return g[1]
    if somente_cache:
        raise RuntimeError("Os dados não foram baixados pelo navegador (veja o aviso). Tente de novo.")
    chave = getattr(boletins_bo, "API_KEY", "")
    u = url.replace("https://api.open-meteo.com", "https://customer-api.open-meteo.com") + f"&apikey={chave}" if chave else url
    ultimo = ""
    for i in range(tentativas):
        try:
            r = requests.get(u, timeout=40)
            if r.status_code == 429:
                ultimo = "Open-Meteo limitou o acesso (HTTP 429)"
                time.sleep(4 * (i + 1))
                continue
            r.raise_for_status()
            dados = r.json()
            guardar(url, dados)
            return dados
        except requests.RequestException as e:
            ultimo = f"{type(e).__name__}: {e}"
            time.sleep(2 * (i + 1))
    raise RuntimeError(ultimo or "Falha ao baixar do Open-Meteo")


def baixar_unidade(lat, lon, somente_cache=False):
    """(best_match, modelos): dicts 'hourly' do Open-Meteo (com cache). somente_cache=True nunca chama a API pelo servidor."""
    return (_baixar(url_best_match(lat, lon), somente_cache=somente_cache)["hourly"],
            _baixar(url_modelos(lat, lon), somente_cache=somente_cache)["hourly"])


# ----------------------------------------------------------------------------
# CÁLCULO
# ----------------------------------------------------------------------------
def _a(h, chave):
    v = h.get(chave)
    if v is None:
        return None
    return np.array([np.nan if x is None else x for x in v], dtype=float)


def _serie_completa(h_bm, h_mod):
    """Todas as horas baixadas (dias inteiros), com as mesmas regras de modelo do boletim horário."""
    tb, tm = list(h_bm["time"]), list(h_mod["time"])
    pos_m = {t: j for j, t in enumerate(tm)}
    comum = [(i, pos_m[t]) for i, t in enumerate(tb) if t in pos_m]
    ib, im = np.array([c[0] for c in comum]), np.array([c[1] for c in comum])
    tempo = [tb[i] for i in ib]
    n = len(tempo)

    def bm(v):
        a = _a(h_bm, v)
        return np.full(n, np.nan) if a is None else a[ib]

    def mod(v, m):
        a = _a(h_mod, f"{v}_{m}")
        return None if a is None else a[im]

    cand = [x for x in (mod("precipitation", MODELO_ICON), mod("precipitation", MODELO_ECMWF)) if x is not None]
    vento, rajada = mod("wind_speed_10m", MODELO_VENTO), mod("wind_gusts_10m", MODELO_VENTO)
    if not cand or vento is None or rajada is None:
        raise RuntimeError("Sem dados de chuva/vento (ICON/ECMWF)")
    direc = mod("wind_direction_10m", MODELO_VENTO)
    cape, li, cin = bm("cape"), bm("lifted_index"), bm("convective_inhibition")
    raios = boletins_bo.prob_raios_horaria(cape, li, cin)
    codigo = bm("weather_code")
    gran_prev = np.isin(codigo, boletins_bo.CODIGOS_GRANIZO)
    gran_poss = (np.nan_to_num(cape) >= 2000) & (np.nan_to_num(li, nan=0.0) <= -5) & (raios >= 50) & ~gran_prev
    return {"tempo": tempo, "datas": [t[:10] for t in tempo], "horas": np.array([int(t[11:13]) for t in tempo]),
            "temp": bm("temperature_2m"), "umid": bm("relative_humidity_2m"), "uv": bm("uv_index"),
            "chuva": np.nan_to_num(np.nanmax(np.vstack(cand), axis=0)), "vento": vento,
            "direc": np.full(n, np.nan) if direc is None else direc, "rajada": rajada, "raios": raios,
            "gran_prev": gran_prev, "gran_poss": gran_poss}


def calcular(nome, h_bm, h_mod, inicio, horas=HORAS_A_FRENTE):
    """Reúne as variáveis hora a hora de `inicio` até `inicio + horas` (13 pontos). `inicio`: datetime de Brasília."""
    chave_ini = inicio.strftime("%Y-%m-%dT%H:00")
    tempo_bm, tempo_mod = list(h_bm["time"]), list(h_mod["time"])
    if chave_ini not in tempo_bm or chave_ini not in tempo_mod:
        raise RuntimeError("A previsão baixada não cobre o horário " + chave_ini.replace("T", " "))
    i0, j0 = tempo_bm.index(chave_ini), tempo_mod.index(chave_ini)
    n = horas + 1
    if i0 + n > len(tempo_bm) or j0 + n > len(tempo_mod):
        raise RuntimeError("A previsão baixada não tem 12 horas à frente deste horário")
    sl_b, sl_m = slice(i0, i0 + n), slice(j0, j0 + n)
    horarios = [datetime.strptime(t, "%Y-%m-%dT%H:%M") for t in tempo_bm[sl_b]]

    def bm(v):
        a = _a(h_bm, v)
        return np.full(n, np.nan) if a is None else a[sl_b]

    def mod(v, m):
        a = _a(h_mod, f"{v}_{m}")
        return None if a is None else a[sl_m]

    ch_icon, ch_ecmwf = mod("precipitation", MODELO_ICON), mod("precipitation", MODELO_ECMWF)
    cand = [x for x in (ch_icon, ch_ecmwf) if x is not None]
    if not cand:
        raise RuntimeError("Sem dados de chuva (ICON/ECMWF)")
    chuva = np.nanmax(np.vstack(cand), axis=0)            # o MAIOR valor entre ICON e ECMWF
    vento, direc, rajada = (mod("wind_speed_10m", MODELO_VENTO), mod("wind_direction_10m", MODELO_VENTO),
                            mod("wind_gusts_10m", MODELO_VENTO))
    if vento is None or rajada is None:
        raise RuntimeError("Sem dados de vento do ICON")
    if direc is None:
        direc = np.full(n, np.nan)

    cape, li, cin = bm("cape"), bm("lifted_index"), bm("convective_inhibition")
    raios = boletins_bo.prob_raios_horaria(cape, li, cin)  # previsão heurística
    codigo = bm("weather_code")
    gran_prev = np.isin(codigo, boletins_bo.CODIGOS_GRANIZO)
    gran_poss = (np.nan_to_num(cape) >= 2000) & (np.nan_to_num(li, nan=0.0) <= -5) & (raios >= 50) & ~gran_prev
    uv = np.nan_to_num(bm("uv_index"))
    return {
        "completo": _serie_completa(h_bm, h_mod),
        "nome": nome, "inicio": horarios[0], "horarios": horarios,
        "temp": bm("temperature_2m"), "umid": bm("relative_humidity_2m"), "nuvens": bm("cloud_cover"), "uv": uv,
        "chuva": np.nan_to_num(chuva), "chuva_icon": ch_icon, "chuva_ecmwf": ch_ecmwf,
        "vento": vento, "direc": direc, "rajada": rajada, "raios": raios,
        "gran_prev": gran_prev, "gran_poss": gran_poss, "codigo": codigo,
    }


# ----------------------------------------------------------------------------
# TEXTO (WhatsApp)
# ----------------------------------------------------------------------------
def _f(v, c=0):
    return "s/d" if v is None or (isinstance(v, float) and math.isnan(v)) else (f"{v:.{c}f}".replace(".", ","))


def _dot_chuva(mm):
    return "🔴" if mm >= 20 else ("🟡" if mm >= 5 else "🟢")


def _dot_raj(kmh):
    return boletins_bo.cor(np.round(kmh), boletins_bo.LIM_RAJADA)


def _dot_raios(p):
    return "🔴" if p >= 70 else ("🟡" if p >= 40 else "🟢")


def icone_tempo(codigo, hora):
    c = None if codigo is None or (isinstance(codigo, float) and math.isnan(codigo)) else int(codigo)
    noite = hora < 6 or hora >= 18
    if c in (96, 99):
        return "⛈️"
    if c == 95:
        return "⛈️"
    if c in (80, 81, 82, 61, 63, 65, 66, 67):
        return "🌧️"
    if c in (51, 53, 55, 56, 57, 60):
        return "🌦️"
    if c in (45, 48):
        return "🌫️"
    if c == 3:
        return "☁️"
    if c == 2:
        return "☁️" if noite else "⛅"
    if c == 1:
        return "🌙" if noite else "🌤️"
    if c == 0:
        return "🌙" if noite else "☀️"
    return "🌡️"


def _hm(h):
    return f"{h.hour:02d}h"


def _dir(graus):
    """' (SE)' a partir de graus, ou '' se não houver direção."""
    if graus is None or (isinstance(graus, float) and math.isnan(graus)):
        return ""
    return f" ({boletins_bo.pontos_cardeais(graus)})"


def _faixa_horas(horarios, mascara):
    hs = [horarios[i] for i in range(len(horarios)) if mascara[i]]
    if not hs:
        return ""
    return _hm(hs[0]) if len(hs) == 1 else f"{_hm(hs[0])} a {_hm(hs[-1])}"


def _vento_medio_dir(vento, direc):
    """(velocidade média, ' DIR (graus°)') da janela; direção pela média vetorial, como no boletim diário."""
    v = float(np.nanmean(vento)) if not np.all(np.isnan(vento)) else float("nan")
    ok = ~np.isnan(vento) & ~np.isnan(direc)
    if not ok.any():
        return v, "s/d"
    dr = np.radians(direc[ok])
    um, vm = np.mean(-vento[ok] * np.sin(dr)), np.mean(-vento[ok] * np.cos(dr))
    graus = (math.degrees(math.atan2(-um, -vm)) + 360) % 360
    return v, f"{boletins_bo.pontos_cardeais(graus)} ({graus:.0f}°)"


def texto_whatsapp(d, emitido=None):
    """Boletim CLÁSSICO (mesmo formato do boletim diário, dia a dia), enviado de 3 em 3 h, com ênfase em vento e rajada:
    bloco de destaque com as próximas 12 h e, em cada dia, vento e rajadas primeiro, em negrito."""
    emitido = emitido or agora_brasilia()
    c, nome, hs = d["completo"], d["nome"], d["horarios"]
    lim_at, lim_fo = boletins_bo.LIM_RAJADA
    alerta_lim = boletins_bo.LIMITE_RAJADA_ALERTA
    fmt, cor = boletins_bo.fmt, boletins_bo.cor
    linhas = [f"_*Boletim de previsão do tempo - {nome}*_", f"🕒 Emitido às {emitido:%H:%M} (Brasília)", ""]

    # --- destaque: vento e rajada nas próximas 12 h ---
    rj, vt = d["rajada"], d["vento"]
    i_raj, i_vt = int(np.nanargmax(rj)), int(np.nanargmax(vt))
    v_med, txt_dir = _vento_medio_dir(vt, d["direc"])
    linhas += [f"💨 *Vento e rajadas - próximas {HORAS_A_FRENTE} h ({_hm(hs[0])} às {_hm(hs[-1])})*",
               f"{cor(v_med, boletins_bo.LIM_VENTO)} *Vento: média de {fmt(v_med)} km/h {txt_dir}, máximo de {fmt(np.nanmax(vt))} km/h às {_hm(hs[i_vt])}*",
               f"{cor(np.round(np.nanmax(rj)), boletins_bo.LIM_RAJADA)} *Rajadas: até {fmt(np.nanmax(rj))} km/h às {_hm(hs[i_raj])}*"]
    if (rj > alerta_lim).any():
        linhas.append(f"⚠️ Rajadas acima de {alerta_lim} km/h: {_faixa_horas(hs, rj > alerta_lim)}")
    else:
        linhas.append(f"✅ Sem rajadas acima de {alerta_lim} km/h no período")
    linhas.append("")

    # --- dias, no formato do boletim clássico ---
    hoje = emitido.strftime("%Y-%m-%d")
    dias = [x for x in dict.fromkeys(c["datas"]) if x >= hoje][:boletins_bo.DIAS_PREVISAO]
    alerta = None
    for idx, dia in enumerate(dias):
        m = np.array([x == dia for x in c["datas"]])
        hh = c["horas"][m]
        dd = datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m")
        tmax, tmin = np.nanmax(c["temp"][m]), np.nanmin(c["temp"][m])

        ch = np.nansum(c["chuva"][m])
        per_chuva = ""
        if ch >= 1:
            por_per = {p: np.nansum(c["chuva"][m][[boletins_bo.periodo_de(x) == p for x in hh]]) for p, _, _ in boletins_bo.PERIODOS}
            sel = [p for p, _, _ in boletins_bo.PERIODOS if por_per[p] >= 0.2 * ch]
            per_chuva = f" ({boletins_bo.juntar(sel)})"

        v_dia, dir_dia = _vento_medio_dir(c["vento"][m], c["direc"][m])
        raj_dia = c["rajada"][m]
        raj_max = np.nanmax(raj_dia)
        i_pico = int(np.nanargmax(raj_dia))
        per_raj = boletins_bo.FRASE_PERIODO[boletins_bo.periodo_de(int(hh[i_pico]))]
        acima = boletins_bo.periodos_em(hh[raj_dia > alerta_lim])

        rr = c["raios"][m]
        r_max = np.max(rr)
        sel_r = boletins_bo.periodos_em(hh[rr >= max(20.0, 0.75 * r_max)]) or boletins_bo.periodos_em([hh[int(np.argmax(rr))]])
        uv_max = np.nanmax(c["uv"][m]) if not np.all(np.isnan(c["uv"][m])) else np.nan
        um_med = np.nanmean(c["umid"][m])
        g_prev, g_poss = c["gran_prev"][m], c["gran_poss"][m]
        gran = []
        if g_prev.any():
            gran = [f"🧊 Granizo: previsto ({boletins_bo.juntar(boletins_bo.periodos_em(hh[g_prev]))})"]
        elif g_poss.any():
            gran = [f"🧊 Granizo: possível ({boletins_bo.juntar(boletins_bo.periodos_em(hh[g_poss]))})"]

        linhas += [f"*Dia {dd}*",
                   f"{cor(v_dia, boletins_bo.LIM_VENTO)} *Vento: {fmt(v_dia)} km/h {dir_dia}*",
                   f"{cor(np.round(raj_max), boletins_bo.LIM_RAJADA)} *Rajadas: {fmt(raj_max)} km/h ({per_raj}, pico às {int(hh[i_pico]):02d}h)*"]
        if acima:
            linhas.append(f"      ↳ acima de {alerta_lim} km/h: {boletins_bo.juntar(acima)}")
        linhas += [f"🌡️ Máxima: {fmt(tmax)}°C Mínima: {fmt(tmin)}°C",
                   f"{cor(np.round(ch), boletins_bo.LIM_CHUVA)} Chuva: {fmt(ch)} mm/dia{per_chuva}",
                   f"⚡ Probabilidade de raios: {r_max:.0f}% ({boletins_bo.juntar(sel_r, cap=True)})",
                   *gran,
                   f"{cor(np.round(um_med), boletins_bo.LIM_UMID, invertido=True)} Umidade: {fmt(um_med)}%",
                   f"{cor(np.round(uv_max), boletins_bo.LIM_UV)} Índice UV: {fmt(uv_max)}", ""]
        if idx == 0 and acima:
            txt_p = f"no período da {acima[0]}" if len(acima) == 1 else "nos períodos de " + ", ".join(acima[:-1]) + f" e {acima[-1]}"
            alerta = ("‐------‐---------------------------------\n"
                      f"⚠️ *Atenção*⚠️: *Hoje ({dd})*, há previsão de rajadas acima de {alerta_lim} km/h {txt_p} para a sua unidade. "
                      "Seguimos em monitoramento e, em caso de intensificação, avisaremos imediatamente.")
    if dias and c["gran_prev"][np.array([x == dias[0] for x in c["datas"]])].any():
        dd0 = datetime.strptime(dias[0], "%Y-%m-%d").strftime("%d/%m")
        linhas += ["‐------‐---------------------------------",
                   f"🧊 *Atenção*: *Hoje ({dd0})*, há previsão de granizo associado a tempestades para a sua unidade. "
                   "Seguimos em monitoramento e, em caso de intensificação, avisaremos imediatamente.", ""]
    if alerta:
        linhas.append(alerta)
    return "\n".join(linhas).rstrip() + "\n"


# ----------------------------------------------------------------------------
# GRÁFICO (PNG)
# ----------------------------------------------------------------------------
def _carregar_logo():
    import matplotlib.image as mpimg
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_blueocean.png")
    try:
        return mpimg.imread(caminho)
    except Exception:
        return None


def grafico_png(d, emitido=None, dpi=220, formato="png"):
    """Gráfico do boletim. formato="png" (raster, 220 dpi ≈ 2640 px de largura) ou "svg" (vetorial: não perde qualidade no zoom)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.colors import LinearSegmentedColormap

    emitido = emitido or agora_brasilia()
    hs, n = d["horarios"], len(d["horarios"])
    x = np.arange(n)
    rot = [f"{h.hour:02d}h" for h in hs]
    cores = {"tinta": "#1b2733", "cinza": "#6b7785", "grade": "#e6ebf1", "fundo": "#ffffff", "card": "#f3f6fa",
             "temp": "#e8590c", "umid": "#1c7ed6", "nuv": "#adb5bd", "vento": "#2b8a3e", "rajada": "#f08c00",
             "gran": "#0c8599"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#d5dce5", "svg.fonttype": "path"})
    W, H = 12.0, 20.3
    fig = plt.figure(figsize=(W, H), dpi=dpi, facecolor=cores["fundo"])

    def eixo(l, b, w, h, **kw):
        return fig.add_axes([l / W, b / H, w / W, h / H], **kw)

    # ----- cabeçalho -----
    ax = eixo(0, H - 1.75, W, 1.75)
    ax.axis("off")
    grad = LinearSegmentedColormap.from_list("g", ["#0b2545", "#13518f", "#2a8bc7"])
    ax.imshow(np.linspace(0, 1, 256).reshape(1, -1), extent=[0, 1, 0, 1], aspect="auto", cmap=grad, interpolation="bilinear")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.04, 0.62, "BOLETIM HORÁRIO", color="#9fd3ff", fontsize=11, fontweight="bold", va="center")
    ax.text(0.04, 0.37, d["nome"], color="white", fontsize=22, fontweight="bold", va="center")
    ax.text(0.04, 0.12, f"Próximas {HORAS_A_FRENTE} h · {hs[0]:%d/%m} {_hm(hs[0])} a {hs[-1]:%d/%m} {_hm(hs[-1])} · "
            f"emitido às {emitido:%H:%M} (horário de Brasília)", color="#d7e9fb", fontsize=10.5, va="center")

    logo = _carregar_logo()
    if logo is not None:
        lh = 1.38
        lw = lh * logo.shape[1] / logo.shape[0]
        al = eixo(W - lw - 0.45, H - 1.75 + (1.75 - lh) / 2, lw, lh)
        al.imshow(logo)
        al.axis("off")
        al.set_zorder(5)
        fig.patches.append(Rectangle(((W - lw - 0.45 - 0.12) / W, (H - 1.75 + (1.75 - lh) / 2 - 0.08) / H), (lw + 0.24) / W, (lh + 0.16) / H,
                                     transform=fig.transFigure, fc="#fdfdfd", ec="none", zorder=4))

    # ----- cartões-resumo -----
    i_ch, i_raj, i_rai = int(np.argmax(d["chuva"])), int(np.nanargmax(d["rajada"])), int(np.argmax(d["raios"]))
    gran = "Previsto" if d["gran_prev"].any() else ("Possível" if d["gran_poss"].any() else "Não")
    gran_sub = _faixa_horas(hs, d["gran_prev"] | d["gran_poss"]) or "sem indicação"
    i_vt = int(np.nanargmax(d["vento"]))
    sem = {"🟢": "#2b8a3e", "🟡": "#e8a200", "🔴": "#e03131"}
    kpis = [("RAJADA MÁX.", f"{_f(d['rajada'][i_raj])} km/h", f"às {_hm(hs[i_raj])}{_dir(d['direc'][i_raj])}", sem[_dot_raj(d["rajada"][i_raj])]),
            ("VENTO MÉDIO MÁX.", f"{_f(d['vento'][i_vt])} km/h", f"às {_hm(hs[i_vt])}{_dir(d['direc'][i_vt])}",
             sem[boletins_bo.cor(np.round(d["vento"][i_vt]), boletins_bo.LIM_VENTO)]),
            ("CHUVA", f"{_f(d['chuva'].sum(), 1)} mm", f"pico {_f(d['chuva'][i_ch], 1)} mm às {_hm(hs[i_ch])}" if d["chuva"][i_ch] >= 0.1 else "sem chuva relevante",
             "#1971c2"),
            ("RAIOS (heurística)", f"até {_f(d['raios'][i_rai])}%", f"às {_hm(hs[i_rai])}", sem[_dot_raios(d["raios"][i_rai])]),
            ("GRANIZO", gran, gran_sub, cores["gran"] if gran != "Não" else "#868e96"),
            ("TEMPERATURA", f"{_f(np.nanmin(d['temp']))}–{_f(np.nanmax(d['temp']))}°C", "mín – máx", cores["temp"])]
    ax = eixo(0.45, H - 3.15, W - 0.9, 1.2)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    larg, esp = (1 - 0.010 * 5) / 6, 0.010
    for k, (tit, val, sub, cor_) in enumerate(kpis):
        x0 = k * (larg + esp)
        ax.add_patch(Rectangle((x0, 0), larg, 1, fc=cores["card"], ec="#e1e7ee", lw=1, transform=ax.transAxes))
        ax.add_patch(Rectangle((x0, 0.93), larg, 0.07, fc=cor_, ec="none", transform=ax.transAxes))
        ax.text(x0 + larg / 2, 0.80, tit, ha="center", va="center", fontsize=6.8, color=cores["cinza"], fontweight="bold")
        ax.text(x0 + larg / 2, 0.47, val, ha="center", va="center", fontsize=13.5 if len(val) < 10 else 11.5, color=cor_, fontweight="bold")
        ax.text(x0 + larg / 2, 0.15, sub, ha="center", va="center", fontsize=7.2, color=cores["cinza"])

    # ----- painéis -----
    L, Wp = 0.95, W - 0.95 - 0.5
    alturas = [("vento", 3.1), ("temp", 1.7), ("chuva", 1.7), ("umid", 1.5), ("raios", 1.7), ("uv", 1.2)]
    topo, folga = H - 3.55, 0.78
    eixos = {}
    y = topo
    for nome_, alt in alturas:
        y -= alt + folga + (0.35 if nome_ == "vento" else 0)
        eixos[nome_] = eixo(L, y, Wp, alt)
    for nome_, a in eixos.items():
        a.set_facecolor("white")
        for s in ("top", "right", "left"):
            a.spines[s].set_visible(False)
        a.spines["bottom"].set_color("#cfd8e3")
        a.grid(axis="y", color=cores["grade"], lw=0.9)
        a.set_axisbelow(True)
        a.set_xlim(-0.6, n - 0.4)
        a.tick_params(axis="y", length=0, labelsize=8.5, colors=cores["cinza"])
        a.tick_params(axis="x", length=0, labelsize=8.5, colors=cores["cinza"])
        a.set_xticks(x)
        a.set_xticklabels(rot if nome_ in ("uv", "vento") else [""] * n)
        for i, h in enumerate(hs):                                    # faixa clara para a noite e marca de virada de dia
            if h.hour < 6 or h.hour >= 18:
                a.axvspan(i - 0.5, i + 0.5, color="#eef2f8", zorder=0, lw=0)
            if i > 0 and h.hour == 0:
                a.axvline(i - 0.5, color="#9aa7b6", lw=1, ls=(0, (4, 3)), zorder=1)
                a.text(i - 0.42, 0.97, f"{h:%d/%m}", transform=a.get_xaxis_transform(), fontsize=7.8, color="#7b8794", va="top", fontweight="bold")

    def titulo(a, txt, un="", sub=""):
        a.text(0, 1.1, txt + (f"  ({un.strip('()')})" if un else ""), transform=a.transAxes, fontsize=11.5, fontweight="bold",
               color=cores["tinta"], va="bottom")
        if sub:
            a.text(1, 1.1, sub, transform=a.transAxes, fontsize=8.6, color=cores["cinza"], va="bottom", ha="right")

    def rotular(a, xs, ys, fmt_, cor_, dy=8, minimo=None, passo=1):
        for k in range(0, len(xs), passo):
            if ys[k] is None or math.isnan(ys[k]) or (minimo is not None and ys[k] < minimo):
                continue
            a.annotate(fmt_(ys[k]), (xs[k], ys[k]), textcoords="offset points", xytext=(0, dy), ha="center", fontsize=8,
                       color=cor_, fontweight="bold")

    # 1) temperatura
    a = eixos["temp"]
    t = d["temp"]
    lo, hi = np.nanmin(t), np.nanmax(t)
    a.set_ylim(lo - max(1.5, (hi - lo) * 0.35), hi + max(1.5, (hi - lo) * 0.45))
    a.fill_between(x, t, a.get_ylim()[0], color=cores["temp"], alpha=0.10, zorder=2)
    a.plot(x, t, color=cores["temp"], lw=2.6, marker="o", ms=5.5, mfc="white", mew=2, zorder=4)
    rotular(a, x, t, lambda v: f"{v:.0f}°", cores["temp"], dy=9)
    titulo(a, "Temperatura", "(°C)")

    # 2) umidade + nebulosidade
    a = eixos["umid"]
    a.set_ylim(0, 128)
    a.set_yticks([0, 25, 50, 75, 100])
    a.fill_between(x, d["nuvens"], 0, color=cores["nuv"], alpha=0.38, zorder=2, label="Nebulosidade (%)")
    a.plot(x, d["umid"], color=cores["umid"], lw=2.5, marker="o", ms=5, mfc="white", mew=1.8, zorder=4, label="Umidade relativa (%)")
    rotular(a, x, d["umid"], lambda v: f"{v:.0f}", cores["umid"], dy=8, passo=1)
    a.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0), ncol=2, frameon=False, fontsize=8.3, handlelength=1.6)
    titulo(a, "Umidade e nebulosidade", "(%)")

    # 3) chuva
    a = eixos["chuva"]
    ch = d["chuva"]
    topo_ch = max(2.0, float(np.max(ch)) * 1.3)
    a.set_ylim(0, topo_ch)

    def cor_chuva(v):
        return "#d0ebff" if v < 0.2 else "#74c0fc" if v < 1 else "#339af0" if v < 5 else "#1864ab" if v < 20 else "#7048e8"
    a.bar(x, ch, width=0.62, color=[cor_chuva(v) for v in ch], zorder=3, edgecolor="white", lw=0.6)
    for i, v in enumerate(ch):
        if v >= 0.1:
            a.annotate(f"{v:.1f}".replace(".", ","), (i, v), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8,
                       color="#0b4a8b", fontweight="bold", zorder=6)
    titulo(a, "Precipitação", "(mm/h)", f"total {_f(ch.sum(), 1)} mm em {HORAS_A_FRENTE} h")

    # 4) vento
    a = eixos["vento"]
    vmax = max(50.0, float(np.nanmax(d["rajada"])) * 1.22)
    a.set_ylim(0, vmax)
    a.fill_between(x, d["vento"], d["rajada"], color=cores["rajada"], alpha=0.22, zorder=2, label="Rajada")
    a.plot(x, d["rajada"], color=cores["rajada"], lw=1.8, ls=(0, (4, 2)), marker="s", ms=3.6, zorder=3)
    a.plot(x, d["vento"], color=cores["vento"], lw=2.6, marker="o", ms=5, mfc="white", mew=1.8, zorder=4, label="Vento médio")
    for lim, c_, tx in ((boletins_bo.LIM_RAJADA[0], "#e8a200", "atenção"), (boletins_bo.LIM_RAJADA[1], "#e03131", "forte")):
        if lim < vmax:
            a.axhline(lim, color=c_, lw=1, ls=(0, (6, 4)), zorder=1, alpha=0.8)
            a.text(-0.55, lim, f"{lim} km/h", color=c_, fontsize=7.6, va="bottom", ha="left")
    for i in range(n):                                              # fundo colorido nas horas com rajada de atenção/forte
        if d["rajada"][i] >= boletins_bo.LIM_RAJADA[1]:
            a.axvspan(i - 0.5, i + 0.5, color="#ffc9c9", alpha=0.55, zorder=0.5, lw=0)
        elif d["rajada"][i] >= boletins_bo.LIM_RAJADA[0]:
            a.axvspan(i - 0.5, i + 0.5, color="#ffec99", alpha=0.6, zorder=0.5, lw=0)
    rotular(a, x, d["rajada"], lambda v: f"{v:.0f}", "#b45f06", dy=7, passo=1)
    rotular(a, x, d["vento"], lambda v: f"{v:.0f}", cores["vento"], dy=-14, passo=1)
    for i in range(n):
        if not math.isnan(d["direc"][i]):
            a.text(i, 0.03, boletins_bo.pontos_cardeais(d["direc"][i]), transform=a.get_xaxis_transform(), ha="center", va="bottom",
                   fontsize=7.4, color="#4b5563", fontweight="bold", zorder=6)
    for i in range(n):                                              # setas: para onde o vento sopra
        if math.isnan(d["direc"][i]):
            continue
        ang = math.radians((d["direc"][i] + 180) % 360)
        a.annotate("", xy=(i, 1.07), xycoords=a.get_xaxis_transform(), xytext=(-math.sin(ang) * 13, -math.cos(ang) * 13),
                   textcoords="offset points", arrowprops=dict(arrowstyle="-|>", color=cores["vento"], lw=1.5, mutation_scale=9, shrinkA=0, shrinkB=0),
                   annotation_clip=False)
    a.text(0, 1.2, "Vento e rajada  (km/h)", transform=a.transAxes, fontsize=13, fontweight="bold", color=cores["tinta"], va="bottom")
    a.text(1, 1.2, "verde: vento médio · laranja: rajada · seta: para onde sopra · letra: de onde vem · fundo amarelo/vermelho: rajada de atenção/forte", transform=a.transAxes,
           fontsize=7.6, color=cores["cinza"], va="bottom", ha="right")

    # 5) raios + granizo
    a = eixos["raios"]
    p = d["raios"]
    a.set_ylim(0, 122)
    a.set_yticks([0, 25, 50, 75, 100])
    for lim in (40, 70):
        a.axhline(lim, color="#c9d2dd", lw=0.9, ls=(0, (6, 4)), zorder=1)

    def cor_rai(v):
        return "#8ce99a" if v < 25 else "#ffd43b" if v < 50 else "#ffa94d" if v < 70 else "#fa5252"
    a.bar(x, p, width=0.62, color=[cor_rai(v) for v in p], zorder=3, edgecolor="white", lw=0.6)
    for i, v in enumerate(p):
        if v >= 3:
            a.annotate(f"{v:.0f}", (i, v), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, color="#5c3d00", fontweight="bold", zorder=6)
    for i in range(n):
        if d["gran_prev"][i]:
            a.scatter([i], [112], marker="D", s=70, color=cores["gran"], zorder=7)
        elif d["gran_poss"][i]:
            a.scatter([i], [112], marker="D", s=70, facecolor="white", edgecolor=cores["gran"], lw=1.8, zorder=7)
    if d["gran_prev"].any() or d["gran_poss"].any():
        a.text(1, 1.02, "◆ granizo previsto   ◇ granizo possível", transform=a.transAxes, ha="right", va="bottom", fontsize=8.4, color=cores["gran"], fontweight="bold")
    titulo(a, "Probabilidade de raios", "(%)")

    # 6) UV
    a = eixos["uv"]
    uv = d["uv"]
    a.set_ylim(0, max(8.0, float(np.max(uv)) * 1.3))

    def cor_uv(v):
        return "#8ce99a" if v < 3 else "#ffd43b" if v < 6 else "#ffa94d" if v < 8 else "#fa5252" if v < 11 else "#9c36b5"
    a.bar(x, uv, width=0.62, color=[cor_uv(v) for v in uv], zorder=3, edgecolor="white", lw=0.6)
    for i, v in enumerate(uv):
        if v >= 0.5:
            a.annotate(f"{v:.0f}", (i, v), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, color="#4a3a00", fontweight="bold", zorder=6)
    titulo(a, "Índice UV", "")

    # ----- rodapé -----
    fig.text(0.5, 0.35 / H, "Raios: previsão heurística (CAPE, Lifted Index, CIN) · Faixa azulada = noite · Fonte: Open-Meteo", ha="center", va="center", fontsize=8, color="#8793a1")
    buf = io.BytesIO()
    fig.savefig(buf, format=formato, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


LIMITE_LEGENDA = 1000   # a legenda de foto do WhatsApp tem limite (cerca de 1024 caracteres)


def dividir_texto(texto):
    """(legenda, resto). Se o texto couber na legenda da foto, vai tudo junto da imagem (um único Enter). Se não couber, a
    legenda leva o cabeçalho + resumo e o 'Hora a hora' vai como 2ª mensagem."""
    texto = texto.strip()
    if len(texto) <= LIMITE_LEGENDA:
        return texto, ""
    i = texto.find("*Hora a hora")
    if i <= 0:
        return texto[:LIMITE_LEGENDA], texto[LIMITE_LEGENDA:]
    return texto[:i].rstrip(), texto[i:].strip()
