(function () {
  const TOKEN_KEY = "moneyline_admin_token";

  function getToken() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("token");
    if (fromUrl) {
      sessionStorage.setItem(TOKEN_KEY, fromUrl);
      return fromUrl;
    }
    return sessionStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(value) {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  }

  function authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const token = getToken();
    if (token) headers["X-Admin-Token"] = token;
    return headers;
  }

  async function apiFetch(url, options) {
    const opts = Object.assign({ headers: authHeaders() }, options || {});
    opts.headers = authHeaders(opts.headers);
    const resp = await fetch(url, opts);
    if (resp.status === 401) {
      throw new Error("Admin token required. Enter your WEB_ADMIN_TOKEN below.");
    }
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const body = await resp.json();
        detail = body.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return resp.json();
  }

  function showToast(message, kind) {
    let el = document.getElementById("shell-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "shell-toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.className = "toast show " + (kind || "");
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
      el.classList.remove("show");
    }, 3200);
  }

  function initSidebar(activePage) {
    document.querySelectorAll(".nav-link[data-page]").forEach(function (link) {
      if (link.dataset.page === activePage) link.classList.add("active");
    });
  }

  function bindSlidePanel() {
    const backdrop = document.getElementById("slide-backdrop");
    const panel = document.getElementById("slide-panel");
    const closeBtn = document.getElementById("slide-close");
    if (!backdrop || !panel) return;

    function close() {
      backdrop.classList.remove("open");
      panel.classList.remove("open");
    }

    backdrop.addEventListener("click", close);
    if (closeBtn) closeBtn.addEventListener("click", close);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") close();
    });

    window.MoneyLineShell = window.MoneyLineShell || {};
    window.MoneyLineShell.openSlidePanel = function () {
      backdrop.classList.add("open");
      panel.classList.add("open");
    };
    window.MoneyLineShell.closeSlidePanel = close;
  }

  function bindTokenBar() {
    const input = document.getElementById("admin-token");
    const saveBtn = document.getElementById("save-token");
    if (!input) return;
    input.value = getToken();
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        setToken(input.value.trim());
        showToast("Admin token saved for this session", "ok");
        if (window.MoneyLineSubscribers && window.MoneyLineSubscribers.reload) {
          window.MoneyLineSubscribers.reload();
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindSlidePanel();
    bindTokenBar();
  });

  window.MoneyLineShell = Object.assign(window.MoneyLineShell || {}, {
    getToken: getToken,
    setToken: setToken,
    apiFetch: apiFetch,
    showToast: showToast,
    initSidebar: initSidebar,
  });
})();
