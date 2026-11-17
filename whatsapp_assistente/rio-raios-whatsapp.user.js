// ==UserScript==
// @name         RIO Raios → WhatsApp Web (assistente com supervisão)
// @namespace    rio-raios
// @version      2.3
// @description  Recebe o alerta do app RIO Raios, abre o grupo da unidade no WhatsApp Web e deixa a mensagem DIGITADA, e preenche o formulário do site da BlueOcean. Você confere e confirma.
// @match        https://web.whatsapp.com/*
// @match        https://*.streamlit.app/*
// @match        http://localhost:*/*
// @match        https://previsoesbrblueocean.com.br/*
// @match        https://www.previsoesbrblueocean.com.br/*
// @noframes
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// @grant        GM_setClipboard
// @grant        GM_notification
// ==/UserScript==

(function () {
  "use strict";

  // ------------------------------------------------------------------
  // CONFIGURAÇÃO
  // ------------------------------------------------------------------
  // Como achar o grupo de cada unidade: o script procura no WhatsApp por (nesta ordem) o texto antes do " - " do
  // nome da estação, o texto depois do " - " (a sigla) e o nome completo. Se o nome do grupo não tiver nada disso,
  // escreva aqui o texto de busca da unidade:  "Nome da estação no app": "texto que aparece no nome do grupo"
  var BUSCA_POR_UNIDADE = {
    "UTE Termobahia - UTE TBA": "UTE Termobahia",
    "UTE Termoceará - UTE TCE": "UTE Termoceará",
    "UTE Vale do Açu - UTE VLA": "UTE Vale do Açu",
    "Refinaria Abreu e Lima - RNEST": "RNEST",
    "Unidade de Tratamento de Gás Sul Capixaba - UTGSUL": "UTGSUL",
    "Unidade de Tratamento de Gás de Cacimbas - UTGC": "UTGC - Linhares",
    "Refinaria Duque de Caxias - REDUC": "REDUC",
    "UTE Termorio - UTE TRI": "UTE Termorio",
    "BOAVENTURA, Itaboraí-RJ": "BOAVENTURA",
    "Unidade de Tratamento de Gás de Cabiúnas - UTGCAB": "UTGCAB",
    "UTE Termomacaé - UTE TMA": "UTE TMA",
    "UTE Seropédica/Baixada Fluminense - UTE SRP/BF": "UTE SRP/BF",
    "Refinaria Gabriel Passos - REGAP": "REGAP",
    "UTE Ibirité - UTE IBT": "UTE IBT",
    "UTE Juiz de Fora - UTE JF": "UTE JF",
    "UTE Três Lagoas - UTE TLG": "UTE TLG",
    "UFN III - Unidade de Fertilizantes Nitrogenados III": "UFN-III",
    "Unidade de Tratamento de Gás de Caraguatatuba - UTGCA": "UTGCA - Caraguatatuba",
    "Refinaria Presidente Bernardes - RPBC": "RPBC - Cubatão",
    "Refinaria Henrique Lage - REVAP": "REVAP",
    "Refinaria de Capuava - RECAP": "RECAP",
    "Refinaria de Paulínia - REPLAN": "REPLAN",
    "UTE Nova Piratininga - UTE NPI": "UTE NPI",
    "Refinaria Presidente Getúlio Vargas - REPAR": "REPAR",
    "Refinaria Alberto Pasqualini - REFAP": "REFAP",
    "UTE Canoas - UTE CAN": "UTE CAN",
    "Armazém Rio de Janeiro": "Armazém Rio de Janeiro",
    "CILEP - CENPES": "CENPES",
    "Porto Baia de Guanabara": "Porto Baia de Guanabara",
    "ARM Macaé - Armazém Macaé": "ARM Macaé",
    "Porto de Imbetiba - Macaé": "Porto de Imbetiba",
    "Porto Açu": "Porto do Açú",
    "Porto Aratu": "Porto Aratu",
    "Porto TMIB": "Porto TMIB",
    "Porto Belém": "Porto Belém",
    "Porto Valença": "Porto Valença",
    "Porto Guamaré": "Porto Guamaré",
    "Porto Mucuripe": "Porto Mucuripe",
    "Porto Paracuru": "Porto Paracuru",
  };
  // Se TODOS os grupos tiverem a mesma palavra no nome (ex.: "ALERTAS"), ela é preferida quando houver mais de um resultado.
  var PALAVRA_PREFERIDA = "alertas";

  var CHAVE = "rio_envio";
  var CHAVE_FILA = "rio_fila";
  var CHAVE_REGISTRO = "rio_registro";
  var CHAVE_BOLETIM = "rio_boletim";
  var CHAVE_FILA_SITE = "rio_fila_site";        // fila de boletins a registrar no site (um por vez)
  var CHAVE_PROG_SITE = "rio_fila_site_prog";   // ids já salvos no site (o app marca o check "Site")
  var ehWhatsApp = location.hostname === "web.whatsapp.com";
  var ehSite = /previsoesbrblueocean\.com\.br$/.test(location.hostname);

  // Selo de diagnóstico: aparece uns segundos no canto da página quando o script está rodando.
  // Se ele NÃO aparece no app / WhatsApp / site, o navegador não está executando o userscript (veja "Allow User Scripts").
  (function () {
    function mostrar() {
      if (!document.body || document.getElementById("rio-selo")) return;
      var d = document.createElement("div");
      d.id = "rio-selo";
      d.textContent = "🤖 RIO Assistente v2.3 ativo (" + (ehWhatsApp ? "WhatsApp" : ehSite ? "site BlueOcean" : "app RIO") + ")";
      d.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2147483647;padding:6px 12px;border-radius:8px;background:#075e54;color:#fff;font:600 12px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4);transition:opacity .6s;";
      document.body.appendChild(d);
      setTimeout(function () { d.style.opacity = "0"; }, 6000);
      setTimeout(function () { d.remove(); }, 6800);
    }
    if (document.body) mostrar(); else document.addEventListener("DOMContentLoaded", mostrar);
  })();

  function norm(t) {
    return String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  }
  function esperar(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function aguardar(fn, ms, passo) {
    var fim = Date.now() + ms;
    while (Date.now() < fim) { var v = fn(); if (v) return v; await esperar(passo || 150); }
    return null;
  }

  // ------------------------------------------------------------------
  // LADO DO APP (streamlit): repassa a mensagem do mapa para a aba do WhatsApp
  // ------------------------------------------------------------------
  if (!ehWhatsApp && !ehSite) {
    window.addEventListener("message", function (ev) {
      var d = ev.data;
      if (!d || d.fonte !== "rio-raios") return;
      if (d.tipo === "fila" && Array.isArray(d.itens)) {
        GM_setValue(CHAVE_FILA, { itens: d.itens.map(function (i) { return { estacao: String(i.estacao || ""), texto: String(i.texto || ""), id: String(i.id || "") }; }), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "registrar") {
        GM_setValue(CHAVE_REGISTRO, { estacao: String(d.estacao || ""), nivel: String(d.nivel || "vermelho"), minutos: parseInt(d.minutos, 10) || 60, ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "fila_site" && Array.isArray(d.itens)) {
        GM_setValue(CHAVE_PROG_SITE, { feitos: [], ts: Date.now() });
        GM_setValue(CHAVE_FILA_SITE, { id: String(Date.now()), indice: 0, ativa: true, pulados: [], salvos: [], ts: Date.now(),
          itens: d.itens.map(function (i) { return { id: String(i.id || ""), estacao: String(i.estacao || ""), status: String(i.status || "verde"),
                                                  titulo: String(i.titulo || ""), resumo: String(i.resumo || ""), texto: String(i.texto || "") }; }) });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "boletim") {
        GM_setValue(CHAVE_BOLETIM, { estacao: String(d.estacao || ""), status: String(d.status || "verde"), titulo: String(d.titulo || ""),
                                     resumo: String(d.resumo || ""), texto: String(d.texto || ""), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo !== "preparar") return;
      GM_setValue(CHAVE, { estacao: String(d.estacao || ""), texto: String(d.texto || ""), id: String(d.id || ""), ts: Date.now() });
      try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
    });
    // O site avisa quais boletins foram salvos: repassa a todos os quadros (iframes) do app para marcar o check "Site".
    function espalhar(win, msg, nivel) {
      try { win.postMessage(msg, "*"); } catch (e) {}
      if (nivel > 3) return;
      var n = 0; try { n = win.length; } catch (e) {}
      for (var i = 0; i < n; i++) { try { espalhar(win.frames[i], msg, nivel + 1); } catch (e) {} }
    }
    GM_addValueChangeListener(CHAVE_PROG_SITE, function (nome, antigo, novo, remoto) {
      if (novo) espalhar(window, { fonte: "rio-raios-prog-site", feitos: novo.feitos || [] }, 0);
    });
    return;
  }


  // ------------------------------------------------------------------
  // LADO DO SITE DA BLUEOCEAN (Registro de eventos críticos): preenche o formulário "Novo evento".
  // NUNCA clica em "Salvar": você confere e salva.
  // ------------------------------------------------------------------
  if (ehSite) {
    var alnum = function (t) { return norm(t).replace(/[^a-z0-9]/g, ""); };
    var faixaSite = null;
    var avisoSite = function (msg, cor) {
      if (!faixaSite) {
        faixaSite = document.createElement("div");
        faixaSite.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;font:600 14px sans-serif;color:#fff;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.4);cursor:pointer;";
        faixaSite.title = "Clique para fechar";
        faixaSite.addEventListener("click", function () { faixaSite.style.display = "none"; });
        document.body.appendChild(faixaSite);
      }
      faixaSite.style.background = cor || "#075e54"; faixaSite.textContent = msg; faixaSite.style.display = "block";
    };
    var setarValor = function (el, v) {
      var proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      var setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    };
    var raizForm = function (titulo) {
      var t = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6,div,span,p")).find(function (e) { return e.children.length === 0 && norm(e.textContent) === (titulo || "novo evento"); });
      var p = t;
      for (var i = 0; p && i < 8; i++, p = p.parentElement) if (p.querySelector("select")) return p;
      return document.body;
    };
    var textoProprio = function (el) {
      return Array.from(el.childNodes).filter(function (n) { return n.nodeType === 3; }).map(function (n) { return n.textContent; }).join(" ");
    };
    var SEL_CTRL = "select,input:not([type=checkbox]):not([type=radio]),textarea";
    var controlePorRotulo = function (raiz, rotulo, posicao) {
      var alvo = norm(rotulo);
      var els = Array.from(raiz.querySelectorAll("label,span,div,p,small,strong"));
      for (var k = 0; k < els.length; k++) {
        var el = els[k];
        var igual = norm(el.textContent) === alvo || norm(textoProprio(el)) === alvo;
        if (!igual) continue;
        if (el.htmlFor) { var c0 = document.getElementById(el.htmlFor); if (c0) return c0; }
        var dentro = el.querySelector(SEL_CTRL);
        if (dentro) return dentro;
        var p = el;
        for (var i = 0; i < 4; i++) {
          p = p.parentElement; if (!p) break;
          var c = p.querySelector(SEL_CTRL);
          if (c) return c;
        }
      }
      // plano B: posição dentro do formulário
      if (posicao) {
        var lista = Array.from(raiz.querySelectorAll(posicao.seletor));
        return lista[posicao.indice] || null;
      }
      return null;
    };
    var acharOpcao = function (sel, estacao) {
      var opcoes = Array.from(sel.options).filter(function (o) { return o.value !== "" || alnum(o.textContent) !== "selecione"; });
      var alvo = alnum(estacao);
      var e = opcoes.find(function (o) { return alnum(o.textContent) === alvo; });
      if (e) return e;
      if (/boaventura|itaborai/.test(alvo)) { e = opcoes.find(function (o) { return /itaborai/.test(alnum(o.textContent)); }); if (e) return e; }
      var sigla = alnum(String(estacao).split(" - ").slice(-1)[0]);
      e = opcoes.find(function (o) { var a = alnum(o.textContent); return a.length > 5 && (a.indexOf(alvo) >= 0 || alvo.indexOf(a) >= 0); });
      if (e) return e;
      if (sigla.length >= 3) { e = opcoes.find(function (o) { return alnum(o.textContent).slice(-sigla.length) === sigla; }); if (e) return e; }
      var toks = norm(estacao).split(/[^a-z0-9]+/).filter(function (t) { return t.length > 2; });
      var melhor = null, nota = 0;
      opcoes.forEach(function (o) {
        var n = norm(o.textContent), ok = toks.filter(function (t) { return n.indexOf(t) >= 0; }).length / (toks.length || 1);
        if (ok > nota) { nota = ok; melhor = o; }
      });
      return nota >= 0.7 ? melhor : null;
    };
    var partesSP = function (ms) {
      var f = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ms));
      var o = {}; f.forEach(function (p) { o[p.type] = p.value; });
      return o.year + "-" + o.month + "-" + o.day + "T" + o.hour + ":" + o.minute;
    };
    var estaLigado = function (el) {
      var cb = el.matches("input[type=checkbox]") ? el : el.querySelector("input[type=checkbox]");
      if (cb) return cb.checked;
      var x = el.closest("[aria-pressed],[aria-checked]") || el;
      var a = x.getAttribute("aria-pressed") || x.getAttribute("aria-checked");
      if (a === "true") return true;
      if (a === "false") return false;
      if (/(^|[\s-_])(active|selected|checked|on)([\s-_]|$)/i.test(el.className || "")) return true;
      return null;
    };
    var preencherSite = async function (d) {
      if (!/\/alerts/.test(location.pathname)) { avisoSite("⚠️ Abra a página 'Registro de eventos críticos' (/alerts) e envie de novo pelo app.", "#b45309"); return; }
      var raiz = raizForm();
      raiz.scrollIntoView({ block: "center", behavior: "smooth" });
      var falhas = [];
      // 1) Unidade
      var selU = controlePorRotulo(raiz, "Unidade", { seletor: "select", indice: 0 });
      if (!selU || selU.tagName !== "SELECT") falhas.push("campo Unidade");
      else {
        var op = acharOpcao(selU, d.estacao);
        if (!op) falhas.push("unidade '" + d.estacao + "' não encontrada na lista"); else setarValor(selU, op.value);
      }
      await esperar(300);
      // 2) Datas (início = agora em Brasília; vencimento = início + validade; verde mantém o vencimento do site)
      var agora = Date.now();
      var ini = controlePorRotulo(raiz, "Início", { seletor: "input[type=datetime-local]", indice: 0 });
      if (!ini) falhas.push("campo Início"); else setarValor(ini, partesSP(agora));
      {
        var minVenc = d.nivel === "verde" ? 60 : d.minutos;   // alerta verde: sempre 1 hora a partir de agora
        var ven = controlePorRotulo(raiz, "Vencimento", { seletor: "input[type=datetime-local]", indice: 1 });
        if (!ven) falhas.push("campo Vencimento"); else setarValor(ven, partesSP(agora + minVenc * 60000));
      }
      await esperar(200);
      // 3) Nível
      var selN = controlePorRotulo(raiz, "Nível", { seletor: "select", indice: 1 });
      var palavra = { verde: "verde", amarelo: "amarelo", vermelho: "vermelho" }[d.nivel] || "vermelho";
      if (!selN || selN.tagName !== "SELECT") falhas.push("campo Nível");
      else {
        var on = Array.from(selN.options).find(function (o) { return norm(o.textContent).indexOf(palavra) >= 0; });
        if (!on) falhas.push("nível " + palavra); else setarValor(selN, on.value);
      }
      await esperar(300);
      // 4) Parâmetro RAIOS: sempre marcado (inclusive no alerta verde)
      var avisoRaios = "";
      {
        var bt = Array.from(raiz.querySelectorAll("button,label,[role=button],[role=checkbox]")).find(function (e) { return norm(e.textContent) === "raios"; });
        if (!bt) falhas.push("botão RAIOS");
        else {
          var ligado = estaLigado(bt);
          if (ligado === false || ligado === null) { bt.click(); if (ligado === null) avisoRaios = " Confira se RAIOS ficou marcado."; }
        }
      }
      await esperar(400);
      var ta = Array.from(raiz.querySelectorAll("textarea"))[0];
      var texto = ta ? (ta.value || "").slice(0, 60) : "";
      if (falhas.length) avisoSite("⚠️ Preenchi o que deu, mas não achei: " + falhas.join("; ") + ". Complete à mão e salve.", "#b45309");
      else avisoSite("✅ Formulário preenchido (" + d.estacao.split(" - ")[0] + ", " + palavra + ", " + (d.nivel === "verde" ? "fim do alerta, +60 min" : d.minutos + " min") + "). Confira o texto e clique em 'Salvar alerta automático'." + avisoRaios, "#075e54");
    };
    var preencherBoletim = async function (d) {
      if (!/\/newsletter/.test(location.pathname)) { avisoSite("⚠️ Abra a página 'Histórico de Boletins' (/newsletter) e envie de novo pelo app.", "#b45309"); return; }
      var raiz = raizForm("novo boletim");
      raiz.scrollIntoView({ block: "center", behavior: "smooth" });
      var falhas = [];
      var selU = controlePorRotulo(raiz, "Unidade", { seletor: "select", indice: 0 });
      if (!selU || selU.tagName !== "SELECT") falhas.push("campo Unidade");
      else { var op = acharOpcao(selU, d.estacao); if (!op) falhas.push("unidade '" + d.estacao + "' não encontrada na lista"); else setarValor(selU, op.value); }
      await esperar(300);
      var selS = controlePorRotulo(raiz, "Status", { seletor: "select", indice: 1 });
      if (!selS || selS.tagName !== "SELECT") falhas.push("campo Status");
      else { var os = Array.from(selS.options).find(function (o) { return norm(o.textContent).indexOf(d.status) >= 0; }); if (!os) falhas.push("status " + d.status); else setarValor(selS, os.value); }
      var dt = controlePorRotulo(raiz, "Data e hora de emissão (Brasília)", { seletor: "input[type=datetime-local]", indice: 0 });
      if (!dt) falhas.push("campo Data e hora"); else setarValor(dt, partesSP(Date.now()));
      var textos = Array.from(raiz.querySelectorAll("input:not([type=datetime-local]):not([type=checkbox]):not([type=radio])"));
      var tit = controlePorRotulo(raiz, "Título", { seletor: "input:not([type=datetime-local])", indice: 0 }) || textos[0];
      var res = controlePorRotulo(raiz, "Resumo", { seletor: "input:not([type=datetime-local])", indice: 1 }) || textos[1];
      var tx = raiz.querySelector("textarea");
      if (!tit) falhas.push("campo Título"); else setarValor(tit, d.titulo);
      if (d.resumo) { if (!res) falhas.push("campo Resumo"); else setarValor(res, d.resumo); }
      if (!tx || tx.tagName !== "TEXTAREA") falhas.push("campo Texto"); else setarValor(tx, d.texto);
      await esperar(300);
      if (falhas.length) avisoSite("⚠️ Preenchi o que deu, mas não achei: " + falhas.join("; ") + ". Complete à mão e salve.", "#b45309");
      else avisoSite("✅ Boletim preenchido (" + d.estacao.split(" - ")[0] + ", status " + d.status + "). Confira e clique em 'Adicionar boletim'.", "#075e54");
      return falhas;
    };

    // ---------------- FILA DE BOLETINS NO SITE ----------------
    // Preenche um boletim por vez. Você confere e clica em "Adicionar boletim"; ao detectar que salvou
    // (o formulário limpou ou o título apareceu na lista) o script preenche o próximo. NUNCA clica em salvar.
    var painelFila = null, filaOcupada = false, esperandoSalvar = false;
    var lerFila = function () { try { return GM_getValue(CHAVE_FILA_SITE, null); } catch (e) { return null; } };
    var gravarFila = function (f) { f.ts = Date.now(); GM_setValue(CHAVE_FILA_SITE, f); };
    var marcarSalvo = function (id) {
      var pr = GM_getValue(CHAVE_PROG_SITE, { feitos: [] }); pr.feitos = (pr.feitos || []).filter(function (x) { return x !== id; }).concat([id]); pr.ts = Date.now();
      GM_setValue(CHAVE_PROG_SITE, pr);
    };
    var desenharPainel = function (msg, corMsg) {
      var f = lerFila();
      if (!f || !f.ativa) { if (painelFila) painelFila.style.display = "none"; return; }
      if (!painelFila) {
        painelFila = document.createElement("div");
        painelFila.style.cssText = "position:fixed;right:14px;bottom:14px;z-index:2147483646;width:320px;background:#10151d;color:#eaeaea;border:1px solid #1d70b8;border-radius:12px;padding:12px 14px;font:13px sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5)";
        document.body.appendChild(painelFila);
      }
      painelFila.style.display = "block";
      var total = f.itens.length, i = f.indice, it = f.itens[i];
      painelFila.textContent = "";
      var h = document.createElement("div"); h.style.cssText = "font-weight:700;font-size:14px;margin-bottom:4px";
      h.textContent = i >= total ? "📋 Fila concluída" : "📋 Fila de boletins — " + (i + 1) + " de " + total; painelFila.appendChild(h);
      var info = document.createElement("div"); info.style.cssText = "color:#b8c0cc;margin-bottom:6px";
      info.textContent = i >= total ? ("Salvos: " + f.salvos.length + " · Pulados: " + f.pulados.length) : ((it.estacao.split(" - ")[0]) + " · status " + it.status + " · salvos " + f.salvos.length);
      painelFila.appendChild(info);
      var barra = document.createElement("div"); barra.style.cssText = "height:6px;background:#232a36;border-radius:4px;margin-bottom:8px;overflow:hidden";
      var ml = document.createElement("div"); ml.style.cssText = "height:100%;background:#25d366;width:" + Math.round(100 * Math.min(i, total) / Math.max(total, 1)) + "%"; barra.appendChild(ml); painelFila.appendChild(barra);
      if (msg) { var m = document.createElement("div"); m.style.cssText = "margin-bottom:8px;color:" + (corMsg || "#ffd78a"); m.textContent = msg; painelFila.appendChild(m); }
      var linhaB = document.createElement("div"); linhaB.style.cssText = "display:flex;flex-wrap:wrap;gap:6px";
      function bt(txt, fn, cor) {
        var b = document.createElement("button"); b.textContent = txt;
        b.style.cssText = "cursor:pointer;border-radius:7px;border:1px solid #3a4150;background:" + (cor || "#232834") + ";color:#fff;padding:6px 10px;font:12.5px sans-serif";
        b.addEventListener("click", fn); linhaB.appendChild(b);
      }
      if (i < total) {
        bt("✔ Salvei → próximo", function () { avancarFila("salvo"); }, "#1d70b8");
        bt("↻ Preencher de novo", function () { preencherAtualFila(true); });
        bt("⏭ Pular", function () { avancarFila("pulado"); });
      }
      bt(i >= total ? "Fechar" : "⏹ Parar fila", function () { var g = lerFila(); if (g) { g.ativa = false; gravarFila(g); } desenharPainel(); });
      painelFila.appendChild(linhaB);
    };
    var avancarFila = function (como) {
      var f = lerFila(); if (!f || !f.ativa || f.indice >= f.itens.length) return;
      var it = f.itens[f.indice];
      if (como === "salvo") { f.salvos.push(it.id); marcarSalvo(it.id); } else f.pulados.push(it.id);
      f.indice++; f.clicou = -1; gravarFila(f); esperandoSalvar = false;
      desenharPainel();
      if (f.indice < f.itens.length) setTimeout(preencherAtualFila, 900);
      else avisoSite("✅ Fila concluída: " + f.salvos.length + " boletim(ns) salvo(s), " + f.pulados.length + " pulado(s).", "#075e54");
    };
    var preenchidoChave = "";
    var preencherAtualFila = async function (forcar) {
      var f = lerFila(); if (!f || !f.ativa || f.indice >= f.itens.length || filaOcupada) return;
      if (forcar !== true && preenchidoChave === f.id + ":" + f.indice) return;   // já preenchido nesta página: não sobrescreve o que você editou
      preenchidoChave = f.id + ":" + f.indice;
      if (!/\/newsletter/.test(location.pathname)) { desenharPainel("Abra a página 'Histórico de Boletins' (/newsletter) para continuar a fila."); return; }
      filaOcupada = true;
      try {
        var it = f.itens[f.indice];
        desenharPainel("Preenchendo…", "#9fd4ff");
        var falhas = await preencherBoletim(it);
        esperandoSalvar = true;
        desenharPainel(falhas && falhas.length ? ("Não achei: " + falhas.join("; ") + ". Complete à mão e salve.") : "Preenchido. Confira e clique em 'Adicionar boletim': a fila segue sozinha.", falhas && falhas.length ? "#ffd78a" : "#8de9b0");
      } finally { filaOcupada = false; }
    };
    // Detecta o clique em "Adicionar boletim" e confirma o salvamento (formulário limpou ou título apareceu na lista).
    document.addEventListener("click", function (ev) {
      var f = lerFila(); if (!f || !f.ativa || f.indice >= f.itens.length || !esperandoSalvar) return;
      var b = ev.target && ev.target.closest && ev.target.closest("button,input[type=submit],[role=button]");
      if (!b || b.closest && painelFila && painelFila.contains(b)) return;
      if (!/adicionar boletim/.test(norm(b.textContent || b.value || ""))) return;
      var it = f.itens[f.indice], id0 = f.id, idx0 = f.indice;
      f.clicou = idx0; f.clicouTs = Date.now(); gravarFila(f);   // se o site recarregar depois de salvar, a próxima carga sabe
      (async function () {
        var ok = await aguardar(function () {
          var g = lerFila(); if (!g || g.id !== id0 || g.indice !== idx0) return "x";
          var tx = document.querySelector("textarea");
          var limpou = !tx || String(tx.value || "").trim() === "";
          var naLista = Array.from(document.querySelectorAll("tr,li,article,[class*=card],[class*=item]")).some(function (e) {
            return !e.querySelector("textarea") && e.children.length < 40 && norm(e.textContent).indexOf(norm(it.titulo)) >= 0;
          });
          return limpou || naLista;
        }, 10000, 400);
        if (ok === true) avancarFila("salvo");
        else if (!ok) desenharPainel("Não confirmei que salvou (o site pode ter recusado). Corrija e salve de novo, ou use '✔ Salvei → próximo'.");
      })();
    }, true);
    GM_addValueChangeListener(CHAVE_FILA_SITE, function (nome, antigo, novo, remoto) {
      if (!remoto) return;
      esperandoSalvar = false; desenharPainel();
      if (novo && novo.ativa && novo.indice === 0) setTimeout(preencherAtualFila, 600);
    });
    setTimeout(async function () {   // ao abrir/recarregar o site com fila em andamento
      var f = lerFila();
      if (f && f.ativa && f.indice < f.itens.length && f.clicou === f.indice && Date.now() - (f.clicouTs || 0) < 30000) {
        // o site recarregou logo depois de "Adicionar boletim": confirma pelo título na lista e segue para o próximo
        var it0 = f.itens[f.indice];
        var visto = await aguardar(function () { return norm(document.body.textContent).indexOf(norm(it0.titulo)) >= 0; }, 8000, 500);
        if (visto) { avancarFila("salvo"); return; }
        desenharPainel("Não confirmei que o último boletim foi salvo. Use '✔ Salvei → próximo' se salvou, ou '↻ Preencher de novo'."); return;
      }
      if (f && f.ativa && f.indice < f.itens.length && Date.now() - (f.ts || 0) < 6 * 3600 * 1000) { desenharPainel(); preencherAtualFila(); }
      else if (f && f.ativa) desenharPainel();
    }, 1800);
    GM_addValueChangeListener(CHAVE_BOLETIM, function (nome, antigo, novo, remoto) {
      if (remoto && novo && novo.estacao) preencherBoletim(novo);
    });
    GM_addValueChangeListener(CHAVE_REGISTRO, function (nome, antigo, novo, remoto) {
      if (remoto && novo && novo.estacao) preencherSite(novo);
    });
    return;
  }

  // ------------------------------------------------------------------
  // LADO DO WHATSAPP WEB
  // ------------------------------------------------------------------
  var faixa = null;
  function aviso(msg, cor) {
    if (!faixa) {
      faixa = document.createElement("div");
      faixa.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;font:600 14px sans-serif;color:#fff;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.4);cursor:pointer;";
      faixa.title = "Clique para fechar";
      faixa.addEventListener("click", function () { faixa.style.display = "none"; });
      document.body.appendChild(faixa);
    }
    faixa.style.display = "block";
    faixa.style.background = cor || "#075e54";
    faixa.textContent = msg;
  }

  function caixaBusca() {
    // Na versão atual do WhatsApp Web a busca pode ser um <input> ou um campo editável; procura os dois.
    var todas = Array.prototype.slice.call(document.querySelectorAll('input, div[contenteditable="true"], [role="textbox"], [role="searchbox"]'))
      .filter(function (e) { return !e.closest("footer") && !e.closest("#main") && e.getBoundingClientRect().width > 0; });
    function rotulo(e) {
      return norm((e.getAttribute("aria-label") || "") + " " + (e.getAttribute("placeholder") || "") + " " + (e.getAttribute("title") || "") + " " + (e.getAttribute("data-tab") || ""));
    }
    var pref = todas.filter(function (e) { return /pesquis|search|conversa/.test(rotulo(e)); })[0];
    if (pref) return pref;
    // plano B: o campo mais alto na coluna da esquerda
    var esq = todas.filter(function (e) { return e.getBoundingClientRect().left < 500; })
      .sort(function (a, b) { return a.getBoundingClientRect().top - b.getBoundingClientRect().top; });
    return esq[0] || null;
  }
  function caixaMensagem() {
    return document.querySelector('#main footer div[contenteditable="true"]') || document.querySelector('footer div[contenteditable="true"]');
  }
  function limparEDigitar(el, texto) {
    el.focus();
    if (el.tagName === "INPUT" && el.select) el.select(); else document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
    if (texto) document.execCommand("insertText", false, texto);
  }
  function colar(el, texto) {
    el.focus();
    var dt = new DataTransfer();
    dt.setData("text/plain", texto);
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }
  function clicar(el) {
    ["mousedown", "mouseup", "click"].forEach(function (t) { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true })); });
  }
  function termosDaUnidade(estacao) {
    var lista = [];
    if (BUSCA_POR_UNIDADE[estacao]) lista.push(BUSCA_POR_UNIDADE[estacao]);
    var partes = String(estacao).split(" - ");
    lista.push(partes[0]);
    if (partes.length > 1) lista.push(partes[partes.length - 1]);
    lista.push(estacao);
    var vistos = {};
    return lista.filter(function (t) { t = t.trim(); var k = norm(t); if (!k || vistos[k]) return false; vistos[k] = 1; return true; });
  }

  var diag = { busca: false, itens: 0, amostra: [], cabecalho: "" };

  // Chats que aparecem na lista da esquerda (não conta o chat aberto nem o rodapé).
  function chatsVisiveis() {
    var vistos = [], saida = [];
    Array.prototype.slice.call(document.querySelectorAll("[title]")).forEach(function (el) {
      if (el.closest("#main") || el.closest("footer")) return;
      var t = el.getAttribute("title"); if (!t || t.length < 3) return;
      var linha = el.closest('[role="listitem"], [role="row"], [role="gridcell"]');
      if (!linha) return;
      if (vistos.indexOf(linha) !== -1) return;
      vistos.push(linha); saida.push({ titulo: t, linha: linha });
    });
    return saida;
  }
  function acharNaLista(termo) {
    var alvo = norm(termo);
    var todos = chatsVisiveis();
    diag.itens = todos.length; diag.amostra = todos.slice(0, 3).map(function (c) { return c.titulo; });
    var certos = todos.filter(function (c) { return norm(c.titulo).indexOf(alvo) !== -1; });
    if (!certos.length) return null;
    return certos.filter(function (c) { return norm(c.titulo).indexOf(PALAVRA_PREFERIDA) !== -1; })[0] || certos[0];
  }
  // Compara só letras e números: no cabeçalho o emoji (⚡) vira imagem e some do texto, e os espaços variam.
  function soAlnum(t) { return norm(t).replace(/[^a-z0-9]/g, ""); }
  function textoCabecalho() {
    var hs = Array.prototype.slice.call(document.querySelectorAll("header"));
    var h = hs.filter(function (e) { return e.getBoundingClientRect().left > 200; })[0] || document.querySelector("#main header");
    return h ? (h.innerText || "") : "";
  }
  function chatAbertoE(titulo) {
    var alvo = soAlnum(titulo);
    if (!alvo) return false;
    diag.cabecalho = textoCabecalho().replace(/\s+/g, " ").slice(0, 80);
    if (soAlnum(textoCabecalho()).indexOf(alvo) !== -1) return true;
    var m = document.querySelector("#main");
    return !!(m && soAlnum((m.innerText || "").slice(0, 800)).indexOf(alvo) !== -1);
  }

  async function abrirGrupo(termo) {
    // 1) tenta direto na lista visível; 2) se não achar, usa a busca do WhatsApp
    var chat = acharNaLista(termo);
    if (!chat) {
      var busca = caixaBusca();
      diag.busca = !!busca;
      if (!busca) return null;
      limparEDigitar(busca, termo);
      await esperar(900);
      chat = await aguardar(function () { return acharNaLista(termo); }, 4000, 250);
    }
    if (!chat) return null;
    clicar(chat.linha);
    var ok = await aguardar(function () { return chatAbertoE(chat.titulo); }, 4000, 200);
    return ok ? chat.titulo : null;
  }

  var ocupado = false;
  var fila = { pular: false, parar: false };

  // Prepara UMA mensagem: abre o grupo e deixa o texto digitado. Devolve o título do grupo, ou null se falhou
  // (nesse caso o texto fica copiado e um aviso aparece).
  async function prepararUm(dado, prefixo) {
    prefixo = prefixo || "";
    try {
      aviso("⏳ " + prefixo + "RIO Raios: procurando o grupo de " + dado.estacao.split(" - ")[0] + "…", "#334155");
      var titulo = null, termos = termosDaUnidade(dado.estacao);
      for (var i = 0; i < termos.length && !titulo; i++) titulo = await abrirGrupo(termos[i]);
      if (!titulo) {
        GM_setClipboard(dado.texto);
        aviso("⚠️ " + prefixo + "Não achei o grupo de " + dado.estacao + " (procurei: " + termos.join(" | ") + "). Texto COPIADO: abra o grupo e cole (Ctrl+V). [diag: caixa de busca " + (diag.busca ? "ok" : "não achada") + "; chats vistos " + diag.itens + (diag.amostra.length ? "; ex.: " + diag.amostra.join(" / ") : "") + "; cabeçalho lido: “" + diag.cabecalho + "”]", "#b45309");
        return null;
      }
      var cx = await aguardar(caixaMensagem, 4000, 200);
      if (!cx) { GM_setClipboard(dado.texto); aviso("⚠️ " + prefixo + "Grupo aberto (" + titulo + "), mas não achei a caixa de mensagem. Texto COPIADO: cole com Ctrl+V.", "#b45309"); return null; }
      colar(cx, dado.texto);
      await esperar(400);
      if (!(cx.innerText || "").trim()) {
        GM_setClipboard(dado.texto);
        aviso("⚠️ " + prefixo + "Grupo aberto (" + titulo + "), mas não consegui digitar. Texto COPIADO: cole com Ctrl+V.", "#b45309");
        return null;
      }
      cx.focus();
      aviso("✅ " + prefixo + "Mensagem pronta no grupo “" + titulo + "”. CONFIRA e aperte ENTER para enviar.", "#075e54");
      try { GM_notification({ title: "RIO Raios", text: "Mensagem pronta em " + titulo + ". Confira e aperte Enter.", timeout: 6000 }); } catch (e) {}
      return titulo;
    } catch (e) {
      GM_setClipboard(dado.texto);
      aviso("⚠️ " + prefixo + "Erro ao preparar a mensagem (" + e.message + "). Texto COPIADO: cole com Ctrl+V.", "#b91c1c");
      return null;
    }
  }

  async function preparar(dado) {
    if (ocupado) return;
    ocupado = true;
    try { await prepararUm(dado, ""); } finally { ocupado = false; }
  }

  // ---- Fila: prepara um grupo por vez; quando VOCÊ envia (a caixa esvazia), passa para o próximo.
  var barra = null;
  function mostrarBarraFila(mostrar) {
    if (!barra) {
      barra = document.createElement("div");
      barra.style.cssText = "position:fixed;top:44px;right:12px;z-index:2147483647;display:flex;gap:8px;";
      [["⏭ Pular este", function () { fila.pular = true; }], ["⏹ Parar fila", function () { fila.parar = true; }]].forEach(function (b) {
        var bt = document.createElement("button"); bt.textContent = b[0];
        bt.style.cssText = "padding:6px 12px;border-radius:8px;border:1px solid #fff;background:#1f2937;color:#fff;font:600 13px sans-serif;cursor:pointer;";
        bt.addEventListener("click", b[1]); barra.appendChild(bt);
      });
      document.body.appendChild(barra);
    }
    barra.style.display = mostrar ? "flex" : "none";
  }
  // Espera você enviar: devolve "enviado", "pulado", "parado" ou "saiu" (você abriu outro chat).
  async function aguardarEnvio(titulo) {
    while (true) {
      if (fila.parar) return "parado";
      if (fila.pular) { fila.pular = false; return "pulado"; }
      if (!chatAbertoE(titulo)) return "saiu";
      var cx = caixaMensagem();
      if (cx && !(cx.innerText || "").trim()) return "enviado";
      await esperar(500);
    }
  }
  async function rodarFila(itens) {
    if (ocupado) { aviso("⚠️ Já existe uma preparação em andamento. Termine ou recarregue a aba do WhatsApp.", "#b45309"); return; }
    ocupado = true; fila.pular = false; fila.parar = false;
    var enviados = [], pulados = [], falhas = [];
    mostrarBarraFila(true);
    try {
      for (var i = 0; i < itens.length; i++) {
        if (fila.parar) break;
        var it = itens[i], pref = "(" + (i + 1) + "/" + itens.length + ") ";
        var titulo = await prepararUm(it, pref);
        var nome = it.estacao.split(" - ")[0];
        if (!titulo) { falhas.push(nome); await esperar(2500); continue; }
        var r = await aguardarEnvio(titulo);
        if (r === "enviado") { enviados.push(nome); await esperar(800); }
        else if (r === "parado") break;
        else pulados.push(nome);
      }
      var resumo = (fila.parar ? "⏹ Fila interrompida. " : "🏁 Fila concluída. ") + "Enviados: " + enviados.length +
        (pulados.length ? " · Pulados: " + pulados.join(", ") : "") + (falhas.length ? " · Falhas (grupo não achado): " + falhas.join(", ") : "") + ".";
      aviso(resumo, falhas.length || pulados.length ? "#b45309" : "#075e54");
    } finally { mostrarBarraFila(false); ocupado = false; fila.parar = false; fila.pular = false; }
  }

  GM_addValueChangeListener(CHAVE, function (nome, antigo, novo, remoto) {
    if (remoto && novo && novo.texto) preparar(novo);
  });
  GM_addValueChangeListener(CHAVE_FILA, function (nome, antigo, novo, remoto) {
    if (remoto && novo && novo.itens && novo.itens.length) rodarFila(novo.itens);
  });
})();
