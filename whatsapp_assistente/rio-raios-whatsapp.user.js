// ==UserScript==
// @name         RIO Raios → WhatsApp Web (assistente com supervisão)
// @namespace    rio-raios
// @version      2.8
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
// @grant        unsafeWindow
// @run-at       document-idle
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

  // Texto do campo "Texto" do site no modo Manual (o mesmo padrão do modo Automático). Se o seu for diferente, edite aqui.
  var TEXTO_SITE = {
    vermelho: "Raios próximos de sua região (-15 min até o momento)",
    amarelo: "Raios próximos de sua região (-30 min até o momento)",
    verde: "FIM DO ALERTA DE RAIOS"
  };
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
      d.textContent = "🤖 RIO Assistente v2.8 ativo (" + (ehWhatsApp ? "WhatsApp" : ehSite ? "site BlueOcean" : "app RIO") + ")";
      d.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:6px 12px;border-radius:8px;background:#075e54;color:#fff;font:600 12px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4);transition:opacity .6s;";
      document.body.appendChild(d);
      setTimeout(function () { d.style.opacity = "0"; }, 6400);
      setTimeout(function () { d.remove(); }, 7000);
    }
    if (document.body) mostrar(); else document.addEventListener("DOMContentLoaded", mostrar);
  })();

  function norm(t) {
    return String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  }
  function esperar(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // Aviso no canto inferior direito: some sozinho em 7 s (o mouse em cima pausa a contagem) e fecha no ✕ ou clicando nele.
  var toastEl = null, toastTimer = null;
  function toast(msg, cor) {
    if (!document.body) return;
    if (!toastEl || !toastEl.isConnected) {
      toastEl = document.createElement("div");
      toastEl.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:380px;box-sizing:border-box;padding:12px 34px 12px 14px;border-radius:10px;font:600 13px/1.4 sans-serif;color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.45);cursor:pointer;word-break:break-word;";
      toastEl.title = "Clique para fechar";
      var x = document.createElement("span"); x.textContent = "✕";
      x.style.cssText = "position:absolute;top:6px;right:10px;font-size:14px;opacity:.85;";
      toastEl.appendChild(x);
      toastEl._msg = document.createElement("span"); toastEl.insertBefore(toastEl._msg, x);
      toastEl.addEventListener("click", function () { toastEl.style.display = "none"; clearTimeout(toastTimer); });
      toastEl.addEventListener("mouseenter", function () { clearTimeout(toastTimer); });
      toastEl.addEventListener("mouseleave", function () { armar(); });
      document.body.appendChild(toastEl);
    }
    function armar() { clearTimeout(toastTimer); toastTimer = setTimeout(function () { if (toastEl) toastEl.style.display = "none"; }, 7000); }
    toastEl.style.background = cor || "#075e54";
    toastEl._msg.textContent = msg;
    toastEl.style.display = "block";
    armar();
  }
  async function aguardar(fn, ms, passo) {
    var fim = Date.now() + ms;
    while (Date.now() < fim) { var v = fn(); if (v) return v; await esperar(passo || 150); }
    return null;
  }

  // ------------------------------------------------------------------
  // COMPATIBILIDADE (Chrome, Edge, Brave, Firefox, Opera, Safari com Tampermonkey/Violentmonkey)
  // ------------------------------------------------------------------
  var ABA = Math.random().toString(36).slice(2) + Date.now().toString(36);   // identifica esta aba
  function gSet(k, v) { try { GM_setValue(k, v); return true; } catch (e) { return false; } }
  function gGet(k, padrao) { try { var v = GM_getValue(k, padrao); return v === undefined ? padrao : v; } catch (e) { return padrao; } }
  // Avisa quando o valor muda em OUTRA aba. Se o gerenciador de scripts não tem o "ouvinte", consulta a cada 1 s.
  function onMudou(chave, fn) {
    function seguro(a, b, c, d) { try { fn(a, b, c, d); } catch (e) { try { console.error("[RIO]", e); } catch (x) {} } }
    if (typeof GM_addValueChangeListener === "function") {
      try { GM_addValueChangeListener(chave, seguro); return; } catch (e) {}
    }
    var ultimo = JSON.stringify(gGet(chave, null));
    setInterval(function () {
      var v = gGet(chave, null), j = JSON.stringify(v);
      if (j !== ultimo) { ultimo = j; seguro(chave, null, v, true); }
    }, 1000);
  }
  // Só UMA aba trata cada pedido (se houver 2 abas do WhatsApp/site abertas, não duplica).
  async function reivindicar(nome, ts) {
    var k = "rio_claim_" + nome;
    gSet(k, { ts: ts, aba: ABA });
    await esperar(300 + Math.floor(Math.random() * 120));
    var c = gGet(k, null);
    return !c || c.ts !== ts || c.aba === ABA;
  }
  // Copia para a área de transferência sem depender de um único método.
  function copiarTexto(t) {
    try { if (typeof GM_setClipboard === "function") { GM_setClipboard(t); return; } } catch (e) {}
    try { navigator.clipboard.writeText(t); return; } catch (e) {}
    try {
      var x = document.createElement("textarea"); x.value = t; x.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(x); x.select(); document.execCommand("copy"); document.body.removeChild(x);
    } catch (e) {}
  }

  // ------------------------------------------------------------------
  // LADO DO APP (streamlit): repassa a mensagem do mapa para a aba do WhatsApp
  // ------------------------------------------------------------------
  if (!ehWhatsApp && !ehSite) {
    window.addEventListener("message", function (ev) {
      try { tratarMensagemApp(ev); } catch (e) { try { console.error("[RIO]", e); } catch (x) {} }
    });
    function tratarMensagemApp(ev) {
      var d = ev.data;
      if (!d || d.fonte !== "rio-raios") return;
      if (d.tipo === "fila" && Array.isArray(d.itens)) {
        gSet(CHAVE_FILA, { itens: d.itens.map(function (i) { return { estacao: String(i.estacao || ""), texto: String(i.texto || ""), id: String(i.id || "") }; }), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "registrar") {
        gSet(CHAVE_REGISTRO, { estacao: String(d.estacao || ""), nivel: String(d.nivel || "vermelho"), minutos: parseInt(d.minutos, 10) || 60,
                               texto: String(d.texto || ""), meteorologista: String(d.meteorologista || ""), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "fila_site" && Array.isArray(d.itens)) {
        gSet(CHAVE_PROG_SITE, { feitos: [], ts: Date.now() });
        gSet(CHAVE_FILA_SITE, { id: String(Date.now()), indice: 0, ativa: true, pulados: [], salvos: [], ts: Date.now(),
          itens: d.itens.map(function (i) { return { id: String(i.id || ""), estacao: String(i.estacao || ""), status: String(i.status || "verde"),
                                                  titulo: String(i.titulo || ""), resumo: String(i.resumo || ""), texto: String(i.texto || "") }; }) });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo === "boletim") {
        gSet(CHAVE_BOLETIM, { estacao: String(d.estacao || ""), status: String(d.status || "verde"), titulo: String(d.titulo || ""),
                                     resumo: String(d.resumo || ""), texto: String(d.texto || ""), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo !== "preparar") return;
      gSet(CHAVE, { estacao: String(d.estacao || ""), texto: String(d.texto || ""), id: String(d.id || ""),
                    legenda: String(d.legenda || ""), png: String(d.png || ""), ts: Date.now() });
      try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
    }
    // O site avisa quais boletins foram salvos: repassa a todos os quadros (iframes) do app para marcar o check "Site".
    function espalhar(win, msg, nivel) {
      try { win.postMessage(msg, "*"); } catch (e) {}
      if (nivel > 3) return;
      var n = 0; try { n = win.length; } catch (e) {}
      for (var i = 0; i < n; i++) { try { espalhar(win.frames[i], msg, nivel + 1); } catch (e) {} }
    }
    onMudou(CHAVE_PROG_SITE, function (nome, antigo, novo, remoto) {
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
    var avisoSite = function (msg, cor) { toast(msg, cor); };
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
    var ocupadoSite = false;
    var preencherSite = async function (d) {
      if (!/\/alerts/.test(location.pathname)) { avisoSite("⚠️ Abra a página 'Registro de eventos críticos' (/alerts) e envie de novo pelo app.", "#b45309"); return; }
      if (ocupadoSite) return;
      ocupadoSite = true;
      try {
        var raiz = raizForm();
        raiz.scrollIntoView({ block: "center", behavior: "smooth" });
        var falhas = [];
        var agora = Date.now();
        var minVenc = d.nivel === "verde" ? 60 : (parseInt(d.minutos, 10) || 60);   // alerta verde: sempre 1 hora a partir de agora
        var palavra = { verde: "verde", amarelo: "amarelo", vermelho: "vermelho" }[d.nivel] || "vermelho";
        // O formulário tem dois modos: "Manual" (Unidade, Data e hora, Vencimento, Meteorologista, Tipo de alerta, Nível, Texto)
        // e "Automático" (Unidade, Início, Vencimento, Nível, parâmetro RAIOS). Detecta qual está aberto.
        var selTipo = controlePorRotulo(raiz, "Tipo de alerta", null);
        var campoMet = controlePorRotulo(raiz, "Meteorologista", null);
        var manual = !!(selTipo && selTipo.tagName === "SELECT");
        // 1) Unidade
        var selU = controlePorRotulo(raiz, "Unidade", { seletor: "select", indice: 0 });
        if (!selU || selU.tagName !== "SELECT") falhas.push("campo Unidade");
        else {
          var op = acharOpcao(selU, d.estacao);
          if (!op) falhas.push("unidade '" + d.estacao + "' não encontrada na lista"); else setarValor(selU, op.value);
        }
        await esperar(300);
        // 2) Datas (início = agora em Brasília; vencimento = início + validade)
        var ini = controlePorRotulo(raiz, "Data e hora", null) || controlePorRotulo(raiz, "Início", { seletor: "input[type=datetime-local]", indice: 0 });
        if (!ini) falhas.push("campo Data e hora"); else setarValor(ini, partesSP(agora));
        var ven = controlePorRotulo(raiz, "Vencimento", { seletor: "input[type=datetime-local]", indice: 1 });
        if (!ven) falhas.push("campo Vencimento"); else setarValor(ven, partesSP(agora + minVenc * 60000));
        await esperar(200);
        // 3) Meteorologista = nome cadastrado no RIO (só no modo manual)
        if (campoMet && campoMet.tagName === "INPUT" && d.meteorologista) setarValor(campoMet, d.meteorologista);
        else if (manual && d.meteorologista) falhas.push("campo Meteorologista");
        // 4) Tipo de alerta = Raios (modo manual)
        if (manual) {
          var oTipo = Array.from(selTipo.options).find(function (o) { return norm(o.textContent) === "raios"; }) ||
                      Array.from(selTipo.options).find(function (o) { return norm(o.textContent).indexOf("raio") >= 0; });
          if (!oTipo) falhas.push("tipo 'Raios'"); else setarValor(selTipo, oTipo.value);
          await esperar(200);
        }
        // 5) Nível
        var selN = controlePorRotulo(raiz, "Nível", { seletor: "select", indice: manual ? 2 : 1 });
        if (!selN || selN.tagName !== "SELECT") falhas.push("campo Nível");
        else {
          var on = Array.from(selN.options).find(function (o) { return norm(o.textContent).indexOf(palavra) >= 0; });
          if (!on) falhas.push("nível " + palavra); else setarValor(selN, on.value);
        }
        await esperar(300);
        // 6) Modo automático: parâmetro RAIOS sempre marcado (inclusive no alerta verde)
        var avisoRaios = "";
        if (!manual) {
          var bt = Array.from(raiz.querySelectorAll("button,label,[role=button],[role=checkbox]")).find(function (e) { return norm(e.textContent) === "raios"; });
          if (!bt) falhas.push("botão RAIOS");
          else {
            var ligado = estaLigado(bt);
            if (ligado === false || ligado === null) { bt.click(); if (ligado === null) avisoRaios = " Confira se RAIOS ficou marcado."; }
          }
          await esperar(400);
        }
        // 7) Texto = a mensagem do alerta (modo manual)
        if (manual) {
          var ta = raiz.querySelector("textarea");
          if (!ta) falhas.push("campo Texto"); else setarValor(ta, TEXTO_SITE[d.nivel] || TEXTO_SITE.vermelho);
        }
        var botao = manual ? "Registrar evento" : "Salvar alerta automático";
        if (falhas.length) avisoSite("⚠️ Preenchi o que deu, mas não achei: " + falhas.join("; ") + ". Complete à mão e salve.", "#b45309");
        else avisoSite("✅ Formulário " + (manual ? "manual" : "automático") + " preenchido (" + d.estacao.split(" - ")[0] + ", " + palavra + ", " + (d.nivel === "verde" ? "fim do alerta, +60 min" : minVenc + " min") + (manual && d.meteorologista ? ", meteorologista " + d.meteorologista : "") + "). Confira e clique em '" + botao + "'." + avisoRaios, "#075e54");
      } catch (e) {
        avisoSite("⚠️ Erro ao preencher o formulário (" + (e && e.message) + "). Preencha à mão.", "#b91c1c");
      } finally { ocupadoSite = false; }
    };
    var preencherBoletimInterno = async function (d) {
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

    var preencherBoletim = async function (d) {
      try { return await preencherBoletimInterno(d); }
      catch (e) { avisoSite("⚠️ Erro ao preencher o boletim (" + (e && e.message) + "). Preencha à mão.", "#b91c1c"); return ["erro: " + (e && e.message)]; }
    };
    // ---------------- FILA DE BOLETINS NO SITE ----------------
    // Preenche um boletim por vez. Você confere e clica em "Adicionar boletim"; ao detectar que salvou
    // (o formulário limpou ou o título apareceu na lista) o script preenche o próximo. NUNCA clica em salvar.
    var painelFila = null, filaOcupada = false, esperandoSalvar = false;
    var lerFila = function () { try { return gGet(CHAVE_FILA_SITE, null); } catch (e) { return null; } };
    var gravarFila = function (f) { f.ts = Date.now(); gSet(CHAVE_FILA_SITE, f); };
    var marcarSalvo = function (id) {
      var pr = gGet(CHAVE_PROG_SITE, { feitos: [] }); pr.feitos = (pr.feitos || []).filter(function (x) { return x !== id; }).concat([id]); pr.ts = Date.now();
      gSet(CHAVE_PROG_SITE, pr);
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
    onMudou(CHAVE_FILA_SITE, function (nome, antigo, novo, remoto) {
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
    var tratadoSite = {};
    onMudou(CHAVE_BOLETIM, async function (nome, antigo, novo, remoto) {
      if (!remoto || !novo || !novo.estacao || tratadoSite["b" + novo.ts]) return;
      tratadoSite["b" + novo.ts] = 1;
      if (await reivindicar("boletim", novo.ts)) preencherBoletim(novo);
    });
    onMudou(CHAVE_REGISTRO, async function (nome, antigo, novo, remoto) {
      if (!remoto || !novo || !novo.estacao || tratadoSite["r" + novo.ts]) return;
      tratadoSite["r" + novo.ts] = 1;
      if (await reivindicar("registro", novo.ts)) preencherSite(novo);
    });
    return;
  }

  // ------------------------------------------------------------------
  // LADO DO WHATSAPP WEB
  // ------------------------------------------------------------------
  var faixa = null;
  function aviso(msg, cor) { toast(msg, cor); }

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
  function colar(el, texto, janela) {
    var W = janela || window;
    el.focus();
    var dt = new W.DataTransfer();
    dt.setData("text/plain", texto);
    el.dispatchEvent(new W.ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }
  var textoDaCaixa = function (cx) { return (cx.innerText || "").replace(/\s+/g, ""); };
  // Esvazia a caixa de mensagem (rascunho antigo, texto de tentativa anterior) e confirma que ficou vazia.
  function limparCaixa(cx) {
    cx.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
    if (textoDaCaixa(cx)) {
      try {
        var sel = window.getSelection(), r = document.createRange();
        r.selectNodeContents(cx); sel.removeAllRanges(); sel.addRange(r);
        document.execCommand("delete", false, null);
      } catch (e) {}
    }
    return !textoDaCaixa(cx);
  }
  // Pula linha como o WhatsApp espera: Shift+Enter (o insertLineBreak do Firefox é ignorado pela caixa).
  function quebraDeLinha(cx) {
    var op = { key: "Enter", code: "Enter", keyCode: 13, which: 13, shiftKey: true, bubbles: true, cancelable: true };
    var ev = new KeyboardEvent("keydown", op);
    var livre = cx.dispatchEvent(ev);
    if (livre) { document.execCommand("insertLineBreak", false, null); }
    cx.dispatchEvent(new KeyboardEvent("keyup", op));
  }
  // Coloca o texto na caixa de mensagem tentando 3 jeitos (o Firefox não aceita o "colar" simulado do Chrome):
  // 1) linha a linha com insertText + quebra de linha (o mesmo jeito que já digita na busca de grupos), 2) colar simulado
  // com objetos da página, 3) colar simulado do script. Confere se o texto entrou antes de aceitar.
  async function inserirTexto(cx, texto) {
    var alvo = texto.replace(/\s+/g, "").length, diag = [];
    var W = (typeof unsafeWindow !== "undefined" && unsafeWindow) ? unsafeWindow : window;
    var estrategias = [
      ["linhas", async function () {
        cx.focus();
        var ls = texto.split("\n");
        for (var i = 0; i < ls.length; i++) {
          if (ls[i]) document.execCommand("insertText", false, ls[i]);
          if (i < ls.length - 1) quebraDeLinha(cx);
        }
      }],
      ["colar-pagina", async function () { colar(cx, texto, W); }],
      ["colar", async function () { colar(cx, texto, window); }]
    ];
    for (var k = 0; k < estrategias.length; k++) {
      // SEMPRE começa com a caixa vazia: assim a mensagem nunca sai repetida/emendada com texto anterior.
      if (!limparCaixa(cx)) { diag.push("não consegui esvaziar a caixa antes de " + estrategias[k][0]); break; }
      try {
        await estrategias[k][1]();
      } catch (e) { diag.push(estrategias[k][0] + ":erro " + (e && e.message)); continue; }
      await esperar(350);
      var got = textoDaCaixa(cx).length;
      var quebras = (cx.innerText || "").split("\n").filter(function (x) { return x.trim(); }).length;
      var esperadas = texto.split("\n").filter(function (x) { return x.trim(); }).length;
      if (got >= alvo * 0.9 && got <= alvo * 1.15 && quebras >= Math.min(esperadas, 2)) return { ok: true, via: estrategias[k][0] };
      diag.push(estrategias[k][0] + ":" + got + "/" + alvo + " linhas:" + quebras + "/" + esperadas);
    }
    limparCaixa(cx);
    return { ok: false, diag: diag.join(" ") };
  }

  // ------------------------------------------------------------------
  // IMAGEM (boletim horário): cola o PNG na caixa do grupo (abre a pré-visualização do WhatsApp) e escreve a legenda.
  // ------------------------------------------------------------------
  function criarArquivoPng(b64, W) {
    var bin = atob(b64), n = bin.length, u8;
    try { u8 = new W.Uint8Array(n); } catch (e) { u8 = new Uint8Array(n); }
    for (var i = 0; i < n; i++) u8[i] = bin.charCodeAt(i);
    try { return new W.File([u8], "boletim-horario.png", { type: "image/png" }); }
    catch (e) { return new File([u8], "boletim-horario.png", { type: "image/png" }); }
  }
  function visivel(e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
  // Caixa de legenda da pré-visualização: um campo editável FORA do rodapé e da lista de conversas.
  function caixaLegenda() {
    return Array.from(document.querySelectorAll('div[contenteditable="true"], [contenteditable="plaintext-only"]')).filter(function (e) {
      return !e.closest("footer") && !e.closest("#side") && visivel(e);
    })[0] || null;
  }
  async function colarImagem(cx, b64) {
    var W = (typeof unsafeWindow !== "undefined" && unsafeWindow) ? unsafeWindow : window, tentativas = [], diag = [];
    function dtCom(Win) { var dt = new Win.DataTransfer(); dt.items.add(criarArquivoPng(b64, Win)); return dt; }
    tentativas.push(["colar-pagina", function () { cx.focus(); cx.dispatchEvent(new W.ClipboardEvent("paste", { clipboardData: dtCom(W), bubbles: true, cancelable: true })); }]);
    tentativas.push(["colar", function () { cx.focus(); cx.dispatchEvent(new window.ClipboardEvent("paste", { clipboardData: dtCom(window), bubbles: true, cancelable: true })); }]);
    tentativas.push(["arrastar", function () {
      var alvo = document.querySelector("#main") || cx, dt = dtCom(W);
      ["dragenter", "dragover", "drop"].forEach(function (t) { alvo.dispatchEvent(new W.DragEvent(t, { dataTransfer: dt, bubbles: true, cancelable: true })); });
    }]);
    for (var k = 0; k < tentativas.length; k++) {
      try { tentativas[k][1](); } catch (e) { diag.push(tentativas[k][0] + ":erro " + (e && e.message)); continue; }
      var cap = await aguardar(caixaLegenda, 3500, 200);
      if (cap) return { ok: true, via: tentativas[k][0], cap: cap };
      diag.push(tentativas[k][0] + ":sem pré-visualização");
    }
    return { ok: false, diag: diag.join(" ") };
  }
  // Último recurso: deixa a imagem na área de transferência (Ctrl+V manual) e espera a pré-visualização aparecer.
  async function imagemNaAreaDeTransferencia(b64) {
    try {
      var bin = atob(b64), u8 = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      await navigator.clipboard.write([new ClipboardItem({ "image/png": new Blob([u8], { type: "image/png" }) })]);
      return true;
    } catch (e) { return false; }
  }
  var tokenSegunda = 0;
  // Depois que VOCÊ envia a imagem (a pré-visualização fecha), deixa o "Hora a hora" digitado como 2ª mensagem.
  async function segundaMensagem(titulo, cap, texto, token) {
    var t0 = Date.now();
    while (Date.now() - t0 < 600000) {
      if (token !== tokenSegunda) return;
      if (!chatAbertoE(titulo)) return;
      if (!cap.isConnected || !visivel(cap)) break;
      await esperar(500);
    }
    if (token !== tokenSegunda || !chatAbertoE(titulo)) return;
    await esperar(1200);
    var cx = await aguardar(caixaMensagem, 4000, 200);
    if (!cx) { copiarTexto(texto); aviso("⚠️ Imagem enviada. Não achei a caixa para o “Hora a hora” — texto COPIADO: cole com Ctrl+V.", "#b45309"); return; }
    var ins = await inserirTexto(cx, texto);
    if (!ins.ok) { copiarTexto(texto); aviso("⚠️ Não consegui digitar o “Hora a hora”. Texto COPIADO: cole com Ctrl+V.", "#b45309"); return; }
    cx.focus();
    aviso("✅ 2ª mensagem (Hora a hora) pronta em “" + titulo + "”. Aperte ENTER para enviar.", "#075e54");
  }
  // Prepara imagem + legenda (+ texto seguinte). Devolve true se a imagem entrou.
  async function prepararImagem(cx, dado, titulo, prefixo) {
    var legenda = dado.legenda || dado.texto || "", resto = dado.legenda ? (dado.texto || "") : "";
    if (!limparCaixa(cx)) return false;
    var r = await colarImagem(cx, dado.png);
    if (!r.ok) {
      var copiada = await imagemNaAreaDeTransferencia(dado.png);
      aviso("🖼 " + prefixo + "Não consegui colar a imagem sozinho." + (copiada ? " Ela está COPIADA: aperte Ctrl+V na caixa do grupo — eu escrevo a legenda." : " Baixe o PNG no app e anexe.") + " [diag: " + r.diag + "]", "#b45309");
      if (!copiada) { copiarTexto(legenda + (resto ? "\n\n" + resto : "")); return false; }
      var cap2 = await aguardar(caixaLegenda, 90000, 300);
      if (!cap2) { copiarTexto(legenda + (resto ? "\n\n" + resto : "")); aviso("⚠️ A imagem não foi colada. Texto COPIADO: cole com Ctrl+V.", "#b45309"); return false; }
      r = { ok: true, via: "manual", cap: cap2 };
    }
    var ins = await inserirTexto(r.cap, legenda);
    if (!ins.ok) { copiarTexto(legenda); aviso("⚠️ " + prefixo + "Imagem colada, mas não consegui escrever a legenda. Legenda COPIADA: cole com Ctrl+V. [diag: " + ins.diag + "]", "#b45309"); }
    else r.cap.focus();
    aviso("✅ " + prefixo + "Imagem + legenda prontas no grupo “" + titulo + "”. CONFIRA e aperte ENTER" + (resto ? " (depois deixo o Hora a hora pronto)" : "") + ".", "#075e54");
    try { GM_notification({ title: "RIO Raios", text: "Imagem pronta em " + titulo + ". Confira e aperte Enter.", timeout: 6000 }); } catch (e) {}
    if (resto) { var tk = ++tokenSegunda; segundaMensagem(titulo, r.cap, resto, tk); }
    return true;
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
        copiarTexto(dado.texto);
        aviso("⚠️ " + prefixo + "Não achei o grupo de " + dado.estacao + " (procurei: " + termos.join(" | ") + "). Texto COPIADO: abra o grupo e cole (Ctrl+V). [diag: caixa de busca " + (diag.busca ? "ok" : "não achada") + "; chats vistos " + diag.itens + (diag.amostra.length ? "; ex.: " + diag.amostra.join(" / ") : "") + "; cabeçalho lido: “" + diag.cabecalho + "”]", "#b45309");
        return null;
      }
      var cx = await aguardar(caixaMensagem, 4000, 200);
      if (!cx) { copiarTexto(dado.texto); aviso("⚠️ " + prefixo + "Grupo aberto (" + titulo + "), mas não achei a caixa de mensagem. Texto COPIADO: cole com Ctrl+V.", "#b45309"); return null; }
      if (dado.png) {
        var okImg = await prepararImagem(cx, dado, titulo, prefixo);
        if (okImg) return titulo;
        // sem imagem: segue o fluxo normal só com texto (legenda + hora a hora)
        dado = { estacao: dado.estacao, id: dado.id, texto: (dado.legenda ? dado.legenda + (dado.texto ? "\n\n" + dado.texto : "") : dado.texto) };
      }
      var ins = await inserirTexto(cx, dado.texto);
      if (!ins.ok) {
        copiarTexto(dado.texto);
        aviso("⚠️ " + prefixo + "Grupo aberto (" + titulo + "), mas não consegui digitar. Texto COPIADO: cole com Ctrl+V. [diag: " + ins.diag + "]", "#b45309");
        return null;
      }
      // O WhatsApp às vezes redesenha a caixa logo depois de abrir o grupo (rascunho salvo): confere de novo e corrige.
      await esperar(700);
      var alvoLen = dado.texto.replace(/\s+/g, "").length, cx2 = caixaMensagem() || cx, atualLen = textoDaCaixa(cx2).length;
      if (atualLen < alvoLen * 0.9 || atualLen > alvoLen * 1.15) {
        ins = await inserirTexto(cx2, dado.texto);
        if (!ins.ok) {
          copiarTexto(dado.texto);
          aviso("⚠️ " + prefixo + "Grupo aberto (" + titulo + "), mas a mensagem não ficou certa. Texto COPIADO: cole com Ctrl+V. [diag: " + ins.diag + "]", "#b45309");
          return null;
        }
        cx = cx2;
      }
      cx.focus();
      aviso("✅ " + prefixo + "Mensagem pronta no grupo “" + titulo + "”. CONFIRA e aperte ENTER para enviar.", "#075e54");
      try { GM_notification({ title: "RIO Raios", text: "Mensagem pronta em " + titulo + ". Confira e aperte Enter.", timeout: 6000 }); } catch (e) {}
      return titulo;
    } catch (e) {
      copiarTexto(dado.texto);
      aviso("⚠️ " + prefixo + "Erro ao preparar a mensagem (" + e.message + "). Texto COPIADO: cole com Ctrl+V.", "#b91c1c");
      return null;
    }
  }

  var ultimoPedido = { chave: "", t: 0 };
  async function preparar(dado) {
    if (ocupado) return;
    // Mesmo pedido (mesmo alerta e mesmo texto) repetido em poucos segundos = duplicado: ignora.
    var chave = String(dado.id || "") + "|" + String(dado.texto || "") + "|" + String(dado.legenda || "") + "|" + (dado.png ? dado.png.length : 0);
    if (chave === ultimoPedido.chave && Date.now() - ultimoPedido.t < 20000) return;
    ultimoPedido = { chave: chave, t: Date.now() };
    ocupado = true;
    try { await prepararUm(dado, ""); } finally { ocupado = false; ultimoPedido.t = Date.now(); }
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

  var tratadoWA = {};
  onMudou(CHAVE, async function (nome, antigo, novo, remoto) {
    if (!remoto || !novo || !(novo.texto || novo.legenda) || tratadoWA["p" + novo.ts]) return;
    tratadoWA["p" + novo.ts] = 1;
    if (await reivindicar("preparar", novo.ts)) preparar(novo);   // só uma aba do WhatsApp trata cada pedido
  });
  onMudou(CHAVE_FILA, async function (nome, antigo, novo, remoto) {
    if (!remoto || !novo || !novo.itens || !novo.itens.length || tratadoWA["f" + novo.ts]) return;
    tratadoWA["f" + novo.ts] = 1;
    if (await reivindicar("fila", novo.ts)) rodarFila(novo.itens);
  });
})();
