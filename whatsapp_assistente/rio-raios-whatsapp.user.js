// ==UserScript==
// @name         RIO Raios → WhatsApp Web (assistente com supervisão)
// @namespace    rio-raios
// @version      1.0
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
    // "UTE Nova Piratininga - UTE UNP": "Nova Piratininga",
  };
  // Se TODOS os grupos tiverem a mesma palavra no nome (ex.: "ALERTAS"), ela é preferida quando houver mais de um resultado.
  var PALAVRA_PREFERIDA = "alertas";

  var CHAVE = "rio_envio";
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
      if (!d || d.fonte !== "rio-raios" || d.tipo !== "preparar") return;
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
    return document.querySelector('#side div[contenteditable="true"]') || document.querySelector('div[contenteditable="true"][data-tab="3"]');
  }
  function caixaMensagem() {
    return document.querySelector('#main footer div[contenteditable="true"]') || document.querySelector('footer div[contenteditable="true"]');
  }
  function limparEDigitar(el, texto) {
    el.focus();
    document.execCommand("selectAll", false, null);
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
    ["mousedown", "mouseup", "click"].forEach(function (t) { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })); });
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

  async function abrirGrupo(termo) {
    var busca = caixaBusca();
    if (!busca) return null;
    limparEDigitar(busca, termo);
    await esperar(900);
    var alvoNorm = norm(termo);
    var achados = await aguardar(function () {
      var spans = Array.prototype.slice.call(document.querySelectorAll("#pane-side span[title]"));
      var certos = spans.filter(function (s) { return norm(s.getAttribute("title")).indexOf(alvoNorm) !== -1; });
      return certos.length ? certos : null;
    }, 4000, 200);
    if (!achados) return null;
    var preferido = achados.filter(function (s) { return norm(s.getAttribute("title")).indexOf(PALAVRA_PREFERIDA) !== -1; })[0] || achados[0];
    var linha = preferido.closest('[role="listitem"], [role="row"], [role="gridcell"]') || preferido.parentElement;
    clicar(linha);
    var titulo = preferido.getAttribute("title");
    // confere que o chat aberto é mesmo esse
    var ok = await aguardar(function () {
      var h = document.querySelector("#main header span[title]");
      return h && norm(h.getAttribute("title")) === norm(titulo) ? h : null;
    }, 4000, 200);
    return ok ? titulo : null;
  }

  var ocupado = false;
  async function preparar(dado) {
    if (ocupado) return;
    ocupado = true;
    try {
      aviso("⏳ RIO Raios: procurando o grupo de " + dado.estacao.split(" - ")[0] + "…", "#334155");
      var titulo = null, termos = termosDaUnidade(dado.estacao);
      for (var i = 0; i < termos.length && !titulo; i++) titulo = await abrirGrupo(termos[i]);
      if (!titulo) {
        GM_setClipboard(dado.texto);
        aviso("⚠️ Não achei o grupo de " + dado.estacao + ". O texto foi COPIADO: abra o grupo e cole (Ctrl+V).", "#b45309");
        return;
      }
      var cx = await aguardar(caixaMensagem, 4000, 200);
      if (!cx) { GM_setClipboard(dado.texto); aviso("⚠️ Grupo aberto (" + titulo + "), mas não achei a caixa de mensagem. Texto COPIADO: cole com Ctrl+V.", "#b45309"); return; }
      colar(cx, dado.texto);
      await esperar(400);
      if (!(cx.innerText || "").trim()) {
        GM_setClipboard(dado.texto);
        aviso("⚠️ Grupo aberto (" + titulo + "), mas não consegui digitar. Texto COPIADO: cole com Ctrl+V.", "#b45309");
        return;
      }
      cx.focus();
      aviso("✅ Mensagem pronta no grupo “" + titulo + "”. CONFIRA e aperte ENTER para enviar.", "#075e54");
      try { GM_notification({ title: "RIO Raios", text: "Mensagem pronta em " + titulo + ". Confira e aperte Enter.", timeout: 6000 }); } catch (e) {}
    } catch (e) {
      GM_setClipboard(dado.texto);
      aviso("⚠️ Erro ao preparar a mensagem (" + e.message + "). Texto COPIADO: cole com Ctrl+V.", "#b91c1c");
    } finally { ocupado = false; }
  }

  GM_addValueChangeListener(CHAVE, function (nome, antigo, novo, remoto) {
    if (remoto && novo && novo.texto) preparar(novo);
  });
})();
