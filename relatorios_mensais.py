# ======================================================================
# RELATÓRIOS MENSAIS (PDF) - Blue Ocean
# Portado do script "Geração Relatórios Mensais (novo layout)", sem a interface Tkinter.
# Recebe os arquivos do mês (zip com subpastas por unidade, ou arquivos soltos),
# identifica sozinho o que é cada um (boletins, dados de 3 h, alertas, tela de
# previsão, tela de raios, logo) e gera um PDF por unidade, no mesmo layout.
# ======================================================================
import codecs
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import PurePosixPath

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfdoc import PDFString
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvaslib
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

_AQUI = os.path.dirname(os.path.abspath(__file__))
LOGO_PADRAO = os.path.join(_AQUI, "assets", "logo_relatorio_blueocean.png")


# ---------------------------------------------------------------- fonte (estilo Times New Roman)
def _candidatos_fontes():
    c = []
    if sys.platform.startswith("win"):
        wf = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        c.append((os.path.join(wf, "times.ttf"), os.path.join(wf, "timesbd.ttf")))
    elif sys.platform == "darwin":
        c.append(("/Library/Fonts/Times New Roman.ttf", "/Library/Fonts/Times New Roman Bold.ttf"))
        c.append(("/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"))
    # Liberation Serif (métrica idêntica à do Times New Roman) vem junto do app e serve de reserva em qualquer sistema
    c.append((os.path.join(_AQUI, "assets", "fonts", "LiberationSerif-Regular.ttf"), os.path.join(_AQUI, "assets", "fonts", "LiberationSerif-Bold.ttf")))
    return c


FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
for _reg, _bold in _candidatos_fontes():
    try:
        if os.path.exists(_reg) and os.path.exists(_bold):
            pdfmetrics.registerFont(TTFont("SerifCustom", _reg))
            pdfmetrics.registerFont(TTFont("SerifCustom-Bold", _bold))
            FONT_REGULAR, FONT_BOLD = "SerifCustom", "SerifCustom-Bold"
            break
    except Exception:
        continue

# ---------------------------------------------------------------- dados fixos
EQUIPE = [
    ["Samuel Amorim", "Meteorologista", "+55 22 99710-0365"],
    ["Larissa Portella", "Engenheira Meteorologista", "+55 22 99817-5573"],
    ["Mário Vanderlei", "Meteorologista", "+55 22 99858-3166"],
    ["Mayara Lins", "Meteorologista", "+55 22 99704-5244"],
    ["Ynara Castro", "Meteorologista", "+55 22 99791-9689"],
    ["Vittor Courbassier", "Estagiário de Meteorologia", "+55 12 98876-0623"],
    ["Joao Miotto", "Estagiário de Meteorologia", "+55 48 99950-6505"],
]
# Versão alternativa: nos boletins e nos alertas, o nome dos estagiários é trocado.
#  - fins de semana (sábado e domingo) das 06:00 às 18:00 = turno da Mayara: aparece só "Mayara Lins";
#  - nos demais horários: Vittor -> Samuel Amorim, João -> Larissa Portella.
# A tabela da equipe continua igual.
TROCA_ALTERNATIVA = {"vittorcourbassier": "Samuel Amorim", "vitorcourbassier": "Samuel Amorim", "joaomiotto": "Larissa Portella"}
TURNO_MAYARA = ("Mayara Lins", 6, 18)       # nome, hora inicial, hora final (inclusive, até 18:00)


def _turno_mayara(texto):
    """True se a data/hora ('dd/mm/aaaa, HH:MM') cai num sábado ou domingo entre 06:00 e 18:00."""
    m = re.match(r"\s*(\d{2})/(\d{2})/(\d{4})[ ,T]+(\d{1,2}):(\d{2})", str(texto))
    if not m:
        return False
    try:
        dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(5)))
    except ValueError:
        return False
    minutos = dt.hour * 60 + dt.minute
    return dt.weekday() >= 5 and TURNO_MAYARA[1] * 60 <= minutos <= TURNO_MAYARA[2] * 60


def trocar_meteorologistas(linhas, troca, col_data=None):
    """Cópia das linhas com a coluna 'Meteorologista' trocada (nomes comparados sem acento/caixa).
    Quando col_data é informada, nos horários do turno da Mayara os estagiários viram só o nome dela."""
    if not troca:
        return linhas
    col = _coluna(linhas, "meteorologista")
    if not col:
        return linhas
    col_d = _coluna(linhas, col_data) if col_data else None
    saida = []
    for l in linhas:
        atual = l.get(col, "")
        novo = troca.get(_norm(atual), atual)
        if col_d and _norm(atual) in troca and _turno_mayara(l.get(col_d, "")):
            novo = TURNO_MAYARA[0]
        saida.append({**l, col: novo})
    return saida


ENDERECO = "Condomínio do Edifício Heitor Diniz. Av. Rui Barbosa, 1043 - Sala 602 – Centro - Macaé – RJ"
EMPRESA = "Blue Ocean – Meio Ambiente e Infraestrutura"
URL = "https://previsoesbrblueocean.com.br/"

UNIDADES = [
    "ARM Macaé - Armazém Macaé", "Armazém Rio de Janeiro", "CILEP - CENPES", "Porto Açu", "Porto Aratu",
    "Porto Baia de Guanabara", "Porto Belém", "Porto de Imbetiba - Macaé", "Porto Guamaré", "Porto Mucuripe",
    "Porto Paracuru", "Porto TMIB", "Porto Valença", "Refinaria Abreu e Lima - RNEST",
    "Refinaria Alberto Pasqualini - REFAP", "Refinaria de Capuava - RECAP", "Refinaria de Paulínia - REPLAN",
    "Refinaria Duque de Caxias - REDUC", "Refinaria Gabriel Passos - REGAP", "Refinaria Henrique Lage - REVAP",
    "Refinaria Presidente Bernardes - RPBC", "Refinaria Presidente Getúlio Vargas - REPAR",
    "Unidade de Tratamento de Gás de Cabiúnas - UTGCAB", "Unidade de Tratamento de Gás de Cacimbas - UTGC",
    "Unidade de Tratamento de Gás de Caraguatatuba - UTGCA", "Boaventura, Itaboraí - RJ",
    "Unidade de Tratamento de Gás Sul Capixaba - UTGSUL", "UFN-III - Unidade de Fertilizantes Nitrogenados III", "UTE Canoas - UTE CAN", "UTE Cubatão - UTE CBT",
    "UTE Ibirité - UTE IBT", "UTE Juiz de Fora - UTE JF", "UTE Nova Piratininga - UTE NPI",
    "UTE Seropédica/Baixada Fluminense - UTE SRP/BF", "UTE Termobahia - UTE TBA", "UTE Termocamaçari - UTE TCA",
    "UTE Termoceará - UTE TCE", "UTE Termomacaé - UTE TMA", "UTE Termorio - UTE TRI", "UTE Três Lagoas - UTE TLG",
    "UTE Vale do Açu - UTE VLA",
]
# Outros nomes pelos quais uma unidade aparece nas pastas e nos arquivos (comparados sem acento/pontuação).
ALIAS_UNIDADES = {"Boaventura, Itaboraí - RJ": ["utgitb", "unidade de tratamento de gas de itaborai", "boaventura"],
                  "UFN-III - Unidade de Fertilizantes Nitrogenados III": ["ufniii", "ufn iii"]}

# Arquivos que não são de nenhuma unidade (mapa geral, testes): ignorados em silêncio.
IGNORAR_NOMES = ("americadosul", "testtaker")

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
MARGEM_ESQ, MARGEM_DIR, MARGEM_TOPO, MARGEM_BASE = 25, 25, 26, 22
LARGURA_UTIL = 210 - MARGEM_ESQ - MARGEM_DIR


def _norm(valor):
    t = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", t.lower())


_NORM_UNIDADES = {u: _norm(u) for u in UNIDADES}
_NORM_ALIAS = {u: [_norm(a) for a in ALIAS_UNIDADES.get(u, [])] for u in UNIDADES}


def achar_unidade(texto):
    """Nome oficial da unidade a que o texto (pasta, trecho do nome do arquivo, coluna Unidade) se refere, ou None."""
    alvo = _norm(texto)
    if len(alvo) < 3:
        return None
    melhor, pontos = None, 0
    for u in UNIDADES:
        n = _NORM_UNIDADES[u]
        if alvo == n:
            return u
        p = 0
        if n in alvo or alvo in n:
            p = 700 + min(len(n), len(alvo))
        for a in _NORM_ALIAS[u]:
            if a and (a in alvo or alvo in a):
                p = max(p, 900 + len(a))
        if p > pontos:
            melhor, pontos = u, p
    return melhor


# ---------------------------------------------------------------- unidade pelo título da tela de previsão (OCR)
def ocr_disponivel():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _siglas():
    """sigla (parte depois do último ' - ') -> unidade. Só as que não são ambíguas."""
    m = {}
    for u in UNIDADES:
        if " - " in u:
            ult = u.rsplit(" - ", 1)[1]
            if ult == ult.upper():                    # só siglas (RNEST, UTE CAN...), não nomes como "Macaé"
                m.setdefault(_norm(ult), []).append(u)
    return {k: v[0] for k, v in m.items() if len(v) == 1 and len(k) >= 3}


def unidade_por_texto(texto):
    """Unidade a partir do texto lido no título da tela (nome completo ou só a sigla)."""
    linhas = [l.strip() for l in str(texto).splitlines() if l.strip() and not re.search(r"madrugada|manh[ãa]|tarde|noite", l, re.I)][:3]
    cands = list(linhas)
    if len(linhas) >= 2:
        cands += [" ".join(linhas[:2])]
    if len(linhas) >= 3:
        cands += [" ".join(linhas[:3])]
    siglas = _siglas()
    for c in cands:                                   # sigla exata (UTE CAN, RNEST, UTGC...)
        n = _norm(c)
        if n in siglas:
            return siglas[n]
    for c in cands:                                   # tirando um "ruído" solto no fim ("RNEST E", "UTE TBA |")
        t = re.sub(r"\s+\S$", "", c.strip())
        if _norm(t) in siglas:
            return siglas[_norm(t)]
    import difflib
    melhor, nota = None, 0.0                          # nome completo, tolerando letras erradas do OCR
    for c in cands:
        n = _norm(c)
        if len(n) < 6:
            continue
        for u in UNIDADES:
            r = difflib.SequenceMatcher(None, n, _NORM_UNIDADES[u]).ratio()
            if r > nota:
                melhor, nota = u, r
    if nota >= 0.8:
        return melhor
    for c in reversed(cands):
        if len(_norm(c)) >= 8:
            u = achar_unidade(c)
            if u:
                return u
    return None


def ocr_unidade(dados):
    """Lê o título (canto superior esquerdo) da tela de previsão e devolve a unidade, ou None."""
    if not ocr_disponivel():
        return None
    try:
        import pytesseract
        from PIL import Image as PILImage
        im = PILImage.open(io.BytesIO(dados)).convert("L")
        w, h = im.size
        c = im.crop((0, 0, int(w * 0.64), int(h * 0.30)))
        c = c.resize((c.width * 2, c.height * 2))
        try:
            txt = pytesseract.image_to_string(c, lang="por", config="--psm 6")
        except Exception:
            txt = pytesseract.image_to_string(c, config="--psm 6")
        return unidade_por_texto(txt)
    except Exception:
        return None


# ---------------------------------------------------------------- leitura de arquivos
def _decodificar(b):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "ignore")


def ler_csv_bytes(b):
    if not b or not b.strip():
        return []
    leitor = csv.DictReader(io.StringIO(_decodificar(b), newline=""), delimiter=";")
    return [{(unicodedata.normalize("NFC", k).strip() if k else k): (unicodedata.normalize("NFC", v).strip() if v else "")
             for k, v in linha.items()} for linha in leitor]


_RE_NOME_CSV = re.compile(r"relatorio_mensal_(boletins|dados_tempo|alertas)_(.+?)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", re.I)
_EXT_IMG = (".png", ".jpg", ".jpeg", ".webp")


def _tipo_csv(nome, b):
    """boletins / dados / alertas, pelo cabeçalho (e, na falta dele, pelo nome do arquivo)."""
    linhas = ler_csv_bytes(b)
    if linhas:
        cols = {_norm(c) for c in linhas[0].keys() if c}
        if {"codigo", "emitidoem"} <= cols:
            return "boletins", linhas
        if any(c.startswith("temperatura") for c in cols):
            return "dados", linhas
        if {"meteorologista", "nivel"} <= cols:
            return "alertas", linhas
        return None, linhas
    n = _norm(nome)
    for chave, tipo in (("alerta", "alertas"), ("boletim", "boletins"), ("boletins", "boletins"), ("dadostempo", "dados")):
        if chave in n:
            return tipo, []
    return None, []


def _brilho(b):
    from PIL import Image as PILImage
    im = PILImage.open(io.BytesIO(b)).convert("L")
    im.thumbnail((160, 160))
    px = list(im.getdata())
    return sum(px) / max(1, len(px))


def expandir_entradas(entradas):
    """Lista de (caminho_relativo, bytes). Abre zips (inclusive um dentro do outro) e ignora PDFs e os zips de saída."""
    saida = []

    def abrir(prefixo, nome, dados, nivel):
        ext = os.path.splitext(nome)[1].lower()
        if ext == ".zip":
            if nivel > 0 and os.path.basename(nome).upper().startswith("RELATORIO_MENSAL"):
                return                                   # zip com os PDFs já gerados: não é entrada
            try:
                with zipfile.ZipFile(io.BytesIO(dados)) as z:
                    for info in z.infolist():
                        if info.is_dir() or info.filename.startswith("__MACOSX") or os.path.basename(info.filename).startswith("."):
                            continue
                        nome_int = _corrigir_nome_zip(info)
                        abrir(prefixo, nome_int, z.read(info), nivel + 1)
            except zipfile.BadZipFile:
                pass
            return
        saida.append((str(PurePosixPath(prefixo) / nome) if prefixo else nome, dados))

    for nome, dados in entradas:
        abrir("", nome.replace("\\", "/"), dados, 0)
    return saida


def _corrigir_nome_zip(info):
    n = info.filename
    if not (info.flag_bits & 0x800):
        try:
            n = n.encode("cp437").decode("utf-8")
        except Exception:
            pass
    return n.replace("\\", "/")


def identificar(entradas, imagem_unica="auto"):
    """Reconhece cada arquivo e agrupa por unidade.

    Retorna dict com: 'unidades' {nome: {boletins, dados, alertas, img_prev, img_raio, avisos}},
    'logo' (bytes|None), 'periodo' (datetime, datetime)|None, 'sem_unidade' [(nome, bytes, tipo)], 'ignorados' [nomes]."""
    arquivos = expandir_entradas(entradas)
    un, sem_unidade, ignorados, logo = {}, [], [], None
    datas = []
    ocr_lidas = 0

    def da_unidade(u):
        return un.setdefault(u, {"boletins": None, "dados": None, "alertas": None, "imagens": [], "alertas_vazio": False, "avisos": []})

    for caminho, dados in arquivos:
        nome = os.path.basename(caminho)
        pasta = [p for p in caminho.split("/")[:-1] if p]
        ext = os.path.splitext(nome)[1].lower()
        if any(k in _norm(nome) for k in IGNORAR_NOMES):
            ignorados.append(caminho)
            continue

        if ext in _EXT_IMG:
            if "logo" in _norm(nome):
                logo = logo or dados
                continue
            u = next((achar_unidade(p) for p in reversed(pasta) if achar_unidade(p)), None)
            if not u:
                partes = re.split(r"[_\- ]+", os.path.splitext(nome)[0])
                u = achar_unidade(" ".join(p for p in partes if _norm(p) not in ("raio", "raios")))
            if not u:
                u = ocr_unidade(dados)          # captura de tela com nome genérico: lê o título da tela
                if u:
                    ocr_lidas += 1
            try:
                br = _brilho(dados)
            except Exception:
                ignorados.append(caminho)
                continue
            dica = "raio" if any(k in _norm(nome) for k in ("raio", "lightning")) else ("prev" if any(k in _norm(nome) for k in ("previsao", "forecast")) else None)
            item = {"nome": nome, "bytes": dados, "brilho": br, "dica": dica}
            (da_unidade(u)["imagens"].append(item) if u else sem_unidade.append({"tipo": "imagem", **item}))
            continue

        if ext == ".csv":
            tipo, linhas = _tipo_csv(nome, dados)
            m = _RE_NOME_CSV.search(nome)
            u = None
            if m:
                u = achar_unidade(m.group(2))
                try:
                    datas += [datetime.strptime(m.group(3), "%Y-%m-%d"), datetime.strptime(m.group(4), "%Y-%m-%d")]
                except ValueError:
                    pass
            if not u:
                u = next((achar_unidade(p) for p in reversed(pasta) if achar_unidade(p)), None)
            if not u and tipo == "alertas" and linhas:
                u = achar_unidade(linhas[0].get("Unidade", ""))
            if tipo is None:
                ignorados.append(caminho)
                continue
            if not u:
                if tipo == "alertas" and not linhas:
                    ignorados.append(caminho)                      # alertas.csv vazio e sem unidade: nada a fazer
                else:
                    sem_unidade.append({"tipo": "csv", "csv_tipo": tipo, "nome": nome, "bytes": dados})
                continue
            d = da_unidade(u)
            if tipo == "alertas" and not linhas:
                d["alertas_vazio"] = True
                continue
            if d[tipo] is not None and len(d[tipo]["bytes"]) >= len(dados):
                d["avisos"].append(f"Mais de um CSV de {tipo}: usei o maior ({d[tipo]['nome']}).")
                continue
            d[tipo] = {"nome": nome, "bytes": dados}
            continue

        ignorados.append(caminho)

    # imagens de cada unidade: a mais escura é a tela de raios, a mais clara é a de previsão
    for u, d in un.items():
        d["img_prev"], d["img_raio"] = _separar_imagens(d["imagens"], d["avisos"], imagem_unica)
    periodo = (min(datas), max(datas)) if datas else None
    return {"ocr_lidas": ocr_lidas, "imagem_unica": imagem_unica, "unidades": un, "logo": logo, "periodo": periodo, "sem_unidade": sem_unidade, "ignorados": ignorados}


def _separar_imagens(imgs, avisos, imagem_unica="auto"):
    """imagem_unica: quando há só uma imagem sem dica no nome — 'auto' (pelo brilho), 'raio' ou 'prev'."""
    if not imgs:
        return None, None
    if len(imgs) == 1 and imgs[0]["dica"] is None and imagem_unica in ("raio", "prev"):
        return (None, imgs[0]) if imagem_unica == "raio" else (imgs[0], None)
    raio = next((i for i in imgs if i["dica"] == "raio"), None)
    prev = next((i for i in imgs if i["dica"] == "prev"), None)
    resto = [i for i in imgs if i is not raio and i is not prev]
    if raio is None and prev is None and len(resto) >= 2:
        resto.sort(key=lambda i: i["brilho"])
        raio, prev = resto[0], resto[-1]
    elif raio is None and resto:
        # só uma sobrou: decide pelo brilho (tela de raios é escura)
        c = min(resto, key=lambda i: i["brilho"])
        if c["brilho"] < 110:
            raio = c
            resto.remove(c)
    if prev is None and resto:
        prev = max(resto, key=lambda i: i["brilho"])
    if len(imgs) > 2:
        avisos.append(f"{len(imgs)} imagens na pasta: usei a mais clara como previsão e a mais escura como raios.")
    return prev, raio


def atribuir_sem_unidade(res, indice, unidade):
    """Associa manualmente um arquivo da lista 'sem_unidade' a uma unidade e reavalia as imagens."""
    item = res["sem_unidade"].pop(indice)
    d = res["unidades"].setdefault(unidade, {"boletins": None, "dados": None, "alertas": None, "imagens": [], "alertas_vazio": False, "avisos": []})
    if item["tipo"] == "imagem":
        d["imagens"].append({k: item[k] for k in ("nome", "bytes", "brilho", "dica")})
        d["avisos"] = [a for a in d["avisos"] if "imagens na pasta" not in a]
        d["img_prev"], d["img_raio"] = _separar_imagens(d["imagens"], d["avisos"], res.get("imagem_unica", "auto"))
    else:
        d[item["csv_tipo"]] = {"nome": item["nome"], "bytes": item["bytes"]}


def situacao(d):
    """(pode gerar?, [o que falta de obrigatório], [o que falta de opcional])"""
    falta = [n for n, k in (("boletins", "boletins"), ("dados 3 h", "dados")) if not d.get(k)]
    opcional = [n for n, k in (("tela de previsão", "img_prev"), ("tela de raios", "img_raio")) if not d.get(k)]
    return (not falta), falta, opcional


# ---------------------------------------------------------------- período e datas em português
def formatar_periodo(ini, fim):
    if ini.year == fim.year:
        return f"{ini.day} de {MESES[ini.month - 1]} a {fim.day} de {MESES[fim.month - 1]} de {fim.year}"
    return f"{ini.day} de {MESES[ini.month - 1]} de {ini.year} a {fim.day} de {MESES[fim.month - 1]} de {fim.year}"


def data_capa(fim):
    return f"{MESES[fim.month - 1]} de {fim.year}"


# ---------------------------------------------------------------- estilos e tabelas (layout do relatório)
def estilos():
    return {
        "titulo_capa": ParagraphStyle("tc", fontName=FONT_BOLD, fontSize=16, leading=22, alignment=TA_CENTER),
        "sub_capa_bold": ParagraphStyle("scb", fontName=FONT_BOLD, fontSize=13, leading=18, alignment=TA_CENTER),
        "sub_capa_normal": ParagraphStyle("scn", fontName=FONT_REGULAR, fontSize=13, leading=18, alignment=TA_CENTER),
        "secao": ParagraphStyle("se", fontName=FONT_BOLD, fontSize=13, leading=17, spaceBefore=14, spaceAfter=6, keepWithNext=True),
        "corpo": ParagraphStyle("co", fontName=FONT_REGULAR, fontSize=12, leading=16),
        "legenda": ParagraphStyle("le", fontName=FONT_REGULAR, fontSize=12, leading=16, alignment=TA_CENTER, spaceBefore=3, spaceAfter=6),
        "cap_tab": ParagraphStyle("ct", fontName=FONT_REGULAR, fontSize=12, leading=16, alignment=TA_CENTER, spaceAfter=4, keepWithNext=True),
        "cel": ParagraphStyle("ce", fontName=FONT_REGULAR, fontSize=10, leading=13),
        "cel_c": ParagraphStyle("cc", fontName=FONT_REGULAR, fontSize=10, leading=13, alignment=TA_CENTER),
        "cel_h": ParagraphStyle("ch", fontName=FONT_BOLD, fontSize=10, leading=13),
        "cel_hc": ParagraphStyle("hc", fontName=FONT_BOLD, fontSize=10, leading=13, alignment=TA_CENTER),
        "alerta": ParagraphStyle("al", fontName=FONT_REGULAR, fontSize=8, leading=9.5),
        "alerta_c": ParagraphStyle("alc", fontName=FONT_REGULAR, fontSize=8, leading=9.5, alignment=TA_CENTER),
        "alerta_h": ParagraphStyle("alh", fontName=FONT_BOLD, fontSize=8, leading=9.5),
        "alerta_hc": ParagraphStyle("alhc", fontName=FONT_BOLD, fontSize=8, leading=9.5, alignment=TA_CENTER),
        "dados_c": ParagraphStyle("ddc", fontName=FONT_REGULAR, fontSize=8, leading=9.5, alignment=TA_CENTER),
        "dados_hc": ParagraphStyle("ddhc", fontName=FONT_BOLD, fontSize=8, leading=9.5, alignment=TA_CENTER),
    }


def _p(texto, estilo):
    seguro = (str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;br/&gt;", "<br/>"))
    return Paragraph(seguro, estilo)


def somente_data(valor):
    return "" if valor is None else str(valor).split(",")[0].strip()


def _estilo_tabela():
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.black), ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, colors.black),
    ])


def tabela_boletins(linhas, st):
    cab = [_p("<b>Código</b>", st["cel_hc"]), _p("<b>Emitido em</b>", st["cel_hc"]), _p("<b>Título</b>", st["cel_h"]),
           _p("<b>Meteorologista</b>", st["cel_h"]), _p("<b>Nível</b>", st["cel_hc"])]
    dados = [cab]
    for l in linhas:
        dados.append([_p(l.get("Código", ""), st["cel"]), _p(somente_data(l.get("Emitido em", "")), st["cel_c"]),
                      _p(l.get("Título", ""), st["cel"]), _p(l.get("Meteorologista", ""), st["cel"]), _p(l.get("Nível", ""), st["cel_c"])])
    t = Table(dados, colWidths=[20 * mm, 26 * mm, 54 * mm, 35 * mm, 25 * mm], repeatRows=1)
    t.setStyle(_estilo_tabela())
    return t


def tabela_dados(linhas, st):
    cabs = ["<b>Data/Hora</b>", "<b>Temperatura<br/>(°C)</b>", "<b>Vento<br/>(km/h)</b>", "<b>Rajada<br/>(km/h)</b>",
            "<b>Precipitação<br/>(mm/3h)</b>", "<b>Umidade<br/>(%)</b>", "<b>Radiação<br/>UV (UVI)</b>"]
    chaves = ["Data/Hora", "Temperatura (°C)", "Vento (km/h)", "Rajada (km/h)", "Precipitação (mm)", "Umidade (%)", "Radiação UV (UVI)"]
    dados = [[_p(c, st["dados_hc"]) for c in cabs]]
    for l in linhas:
        dados.append([_p(l.get(k, ""), st["dados_c"]) for k in chaves])
    t = Table(dados, colWidths=[w * mm for w in [29, 23, 21, 21, 24, 21, 21]], repeatRows=1, hAlign="CENTER")
    t.setStyle(_estilo_tabela())
    return t


def _coluna(linhas, nome):
    for l in linhas:
        for c in l.keys():
            if c and c.strip().casefold() == nome.casefold():
                return c
    return None


def tabela_alertas(linhas, st):
    col_rec = _coluna(linhas, "recebeu")
    cab = [_p("<b>Data/Hora</b>", st["alerta_hc"]), _p("<b>Unidade</b>", st["alerta_h"]), _p("<b>Meteorologista</b>", st["alerta_h"]),
           _p("<b>Tipo</b>", st["alerta_hc"]), _p("<b>Nível</b>", st["alerta_hc"]), _p("<b>Texto</b>", st["alerta_h"])]
    if col_rec:
        cab.append(_p("<b>Recebeu</b>", st["alerta_hc"]))
    dados = [cab]
    for l in linhas:
        linha = [_p(l.get("Data/Hora", ""), st["alerta_c"]), _p(l.get("Unidade", ""), st["alerta"]), _p(l.get("Meteorologista", ""), st["alerta"]),
                 _p(l.get("Tipo", ""), st["alerta_c"]), _p(l.get("Nível", ""), st["alerta_c"]), _p(l.get("Texto", ""), st["alerta"])]
        if col_rec:
            linha.append(_p(l.get(col_rec, ""), st["alerta_c"]))
        dados.append(linha)
    larg = [27, 35, 26, 14, 16, 24, 18] if col_rec else [27, 30, 27, 17, 17, 42]
    t = Table(dados, colWidths=[w * mm for w in larg], repeatRows=1, hAlign="CENTER")
    t.setStyle(_estilo_tabela())
    return t


def tabela_equipe(st):
    dados = [[_p("<b>Nome</b>", st["cel_h"]), _p("<b>Cargo</b>", st["cel_h"]), _p("<b>Contato</b>", st["cel_hc"])]]
    for nome, cargo, contato in EQUIPE:
        dados.append([_p(nome, st["cel"]), _p(cargo, st["cel"]), _p(contato, st["cel_c"])])
    t = Table(dados, colWidths=[55 * mm, 65 * mm, 40 * mm], repeatRows=1)
    t.setStyle(_estilo_tabela())
    return t


# ---------------------------------------------------------------- páginas (capa, cabeçalho, rodapé)
def _capa_inferior(canvas, doc, local, data):
    canvas.saveState()
    larg, _ = A4
    canvas.setFont(FONT_REGULAR, 10)
    canvas.drawCentredString(larg / 2, 38 * mm, local)
    canvas.drawCentredString(larg / 2, 31 * mm, data)
    canvas.restoreState()


def _cabecalho_rodape(canvas, doc, logo):
    canvas.saveState()
    larg_pag, alt_pag = A4
    y_top = alt_pag - MARGEM_TOPO * mm + 12 * mm
    x0 = MARGEM_ESQ * mm
    try:
        img = ImageReader(logo)
        iw, ih = img.getSize()
        h = 6 * mm
        w = h * iw / ih
        canvas.drawImage(img, x0, y_top - 1.5 * mm, width=w, height=h, preserveAspectRatio=True, mask="auto")
        x_texto = x0 + w + 3 * mm
    except Exception:
        x_texto = x0
    canvas.setFont(FONT_REGULAR, 12)
    canvas.drawString(x_texto, y_top + 0.5 * mm, EMPRESA)
    if doc.page > 1:
        canvas.setFont(FONT_REGULAR, 10)
        canvas.drawRightString(larg_pag - MARGEM_DIR * mm, y_top + 0.5 * mm, str(doc.page - 1))
    canvas.setLineWidth(1.5)
    canvas.line(x0, y_top - 2.5 * mm, larg_pag - MARGEM_DIR * mm, y_top - 2.5 * mm)
    y_foot = MARGEM_BASE * mm - 6 * mm
    canvas.setFont(FONT_REGULAR, 10)
    canvas.drawCentredString(larg_pag / 2, y_foot + 4 * mm, EMPRESA)
    canvas.drawCentredString(larg_pag / 2, y_foot, ENDERECO)
    canvas.restoreState()


class _CanvasUTF16(_canvaslib.Canvas):
    """Grava título/autor/assunto em UTF-16BE para os acentos aparecerem certos na aba do navegador."""
    @staticmethod
    def _u16(texto):
        return PDFString(codecs.BOM_UTF16_BE + str(texto).encode("utf_16_be"), enc="raw")

    def setTitle(self, title):
        super().setTitle(title)
        try: self._doc.info.title = self._u16(title)
        except Exception: pass

    def setAuthor(self, author):
        super().setAuthor(author)
        try: self._doc.info.author = self._u16(author)
        except Exception: pass

    def setSubject(self, subject):
        super().setSubject(subject)
        try: self._doc.info.subject = self._u16(subject)
        except Exception: pass


def _imagem(dados, largura):
    ir = ImageReader(io.BytesIO(dados))
    iw, ih = ir.getSize()
    return Image(io.BytesIO(dados), width=largura, height=largura * ih / iw, hAlign="CENTER")


def gerar_pdf(config):
    """config: contratante, unidade, periodo, local, data, logo (bytes), img1/img2 (bytes|None),
    boletins/dados/alertas (listas de dicts). Devolve os bytes do PDF."""
    st = estilos()
    troca = config.get("troca_meteorologistas")
    boletins, dados = trocar_meteorologistas(config.get("boletins") or [], troca, "Emitido em"), config.get("dados") or []
    alertas = trocar_meteorologistas(config.get("alertas") or [], troca, "Data/Hora")
    logo = io.BytesIO(config["logo"]) if config.get("logo") else LOGO_PADRAO
    saida = io.BytesIO()
    doc = BaseDocTemplate(saida, pagesize=A4, title=f"Relatório Mensal - {config['unidade']} - {config['periodo']}", author=EMPRESA,
                          subject="Relatório Mensal de Prestação de Serviços", leftMargin=MARGEM_ESQ * mm, rightMargin=MARGEM_DIR * mm,
                          topMargin=MARGEM_TOPO * mm, bottomMargin=MARGEM_BASE * mm)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="corpo")
    doc.addPageTemplates([
        PageTemplate(id="capa", frames=[frame], onPage=lambda c, d: _capa_inferior(c, d, config["local"], config["data"])),
        PageTemplate(id="conteudo", frames=[frame], onPage=lambda c, d: _cabecalho_rodape(c, d, logo if isinstance(logo, str) else io.BytesIO(config["logo"]))),
    ])

    f = [Spacer(1, -25 * mm)]
    try:
        f.append(_imagem(config["logo"], 100 * mm) if config.get("logo") else Image(LOGO_PADRAO, width=100 * mm, height=100 * mm * _prop(LOGO_PADRAO), hAlign="CENTER"))
    except Exception:
        pass
    f += [Spacer(1, 10 * mm), Paragraph(EMPRESA, st["sub_capa_bold"]), Spacer(1, 10 * mm),
          Paragraph("<b>RELATÓRIO MENSAL DE PRESTAÇÃO DE SERVIÇOS</b>", st["titulo_capa"]), Spacer(1, 6 * mm),
          Paragraph(config["contratante"], st["sub_capa_normal"]), Spacer(1, 6 * mm),
          Paragraph(f"Unidade: {config['unidade']}", st["sub_capa_normal"]), Spacer(1, 6 * mm),
          Paragraph(f"Período: {config['periodo']}", st["sub_capa_normal"]),
          NextPageTemplate("conteudo"), PageBreak(),
          Paragraph("Relatório Mensal de Prestação de Serviços", st["secao"]),
          Paragraph(f"<b>Contratante: {config['contratante']}</b>", st["corpo"]),
          Paragraph(f"<b>Unidade Tomadora: {config['unidade']}</b>", st["corpo"]),
          Paragraph("<b>Contratado: Blue Ocean</b>", st["corpo"]), Spacer(1, 3 * mm),
          Paragraph(f"<b>Período: {config['periodo']}</b>", st["corpo"]),
          Paragraph("<b>Disponibilidade das informações e dos serviços:</b> 24 horas por dia, 365 dias por ano", st["corpo"]),
          Paragraph("1. Página principal de acesso para as informações e produtos disponibilizados:", st["secao"]),
          Paragraph(f"<u>{URL}</u>", st["corpo"]), Spacer(1, 4 * mm)]

    n_fig = 0
    for img, legenda in [(config.get("img1"), "Tela do Sistema de Previsão"),
                         (config.get("img2"), "Tela do Sistema de Monitoramento de Raios")]:
        if img:
            n_fig += 1
            legenda = f"Figura {n_fig} – {legenda}"
            try:
                f += [_imagem(img, 0.76 * LARGURA_UTIL * mm), Paragraph(legenda, st["legenda"]), Spacer(1, 1 * mm)]
            except Exception:
                pass

    f.append(Paragraph("2. Boletim Diário de Previsão por unidade monitorada", st["secao"]))
    if boletins:
        f += [Paragraph("Tabela 1 – Boletins Mensais enviados", st["cap_tab"]), tabela_boletins(boletins, st)]
    else:
        f.append(Paragraph("<i>Não foram registrados boletins enviados no período analisado.</i>", st["corpo"]))
    f.append(Spacer(1, 4 * mm))

    f.append(Paragraph("3. Atualização dos boletins a cada 3 horas", st["secao"]))
    if dados:
        f += [Paragraph("Tabela 2 – Atualização dos dados a cada 3 horas.", st["cap_tab"]), tabela_dados(dados, st)]
    else:
        f.append(Paragraph("<i>Não foram registrados dados meteorológicos históricos para esta unidade no período analisado.</i>", st["corpo"]))
    f.append(Spacer(1, 4 * mm))

    f.append(Paragraph("4. Alertas enviados para a Unidade Tomadora", st["secao"]))
    if alertas:
        f += [Paragraph("Tabela 3 – Alertas enviados para a Unidade Tomadora", st["cap_tab"]), tabela_alertas(alertas, st)]
    else:
        f.append(Paragraph("<i>Não foram registrados alertas para a unidade tomadora no período analisado.</i>", st["corpo"]))
    f.append(Spacer(1, 4 * mm))

    f += [Paragraph("5. Equipe de Meteorologia Blue Ocean", st["secao"]),
          Paragraph("Tabela 4 – Equipe de Meteorologia Blue Ocean", st["cap_tab"]), tabela_equipe(st), Spacer(1, 4 * mm),
          Paragraph("6. Índice de Disponibilidade de Dados", st["secao"]),
          Paragraph(f"Durante o período desta medição, {config['periodo']}, o sistema Blue Ocean esteve 100% do "
                    "tempo disponível para acesso, com entrega de todos os dados previstos em contrato.", st["corpo"])]
    doc.build(f, canvasmaker=_CanvasUTF16)
    return saida.getvalue()


def _prop(caminho):
    iw, ih = ImageReader(caminho).getSize()
    return ih / iw


def nome_arquivo_pdf(unidade):
    """Mesmo padrão do script original: RELATORIO_MENSAL_<unidade>.pdf"""
    n = re.sub(r'[<>:"/\\|?*]', "-", unidade)
    n = re.sub(r"\s+", "_", n).strip("._-") or "UNIDADE"
    return f"RELATORIO_MENSAL_{n}.pdf"


def gerar_da_identificacao(unidade, d, logo, contratante, periodo, local, data, troca_meteorologistas=None):
    return gerar_pdf({
        "troca_meteorologistas": troca_meteorologistas,
        "contratante": contratante, "unidade": unidade, "periodo": periodo, "local": local, "data": data, "logo": logo,
        "img1": d["img_prev"]["bytes"] if d.get("img_prev") else None,
        "img2": d["img_raio"]["bytes"] if d.get("img_raio") else None,
        "boletins": ler_csv_bytes(d["boletins"]["bytes"]) if d.get("boletins") else [],
        "dados": ler_csv_bytes(d["dados"]["bytes"]) if d.get("dados") else [],
        "alertas": ler_csv_bytes(d["alertas"]["bytes"]) if d.get("alertas") else [],
    })
