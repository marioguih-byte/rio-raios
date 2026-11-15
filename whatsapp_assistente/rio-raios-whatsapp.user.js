// ==UserScript==
// @name         RIO Raios → WhatsApp Web (assistente com supervisão)
// @namespace    rio-raios
// @version      1.6
// @description  Recebe o alerta do app RIO Raios, abre o grupo da unidade no WhatsApp Web e deixa a mensagem DIGITADA. Você confere e aperta Enter.
// @match        https://web.whatsapp.com/*
// @match        https://*.streamlit.app/*
// @match        http://localhost:*/*
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
  var ehWhatsApp = location.hostname === "web.whatsapp.com";

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
  if (!ehWhatsApp) {
    window.addEventListener("message", function (ev) {
      var d = ev.data;
      if (!d || d.fonte !== "rio-raios") return;
      if (d.tipo === "fila" && Array.isArray(d.itens)) {
        GM_setValue(CHAVE_FILA, { itens: d.itens.map(function (i) { return { estacao: String(i.estacao || ""), texto: String(i.texto || ""), id: String(i.id || "") }; }), ts: Date.now() });
        try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
        return;
      }
      if (d.tipo !== "preparar") return;
      GM_setValue(CHAVE, { estacao: String(d.estacao || ""), texto: String(d.texto || ""), id: String(d.id || ""), ts: Date.now() });
      try { ev.source && ev.source.postMessage({ fonte: "rio-raios-ack" }, "*"); } catch (e) {}
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
