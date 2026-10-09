/* 组合麻将 — 联机客户端 (照搬 mmcr14.online 的信封协议/快照/事件/stage 幂等)
 *
 * 用法:
 *   /game?mp=1              联机对局(需已登录且已在大厅里开局)
 *   /game?spectate=<sid>    观战某场对局
 *
 * 设计:
 * - 与服务端统一使用信封 {version,type,payload,requestId}; 收到 ack/error 按 requestId 回调
 * - 直接消费 session.snapshot / game.event, 适配成 main.js 既有的 state 形状后复用其渲染
 * - 每次输入都带 stage_counter(取最近一次的阶段号) → 服务端幂等校验, 过期的自动丢弃
 * - 断线自动重连并重新拉全量快照(不依赖补发中间消息)
 */
(function () {
  var QS = new URLSearchParams(location.search);
  var MP_MODE = QS.get("mp") === "1";
  var SPECTATE_SID = QS.get("spectate");
  if (!MP_MODE && !SPECTATE_SID) return;   // 单人/冒险模式不接管

  var BASE = (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host;
  var TOKEN = localStorage.getItem("mj_token") || "";
  var REQ_SEQ = 0, PENDING = {};
  var sock = null, RETRY = 0, STAGE = 0, MY_SEAT = -1, CUR = null;
  var SHOWN_OVER = false, LAST_ROUND = 0, PING_TIMER = null;

  window.MP_ACTIVE = true;
  if (typeof window.over !== "function") window.over = function () {};

  function E(id) { return document.getElementById(id); }

  function toast(msg, ok) {
    var d = E("mp-toast");
    if (!d) {
      d = document.createElement("div");
      d.id = "mp-toast";
      d.style.cssText = "position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:99999;" +
        "padding:9px 20px;border-radius:10px;font-size:13px;font-weight:600;transition:opacity .3s;opacity:0";
      document.body.appendChild(d);
    }
    d.textContent = msg;
    d.style.background = ok ? "rgba(0,229,255,.14)" : "rgba(255,82,82,.16)";
    d.style.border = "1px solid " + (ok ? "rgba(0,229,255,.4)" : "rgba(255,82,82,.45)");
    d.style.color = ok ? "#00e5ff" : "#ff8a80";
    d.style.opacity = "1";
    clearTimeout(d._t);
    d._t = setTimeout(function () { d.style.opacity = "0"; }, 2200);
  }

  function overlay(html) {
    var ov = E("mp-overlay");
    if (!ov) {
      ov = document.createElement("div");
      ov.id = "mp-overlay";
      ov.style.cssText = "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;" +
        "background:rgba(5,10,16,.9);z-index:9998";
      document.body.appendChild(ov);
    }
    ov.innerHTML = html;
    ov.style.display = "flex";
    return ov;
  }
  function hideOverlay() { var ov = E("mp-overlay"); if (ov) ov.style.display = "none"; }

  function send(type, payload, cb) {
    if (!sock || sock.readyState !== WebSocket.OPEN) { if (cb) cb({ type: "error", payload: { message: "连接未就绪" } }); return; }
    var rid = "r" + (++REQ_SEQ) + "-" + Date.now();
    if (cb) PENDING[rid] = cb;
    sock.send(JSON.stringify({ version: 1, type: type, payload: payload || {}, requestId: rid }));
  }

  // ---- 状态适配: 把联机快照/事件变成 main.js 认识的 state ----
  function roomOf(seatStatus) {
    var players = {};
    (seatStatus || []).forEach(function (p) {
      players[p.seat_index] = { name: p.username + (p.disconnected ? "（掉线）" : "") + (p.abandoned ? "（托管）" : "") };
    });
    return { players: players };
  }

  function adapt(sess) {
    var v = sess.viewer || {}, st = sess.state || {};
    st.my_idx = (v.seat_index != null && v.seat_index >= 0) ? v.seat_index : -1;
    st.human_hand = v.hand || null;
    st.drawn_tile = v.drawn_tile || null;
    st.actions = v.available_actions || [];
    st.decision_seat = (v.decision_seat != null ? v.decision_seat : -1);
    st.timer = v.timer || null;
    st.room = roomOf(sess.seat_status);
    st.spectator = !!sess.spectator;
    st.session_id = sess.session_id;
    st.round_count = sess.round_count || (sess.summary && sess.summary.round_count) || 0;
    st.final_scores = sess.final_scores || null;
    STAGE = v.stage_counter != null ? v.stage_counter : STAGE;
    MY_SEAT = st.my_idx;
    return st;
  }

  function renderSession(sess) {
    if (sess && sess.phase === "pending") { // 还在等待房
      var s = sess.summary || {}, seats = sess.seats || [];
      var rows = seats.map(function (x) {
        return '<div style="padding:8px 12px;border:1px solid rgba(0,229,255,.18);border-radius:8px;min-width:150px">' +
          '<div style="color:#e0e0e0;font-size:14px;font-weight:700">' + (x.username || "空位") + '</div>' +
          '<div style="color:' + (x.ready ? "#69f0ae" : "#78909c") + ';font-size:11px;margin-top:2px">' +
          (x.player_id ? (x.ready ? "已准备" : "未准备") : "—") + '</div></div>';
      }).join("");
      overlay('<div style="text-align:center"><div style="color:#00e5ff;font-size:20px;font-weight:800;letter-spacing:2px">等待房主开局</div>' +
        '<div style="color:#78909c;font-size:12px;margin:8px 0 18px">已就座 ' + s.occupied_seat_count + '/4 · ' +
        s.round_count + '局 · 主计时 ' + Math.round((s.primary_timer_ms || 7000) / 1000) + 's</div>' +
        '<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">' + rows + '</div>' +
        '<a href="/lobby" style="display:inline-block;margin-top:20px;color:#00e5ff;font-size:12px">← 返回大厅</a></div>');
      return;
    }
    if (!sess || sess.phase !== "active") {
      overlay('<div style="text-align:center"><div style="color:#e0e0e0;font-size:18px;font-weight:700">你当前不在对局中</div>' +
        '<a href="/lobby" style="display:inline-block;margin-top:16px;color:#00e5ff;font-size:13px">前往大厅 →</a></div>');
      return;
    }
    hideOverlay();
    var st = adapt(sess);
    CUR = st;
    if (typeof updateNames === "function") updateNames(st.room);
    if (st.game_over) {
      if (!st._shown) { st._shown = 1; if (typeof clearTimer === "function") clearTimer(); showResultSafe(st); }
      return;
    }
    var old = E("result-overlay"); if (old) old.remove();
    SHOWN_OVER = false;
    if (typeof render === "function") render(st);
    if (typeof startTimer === "function") startTimer(st);
    markTurn(st);
    // 联机也显示「第N/M局」
    var ri = E("round-info");
    if (ri && st.round_count) ri.textContent = st.round_num + "/" + st.round_count + "局";
    if (st.spectator) hideActions();
  }

  function showResultSafe(st) {
    SHOWN_OVER = true;
    if (typeof showResult === "function") showResult(st);
    // 联机: 结算面板按钮改为"关闭"(下一局由服务端自动推进)
    setTimeout(function () {
      var ov = E("result-overlay");
      if (!ov) return;
      var btns = ov.querySelectorAll("button");
      btns.forEach(function (b) { if (b.textContent === "下一局") b.textContent = "关闭"; });
    }, 0);
  }

  function hideActions() {
    var mb = E("meld-btns"); if (mb) mb.style.display = "none";
    var cs = E("chow-sub"); if (cs) cs.style.display = "none";
  }

  // ---- 轮次提示: 四人时"该谁出牌"必须一眼可见 ----
  function injectStyle() {
    if (E("mp-style")) return;
    var s = document.createElement("style");
    s.id = "mp-style";
    s.textContent =
      ".mp-turn{color:#00e5ff !important;text-shadow:0 0 10px rgba(0,229,255,.75)}" +
      ".mp-turn::after{content:' ●';font-size:10px;vertical-align:middle}" +
      "#mp-banner{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:9997;" +
      "padding:7px 22px;border-radius:18px;font-size:14px;font-weight:800;letter-spacing:2px;" +
      "background:rgba(0,229,255,.14);border:1px solid rgba(0,229,255,.45);color:#00e5ff;" +
      "box-shadow:0 0 18px rgba(0,229,255,.22)}";
    document.head.appendChild(s);
  }

  function showBanner(text) {
    var b = E("mp-banner");
    if (!text) { if (b) b.style.display = "none"; return; }
    if (!b) {
      b = document.createElement("div");
      b.id = "mp-banner";
      document.body.appendChild(b);
    }
    b.textContent = text;
    b.style.display = "block";
  }

  function markTurn(st) {
    injectStyle();
    var els = document.querySelectorAll(".mp-turn");
    for (var i = 0; i < els.length; i++) els[i].classList.remove("mp-turn");
    var dec = st.decision_seat;
    if (dec == null || dec < 0) { showBanner(""); return; }
    var my = (MY_SEAT < 0 ? 0 : MY_SEAT);
    var dir = ["bottom", "right", "top", "left"][(dec - my + 4) % 4];
    var nm = E("name-" + dir);
    if (nm) nm.classList.add("mp-turn");
    if (dec === MY_SEAT) {
      var claim = (st.phase === "CLAIM_PK" || st.phase === "CLAIM_CHOW");
      showBanner(claim ? "轮到你鸣牌" : "轮到你出牌");
    } else {
      showBanner("");
    }
  }

  // ---- 覆盖 main.js 的动作发送与"下一局" ----
  window.act = function (type, prm) {
    prm = prm || {};
    var payload = { kind: type, stage_counter: STAGE };
    if (prm.tile != null) payload.tile = prm.tile;
    if (prm.choice != null) payload.choice = prm.choice;
    if (prm.meld_idx != null) payload.meld_idx = prm.meld_idx;
    send("game.input", payload, function (env) {
      if (env && env.type === "error") {
        var m = (env.payload && env.payload.message) || "操作失败";
        if (env.payload && env.payload.code === "stale_input") m = "操作已过期，已同步最新状态";
        toast(m);
        send("game.snapshot", {});
      }
    });
  };
  window.nx = function () { var x = E("result-overlay"); if (x) x.remove(); };

  // ---- 连接与消息处理 ----
  function onEnvelope(env) {
    if (!env || !env.type) return;
    if (env.requestId && PENDING[env.requestId] && (env.type === "ack" || env.type === "error")) {
      var cb = PENDING[env.requestId]; delete PENDING[env.requestId];
      try { cb(env); } catch (e) {}
      if (env.type === "error") { }
      return;
    }
    if (env.type === "pong") return;
    if (env.type === "error") {
      toast((env.payload && env.payload.message) || "服务端错误");
      return;
    }
    if (env.type === "session.snapshot") { renderSession(env.payload && env.payload.session); return; }
    if (env.type === "game.event") {
      var p = env.payload || {};
      if (p.ended) { // 整场结束
        var st = { players: (p.state || {}).players, my_idx: MY_SEAT, human_hand: (p.viewer || {}).hand,
                   scores: (p.state || {}).scores, final_scores: p.final_scores, session_end: true };
        overlay('<div style="text-align:center"><div style="color:#ffb300;font-size:22px;font-weight:900;letter-spacing:2px">对局结束</div>' +
          '<div style="color:#b0bec5;font-size:14px;margin-top:10px">' +
          ['东', '南', '西', '北'].map(function (r, i) { return r + " " + (((p.final_scores || [])[i]) || 0); }).join("　") + '</div>' +
          '<a href="/lobby" style="display:inline-block;margin-top:18px;color:#00e5ff;font-size:13px">返回大厅</a>' +
          '<a href="/replay" style="display:inline-block;margin-top:18px;margin-left:14px;color:#b388ff;font-size:13px">查看回放 →</a></div>');
        return;
      }
      var fake = { phase: "active", session_id: p.session_id, state: p.state, viewer: p.viewer,
                   seat_status: p.seat_status, spectator: p.spectator, round_count: (CUR && CUR.round_count) || 0,
                   final_scores: null };
      renderSession(fake);
      if (p.category === "round_end" || p.category === "round_start") hideOverlay();
      return;
    }
  }

  function connect() {
    var path = SPECTATE_SID ? "/ws/spectate" : "/ws/game";
    var url = BASE + path + "?access_token=" + encodeURIComponent(TOKEN);
    sock = new WebSocket(url);
    sock.onopen = function () {
      RETRY = 0;
      if (SPECTATE_SID) send("spectate.subscribe", { session_id: parseInt(SPECTATE_SID, 10) || 0 });
      else send("game.snapshot", {}, function (env) {
        // 不在对局中(或未开局): 给出明确提示, 而不是留一张空牌桌
        if (env && env.type === "error") renderSession(null);
        else if (env && env.type === "ack") { var p = env.payload || {}; if (!p.session) {} }
      });
      if (PING_TIMER) clearInterval(PING_TIMER);
      PING_TIMER = setInterval(function () { send("ping", {}); }, 20000);
    };
    sock.onmessage = function (ev) {
      try { onEnvelope(JSON.parse(ev.data)); } catch (e) {}
    };
    sock.onclose = function () {
      if (PING_TIMER) { clearInterval(PING_TIMER); PING_TIMER = null; }
      if (RETRY < 5) {
        RETRY++;
        toast("连接断开，正在重连（" + RETRY + "/5）…");
        setTimeout(connect, 1200 * RETRY);
      } else {
        overlay('<div style="text-align:center"><div style="color:#ff8a80;font-size:16px;font-weight:700">连接已断开</div>' +
          '<a href="/lobby" style="display:inline-block;margin-top:14px;color:#00e5ff;font-size:13px">返回大厅</a></div>');
      }
    };
  }

  // ---- 启动 ----
  function boot() {
    if (!TOKEN) {
      overlay('<div style="text-align:center"><div style="color:#e0e0e0;font-size:16px;font-weight:700">请先登录</div>' +
        '<a href="/auth?back=' + encodeURIComponent(location.pathname + location.search) + '" style="display:inline-block;margin-top:14px;color:#00e5ff;font-size:13px">前往登录 →</a></div>');
      return;
    }
    if (SPECTATE_SID) {
      var ri = E("round-info"); if (ri) ri.textContent = "观战中";
    }
    connect();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
