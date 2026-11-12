# ======================================================================
# MAPAS DE PREVISÃO (Brasil) — Open-Meteo + interpolação RBF
# Módulo ACRESCENTADO ao RIO: o streamlit_app.py só importa este arquivo e
# chama previsao_mapas.renderizar() no fim da página; nada do restante do
# app foi alterado.
#
# - Variáveis diárias: precipitação acumulada, rajada máxima (10 m),
#   temperatura máxima e mínima (2 m), 7 dias a partir de hoje (Brasília).
# - A coleta no Open-Meteo roda numa thread em segundo plano (mesmo padrão
#   dos boletins): não trava o mapa de raios nem é interrompida por ele.
# - Os dados ficam em cache no servidor por 3 h e são compartilhados entre
#   as sessões (quem abrir depois já vê os mapas, sem nova coleta).
# - Os mapas usam só matplotlib + scipy + shapely, com o contorno do Brasil
#   em data/brasil_mapa.json (Natural Earth, simplificado): sem cartopy e
#   sem download de shapefiles em tempo de execução.
# - scipy/matplotlib são importados só quando os mapas são gerados, então
#   o app de raios abre exatamente como antes.
# ======================================================================
import io
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------
URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TZ_OPEN_METEO = "America/Sao_Paulo"
N_DIAS = 7                      # 7 dias a partir de hoje (forecast_days inclui o dia atual)
EXTENSAO = [-74.5, -33.5, -34.5, 5.8]   # [lon_min, lon_max, lat_min, lat_max]
BUFFER_PONTOS_GRAUS = 1.5       # pontos de consulta além da fronteira (evita efeito de borda da RBF)
BUFFER_MASCARA_GRAUS = 0.3      # a RBF é avaliada um pouco além da fronteira e o desenho é recortado nela
TAMANHO_LOTE = 50               # coordenadas por requisição
PAUSA_LOTES_S = 1.0
TTL_S = 3 * 3600                # cache da previsão
DAILY_VARS = ["precipitation_sum", "wind_gusts_10m_max", "temperature_2m_max", "temperature_2m_min"]

DIAS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
DIAS_COMPLETO = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

# Cores do tema do RIO (as mesmas do cabeçalho e da barra lateral do app)
FUNDO_CARD = "#0c151f"
BORDA = "#1f2d3a"
TEXTO = "#eaf6f6"
TEXTO_SUAVE = "#9db4c0"
TEXTO_MUDO = "#8b93a3"
ACENTO = "#3fc2c2"
OCEANO = "#0a121b"
TERRA_VIZINHOS = "#161f2b"
TERRA_BRASIL = "#121b27"
BORDA_VIZINHOS = "#2a3645"

VARIAVEIS = {
    "precipitation_sum": dict(
        rotulo="🌧️ Precipitação", titulo="Precipitação acumulada diária", unidade="mm",
        niveis=[0, 1, 2, 5, 10, 15, 20, 30, 50, 75, 100, 150, 200],
        cores=["#101b27", "#c7e9ff", "#8fd0ff", "#4da6ff", "#1f78e8", "#1b9e4b",
               "#7ccf3a", "#ffe34d", "#ffa631", "#f4511e", "#c2185b", "#7b1fa2"],
        acima="#f06bff", abaixo=None, sqrt=True,
        limiar=(">=", 1, "Área com chuva ≥ 1 mm"),
    ),
    "wind_gusts_10m_max": dict(
        rotulo="💨 Rajadas de vento", titulo="Rajada máxima de vento (10 m)", unidade="km/h",
        niveis=[0, 10, 20, 30, 40, 50, 60, 70, 80, 100],
        cores=["#10222d", "#16414a", "#1f6f73", "#2a9d8f", "#7ccf3a",
               "#ffe34d", "#ffa631", "#f4511e", "#c2185b"],
        acima="#f06bff", abaixo=None, sqrt=False,
        limiar=(">=", 50, "Área com rajadas ≥ 50 km/h"),
    ),
    "temperature_2m_max": dict(
        rotulo="🌡️ Temperatura máxima", titulo="Temperatura máxima (2 m)", unidade="°C",
        niveis=list(range(10, 44, 2)),
        cores=['#4d65ad', '#3387bc', '#52abae', '#76c8a5', '#a2d9a4', '#c6e89f', '#e8f69b', '#f8fcb4',
               '#fff6b0', '#fee28f', '#fdc574', '#fca55d', '#f67c4a', '#e85b48', '#d43d4f', '#b41947'],
        acima="#9e0142", abaixo="#5e4fa2", sqrt=False,
        limiar=(">=", 35, "Área com Tmax ≥ 35 °C"),
    ),
    "temperature_2m_min": dict(
        rotulo="🥶 Temperatura mínima", titulo="Temperatura mínima (2 m)", unidade="°C",
        niveis=list(range(0, 30, 2)),
        cores=['#4d65ad', '#378ebb', '#5cb7aa', '#89d0a4', '#b8e2a1', '#e1f399', '#f6fbb0',
               '#fff3ac', '#fedc88', '#fdb96a', '#f98e52', '#ee6445', '#d8434e', '#b41947'],
        acima="#9e0142", abaixo="#5e4fa2", sqrt=False,
        limiar=("<=", 15, "Área com Tmin ≤ 15 °C"),
    ),
}

VISOES = ["🗺️ Mapa do dia", "📅 7 dias", "📥 Dados"]

_CSS = """
<style>
.st-key-pv_secao .pv-card { background: linear-gradient(120deg, #101f2b 0%, #0c151f 100%);
    border: 1px solid #1f2d3a; border-left: 4px solid var(--pv-acento, #3fc2c2);
    border-radius: 14px; padding: 12px 16px; margin-bottom: 8px; }
.st-key-pv_secao .pv-label { color: #8b93a3; font-size: 0.8rem; line-height: 1.3; }
.st-key-pv_secao .pv-valor { color: #eaf6f6; font-size: 1.6rem; font-weight: 700; line-height: 1.25; }
.st-key-pv_secao [data-testid="stImage"] img { border-radius: 12px; border: 1px solid #1f2d3a; }
@media (max-width: 640px) {
  .st-key-pv_secao .pv-card { padding: 8px 12px; border-radius: 12px; }
  .st-key-pv_secao .pv-valor { font-size: 1.25rem; }
}
</style>
"""


# ----------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------
def _agora_brasilia():
    return datetime.now(timezone.utc) - timedelta(hours=3)


@st.cache_resource
def _armazem():
    """Estado compartilhado entre as sessões: previsões coletadas e coletas em andamento."""
    return {"lock": threading.Lock(), "dados": {}, "rodando": {}}


@st.cache_resource(show_spinner=False)
def _geo():
    from shapely.geometry import shape
    with open(os.path.join(APP_DIR, "data", "brasil_mapa.json"), encoding="utf-8") as f:
        d = json.load(f)
    brasil = shape(d["brasil"])
    return {
        "brasil": brasil,
        "brasil_pontos": brasil.buffer(BUFFER_PONTOS_GRAUS),
        "brasil_mascara": brasil.buffer(BUFFER_MASCARA_GRAUS),
        "vizinhos": [shape(v["geom"]) for v in d["vizinhos"]],
        "ufs": [shape(u["geom"]) for u in d["ufs"]],
    }


def _poligonos(geom):
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in geom.geoms for p in _poligonos(g)]
    return []


def _path_de_geom(geom):
    from matplotlib.path import Path
    verts, codes = [], []
    for p in _poligonos(geom):
        for anel in [p.exterior, *p.interiors]:
            xy = np.asarray(anel.coords)
            verts.extend(xy)
            codes.extend([Path.MOVETO] + [Path.LINETO] * (len(xy) - 2) + [Path.CLOSEPOLY])
    return Path(np.array(verts), codes)


@st.cache_resource(show_spinner=False)
def _caminhos():
    g = _geo()
    return {
        "brasil": _path_de_geom(g["brasil"]),
        "vizinhos": [_path_de_geom(v) for v in g["vizinhos"]],
        "ufs": [_path_de_geom(u) for u in g["ufs"]],
    }


def _pontos_consulta(passo):
    import shapely
    lons = np.arange(EXTENSAO[0], EXTENSAO[1] + 1e-6, passo)
    lats = np.arange(EXTENSAO[2], EXTENSAO[3] + 1e-6, passo)
    glon, glat = np.meshgrid(lons, lats)
    glon, glat = glon.ravel(), glat.ravel()
    dentro = shapely.contains_xy(_geo()["brasil_pontos"], glon, glat)
    return glon[dentro], glat[dentro]


# ----------------------------------------------------------------------
# COLETA (Open-Meteo) — thread em segundo plano
# ----------------------------------------------------------------------
def _sessao_http():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _baixar_lote(sessao, lats, lons):
    params = {
        "latitude": ",".join(f"{v:.3f}" for v in lats),
        "longitude": ",".join(f"{v:.3f}" for v in lons),
        "daily": ",".join(DAILY_VARS),
        "timezone": TZ_OPEN_METEO,
        "forecast_days": N_DIAS,
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "temperature_unit": "celsius",
    }
    r = sessao.get(URL_OPEN_METEO, params=params, timeout=90)
    if r.status_code >= 400:
        raise RuntimeError(f"Open-Meteo respondeu HTTP {r.status_code}: {r.text[:160]}")
    dados = r.json()
    lista = dados if isinstance(dados, list) else [dados]
    if len(lista) != len(lats):
        raise RuntimeError("Open-Meteo devolveu um número de pontos diferente do pedido.")
    return lista


def _worker_coleta(estado, armazem, passo, lon, lat):
    """Roda em thread: baixa a previsão e guarda no armazém compartilhado. Não usa st.*."""
    try:
        sessao = _sessao_http()
        resultados = []
        n = len(lon)
        for i in range(0, n, TAMANHO_LOTE):
            sl = slice(i, i + TAMANHO_LOTE)
            resultados.extend(_baixar_lote(sessao, lat[sl], lon[sl]))
            estado["feitos"] = min(i + TAMANHO_LOTE, n)
            time.sleep(PAUSA_LOTES_S)
        datas = resultados[0]["daily"]["time"]
        dados = {v: np.array([r["daily"][v] for r in resultados], dtype=float) for v in DAILY_VARS}
        with armazem["lock"]:
            armazem["dados"][passo] = {
                "datas": datas, "lon": lon, "lat": lat, "dados": dados, "ts": time.time(),
                "atualizado": _agora_brasilia().strftime("%d/%m/%Y %H:%M"),
            }
    except Exception as e:
        estado["erro"] = f"{type(e).__name__}: {e}"
    finally:
        estado["rodando"] = False
        with armazem["lock"]:
            if armazem["rodando"].get(passo) is estado:
                armazem["rodando"].pop(passo, None)


def _entrada(passo):
    """Previsão em cache, se ainda valer: até 3 h de idade e começando em HOJE (Brasília)."""
    e = _armazem()["dados"].get(passo)
    if not e or time.time() - e["ts"] > TTL_S:
        return None
    if e["datas"][0] != _agora_brasilia().date().isoformat():
        return None
    return e


# ----------------------------------------------------------------------
# INTERPOLAÇÃO RBF
# ----------------------------------------------------------------------
@st.cache_data(show_spinner="Interpolando (RBF)…", max_entries=8, ttl=TTL_S)
def _campos(var, passo, versao, suavizacao, vizinhos, passo_grade):
    """Retorna (campos[7, ny, nx], lons, lats, máscara do Brasil). `versao` invalida o cache a cada coleta."""
    import shapely
    from scipy.interpolate import RBFInterpolator

    e = _armazem()["dados"][passo]
    geo = _geo()
    cfg = VARIAVEIS[var]
    gx1 = np.arange(EXTENSAO[0], EXTENSAO[1] + 1e-6, passo_grade)
    gy1 = np.arange(EXTENSAO[2], EXTENSAO[3] + 1e-6, passo_grade)
    gx, gy = np.meshgrid(gx1, gy1)
    mascara_calc = shapely.contains_xy(geo["brasil_mascara"], gx, gy)
    mascara_br = shapely.contains_xy(geo["brasil"], gx, gy)

    campos = []
    for d in range(N_DIAS):
        v = e["dados"][var][:, d]
        ok = np.isfinite(v)
        pts = np.column_stack([e["lon"][ok], e["lat"][ok]])
        vals = v[ok]
        vmin, vmax = vals.min(), vals.max()
        if cfg["sqrt"]:                      # interpola sqrt(P): sem chuva negativa
            vals = np.sqrt(np.clip(vals, 0, None))
        rbf = RBFInterpolator(pts, vals, kernel="thin_plate_spline",
                              smoothing=suavizacao, neighbors=int(vizinhos))
        z = rbf(np.column_stack([gx[mascara_calc], gy[mascara_calc]]))
        if cfg["sqrt"]:
            z = np.clip(z, 0, None) ** 2
        z = np.clip(z, vmin, vmax)           # evita overshoot da RBF
        out = np.full(gx.shape, np.nan)
        out[mascara_calc] = z
        campos.append(out)
    return np.array(campos), gx1, gy1, mascara_br


def _estatisticas(campo, lats, mascara_br, var):
    """(máx, média ponderada por cos(lat), mín, % da área que atende ao limiar) dentro do Brasil."""
    c = np.where(mascara_br, campo, np.nan)
    valido = np.isfinite(c)
    w = np.cos(np.radians(lats))[:, None] * valido
    media = float(np.sum(np.where(valido, c, 0) * w) / w.sum())
    op, limiar, _ = VARIAVEIS[var]["limiar"]
    with np.errstate(invalid="ignore"):
        cond = (c >= limiar) if op == ">=" else (c <= limiar)
    area = float(np.sum(w * (cond & valido)) / w.sum() * 100)
    return float(np.nanmax(c)), media, float(np.nanmin(c)), area


# ----------------------------------------------------------------------
# FIGURAS (matplotlib, tema escuro do RIO) — PNG em cache
# ----------------------------------------------------------------------
def _cmap_norm(cfg):
    from matplotlib.colors import BoundaryNorm, ListedColormap
    cmap = ListedColormap(cfg["cores"]).with_extremes(over=cfg["acima"], under=cfg["abaixo"])
    return cmap, BoundaryNorm(cfg["niveis"], cmap.N)


def _fmt_lon(v):
    return f"{abs(int(v))}°O"


def _fmt_lat(v):
    return "0°" if v == 0 else f"{abs(int(v))}°{'N' if v > 0 else 'S'}"


def _desenhar_mapa(ax, gx1, gy1, campo, cfg, rotulos_eixos=True):
    from matplotlib.patches import PathPatch
    cam = _caminhos()
    cmap, norm = _cmap_norm(cfg)

    ax.set_facecolor(OCEANO)
    ax.set_xlim(EXTENSAO[0], EXTENSAO[1])
    ax.set_ylim(EXTENSAO[2], EXTENSAO[3])
    ax.set_aspect(1 / np.cos(np.radians(-15)))
    for p in cam["vizinhos"]:
        ax.add_patch(PathPatch(p, fc=TERRA_VIZINHOS, ec=BORDA_VIZINHOS, lw=0.5, zorder=1))
    ax.add_patch(PathPatch(cam["brasil"], fc=TERRA_BRASIL, ec="none", zorder=1.5))

    if cfg["abaixo"] is None:       # precipitação/rajada: o zero exato deve cair na 1ª faixa
        campo = np.clip(campo, cfg["niveis"][0] + 1e-6, None)
    dados = np.ma.masked_invalid(campo)
    cf = ax.contourf(gx1, gy1, dados, levels=cfg["niveis"], cmap=cmap, norm=norm,
                     extend="max" if cfg["abaixo"] is None else "both", zorder=2)
    recorte = PathPatch(cam["brasil"], transform=ax.transData, fc="none", ec="none")
    ax.add_patch(recorte)
    cf.set_clip_path(recorte)

    for p in cam["ufs"]:
        ax.add_patch(PathPatch(p, fc="none", ec="#9db4c0", lw=0.35, alpha=0.55, zorder=3))
    ax.add_patch(PathPatch(cam["brasil"], fc="none", ec="#dbe7ee", lw=0.9, zorder=4))

    ax.grid(True, color="#1b2735", lw=0.5)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_color(BORDA)
    if rotulos_eixos:
        xt = [-70, -60, -50, -40]
        yt = [-30, -20, -10, 0]
        ax.set_xticks(xt)
        ax.set_xticklabels([_fmt_lon(v) for v in xt])
        ax.set_yticks(yt)
        ax.set_yticklabels([_fmt_lat(v) for v in yt])
        ax.tick_params(colors=TEXTO_MUDO, labelsize=8, length=0)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    return cf


def _estilo_colorbar(cb, cfg, rotulo):
    cb.set_label(rotulo, color=TEXTO_SUAVE, fontsize=10)
    cb.ax.tick_params(colors=TEXTO_MUDO, labelsize=8)
    cb.outline.set_edgecolor(BORDA)


def _rotulo_dia(d, i):
    return f"Hoje {d:%d/%m}" if i == 0 else f"{DIAS_PT[d.weekday()]} {d:%d/%m}"


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=FUNDO_CARD)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=24, ttl=TTL_S)
def _png_dia(var, dia, passo, versao, suavizacao, vizinhos, passo_grade):
    from matplotlib.figure import Figure
    e = _armazem()["dados"][passo]
    campos, gx1, gy1, _ = _campos(var, passo, versao, suavizacao, vizinhos, passo_grade)
    cfg = VARIAVEIS[var]
    d = date.fromisoformat(e["datas"][dia])

    fig = Figure(figsize=(8.2, 7.9), dpi=130, facecolor=FUNDO_CARD)
    ax = fig.add_subplot(111)
    cf = _desenhar_mapa(ax, gx1, gy1, campos[dia], cfg)
    cb = fig.colorbar(cf, ax=ax, orientation="vertical", shrink=0.8, pad=0.02, ticks=cfg["niveis"])
    _estilo_colorbar(cb, cfg, cfg["unidade"])
    ax.set_title(f'{cfg["titulo"]}\n{DIAS_COMPLETO[d.weekday()]}, {d:%d/%m/%Y}',
                 color=TEXTO, fontsize=12.5, fontweight="bold", loc="left")
    fig.subplots_adjust(left=0.07, right=0.97, top=0.9, bottom=0.06)
    return _png(fig)


@st.cache_data(show_spinner="Montando os 7 mapas…", max_entries=8, ttl=TTL_S)
def _png_semana(var, passo, versao, suavizacao, vizinhos, passo_grade):
    from matplotlib.figure import Figure
    e = _armazem()["dados"][passo]
    campos, gx1, gy1, _ = _campos(var, passo, versao, suavizacao, vizinhos, passo_grade)
    cfg = VARIAVEIS[var]

    fig = Figure(figsize=(17, 9.4), dpi=110, facecolor=FUNDO_CARD)
    axes = fig.subplots(2, 4).ravel()
    cf = None
    for d in range(N_DIAS):
        cf = _desenhar_mapa(axes[d], gx1, gy1, campos[d], cfg, rotulos_eixos=False)
        dia = date.fromisoformat(e["datas"][d])
        axes[d].set_title(_rotulo_dia(dia, d), color=TEXTO, fontsize=12, fontweight="bold")
    axes[-1].set_visible(False)
    cb = fig.colorbar(cf, ax=list(axes), orientation="horizontal", fraction=0.04, pad=0.05,
                      aspect=60, ticks=cfg["niveis"])
    _estilo_colorbar(cb, cfg, f'{cfg["titulo"]} ({cfg["unidade"]})')
    fig.suptitle(f'{cfg["titulo"]} — previsão de {N_DIAS} dias · Open-Meteo, interpolação RBF · '
                 f'coletado em {e["atualizado"]} (Brasília)', color=TEXTO, fontsize=13, fontweight="bold")
    return _png(fig)


@st.cache_data(show_spinner=False, max_entries=24, ttl=TTL_S)
def _png_evolucao(var, dia, passo, versao, suavizacao, vizinhos, passo_grade):
    from matplotlib.figure import Figure
    e = _armazem()["dados"][passo]
    campos, gx1, gy1, mascara_br = _campos(var, passo, versao, suavizacao, vizinhos, passo_grade)
    cfg = VARIAVEIS[var]
    est = np.array([_estatisticas(campos[d], gy1, mascara_br, var) for d in range(N_DIAS)])
    datas = [date.fromisoformat(d) for d in e["datas"]]
    x = np.arange(N_DIAS)
    rot = [f"{'hoje' if i == 0 else DIAS_PT[d.weekday()]}\n{d:%d/%m}" for i, d in enumerate(datas)]

    fig = Figure(figsize=(6.4, 7.6), dpi=130, facecolor=FUNDO_CARD)
    ax1, ax2 = fig.subplots(2, 1, gridspec_kw={"height_ratios": [3, 1.7], "hspace": 0.5})
    for ax in (ax1, ax2):
        ax.set_facecolor(FUNDO_CARD)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(BORDA)
        ax.tick_params(colors=TEXTO_MUDO, labelsize=8.5)
        ax.grid(axis="y", color="#1b2735", lw=0.8)
        ax.set_axisbelow(True)
        ax.set_xticks(x)
        ax.set_xticklabels(rot)

    ax1.axvspan(dia - 0.45, dia + 0.45, color=ACENTO, alpha=0.12, lw=0)
    ax1.fill_between(x, est[:, 2], est[:, 0], color=ACENTO, alpha=0.07)
    ax1.plot(x, est[:, 0], "-o", color="#ff6b6b", lw=2, ms=4, label="Máximo")
    ax1.plot(x, est[:, 1], "-o", color=ACENTO, lw=2.4, ms=4, label="Média")
    ax1.plot(x, est[:, 2], "-o", color="#4da6ff", lw=2, ms=4, label="Mínimo")
    ax1.set_ylabel(cfg["unidade"], color=TEXTO_MUDO, fontsize=9)
    ax1.set_title("Evolução no território", color=TEXTO, fontsize=11,
                  fontweight="bold", loc="left")
    leg = ax1.legend(frameon=False, ncol=3, loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=8.5)
    for t in leg.get_texts():
        t.set_color(TEXTO_SUAVE)

    cores = [ACENTO if i == dia else "#2b3b4b" for i in range(N_DIAS)]
    barras = ax2.bar(x, est[:, 3], color=cores, width=0.62)
    for b, v in zip(barras, est[:, 3]):
        ax2.text(b.get_x() + b.get_width() / 2, v + 3, f"{v:.0f}%", ha="center", fontsize=8.5, color=TEXTO)
    ax2.set_ylim(0, 118)
    ax2.set_yticks([0, 50, 100])
    ax2.set_title(f'{cfg["limiar"][2]} (% da área)', color=TEXTO, fontsize=11, fontweight="bold", loc="left")
    fig.subplots_adjust(left=0.1, right=0.97, top=0.95, bottom=0.07)
    return _png(fig)


# ----------------------------------------------------------------------
# INTERFACE
# ----------------------------------------------------------------------
def _card(label, valor, acento):
    st.markdown(
        f'<div class="pv-card" style="--pv-acento:{acento};"><div class="pv-label">{label}</div>'
        f'<div class="pv-valor">{valor}</div></div>', unsafe_allow_html=True)


def _secao(rodando_inicio=False):
    st.markdown(_CSS, unsafe_allow_html=True)
    with st.container(key="pv_secao"):
        st.subheader("🗺️ Mapas de previsão (Brasil)")
        st.caption("Precipitação, rajadas de vento e temperatura · Open-Meteo com interpolação RBF · "
                   "7 dias a partir de hoje (horário de Brasília).")

        estado = st.session_state.get("pv_estado")
        rodando = bool(estado and estado["rodando"])
        # A coleta terminou enquanto o fragmento se atualizava sozinho: um rerun completo desliga o auto-refresh.
        if rodando_inicio and estado is not None and not estado["rodando"]:
            st.rerun()

        var = st.radio("Variável", list(VARIAVEIS), format_func=lambda v: VARIAVEIS[v]["rotulo"],
                       horizontal=True, key="pv_var")
        with st.expander("⚙️ Interpolação e malha de consulta"):
            c1, c2 = st.columns(2)
            with c1:
                suav = st.slider("Suavização (RBF)", 0.0, 5.0, 0.5, 0.1, key="pv_suav",
                                 help="Maior = campo mais liso; menor = acompanha mais de perto os pontos.")
                viz = st.select_slider("Vizinhos (RBF local)", options=[20, 30, 40, 60, 80], value=40, key="pv_viz")
            with c2:
                grade = st.select_slider("Resolução da grade (°)", options=[0.5, 0.25, 0.15], value=0.25, key="pv_grade")
                passo = st.select_slider("Espaçamento da malha de consulta (°)", options=[3.0, 2.5, 2.0, 1.5],
                                         value=2.0, key="pv_passo", disabled=rodando,
                                         help="Menor espaçamento = mais pontos e mais chamadas à API gratuita do Open-Meteo.")

        entrada = _entrada(passo)
        rotulo_botao = "🔄 Atualizar previsão" if entrada else "🗺️ Gerar mapas de previsão"
        if st.button(rotulo_botao, key="pv_gerar", type="secondary" if entrada else "primary", disabled=rodando):
            armazem = _armazem()
            with armazem["lock"]:
                existente = armazem["rodando"].get(passo)
                if existente is not None and existente["rodando"]:     # outra sessão já está coletando
                    novo, iniciar = existente, False
                else:
                    lon, lat = _pontos_consulta(passo)
                    novo = {"rodando": True, "feitos": 0, "total": len(lon), "erro": None}
                    armazem["rodando"][passo] = novo
                    iniciar = True
            st.session_state["pv_estado"] = novo
            if iniciar:
                threading.Thread(target=_worker_coleta, args=(novo, armazem, passo, lon, lat), daemon=True).start()
            st.rerun()

        if rodando:
            st.progress(min(estado["feitos"] / max(estado["total"], 1), 1.0),
                        text=f"Baixando a previsão do Open-Meteo… [{estado['feitos']}/{estado['total']} pontos]")
            return
        if estado is not None and estado.get("erro") and not entrada:
            st.error(f"Não foi possível baixar a previsão: {estado['erro']}")
        if not entrada:
            st.info("Clique em **Gerar mapas de previsão** para baixar a previsão do Open-Meteo "
                    "(cerca de 20 s) e montar os mapas. Depois da primeira coleta, ela fica disponível "
                    "para todos por 3 h.")
            return

        # ------------------------------------------------------------------
        # Mapas
        # ------------------------------------------------------------------
        versao = int(entrada["ts"])
        args = (passo, versao, suav, viz, grade)
        cfg = VARIAVEIS[var]
        datas = [date.fromisoformat(d) for d in entrada["datas"]]
        campos, gx1, gy1, mascara_br = _campos(var, *args)

        dia = st.radio("Dia", list(range(N_DIAS)), format_func=lambda i: _rotulo_dia(datas[i], i),
                       horizontal=True, key="pv_dia", label_visibility="collapsed")
        vmax, vmedia, vmin, area = _estatisticas(campos[dia], gy1, mascara_br, var)
        un = cfg["unidade"]
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            _card("Máximo", f"{vmax:.1f} {un}", "#ff6b6b")
        with k2:
            _card("Média (Brasil)", f"{vmedia:.1f} {un}", ACENTO)
        with k3:
            _card("Mínimo", f"{vmin:.1f} {un}", "#4da6ff")
        with k4:
            _card(cfg["limiar"][2], f"{area:.0f}%", "#ffd166")

        visao = st.segmented_control("Visão", VISOES, default=VISOES[0], key="pv_visao",
                                     label_visibility="collapsed") or VISOES[0]

        if visao == VISOES[0]:
            col_mapa, col_graf = st.columns([3, 2], gap="large")
            with col_mapa:
                png = _png_dia(var, dia, *args)
                st.image(png)
                st.download_button("⬇️ Baixar PNG do mapa", data=png, mime="image/png", key="pv_dl_dia",
                                   file_name=f"previsao_{var}_{datas[dia]:%Y%m%d}.png", use_container_width=True)
            with col_graf:
                st.image(_png_evolucao(var, dia, *args))
        elif visao == VISOES[1]:
            png7 = _png_semana(var, *args)
            st.image(png7)
            st.download_button("⬇️ Baixar PNG (7 dias)", data=png7, mime="image/png", key="pv_dl_sem",
                               file_name=f"previsao_{var}_7dias_{datas[0]:%Y%m%d}.png", use_container_width=True)
        else:
            df = pd.DataFrame(entrada["dados"][var], columns=[f"{d:%d/%m}" for d in datas]).round(1)
            df.insert(0, "lon", np.round(entrada["lon"], 2))
            df.insert(0, "lat", np.round(entrada["lat"], 2))
            st.dataframe(df, height=420, hide_index=True)
            st.download_button("⬇️ Baixar CSV dos pontos", data=df.to_csv(index=False).encode("utf-8"),
                               mime="text/csv", key="pv_dl_csv", use_container_width=True,
                               file_name=f"previsao_{var}_pontos_{datas[0]:%Y%m%d}.csv")

        st.caption(f"Coletado em {entrada['atualizado']} (Brasília) · {len(entrada['lon'])} pontos de consulta → "
                   f"grade RBF de {grade}° · previsão em cache por 3 h, compartilhada entre os usuários.")


def renderizar():
    """Ponto de entrada: chamado uma vez, no fim do streamlit_app.py."""
    est = st.session_state.get("pv_estado")
    rodando_inicio = bool(est and est["rodando"])
    st.fragment(run_every=2 if rodando_inicio else None)(_secao)(rodando_inicio)
