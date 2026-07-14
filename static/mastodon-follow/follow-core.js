/* ================================================================
   YouTubers on Mastodon — shared follow core
   ----------------------------------------------------------------
   One implementation of the Mastodon PKCE OAuth + resolve + follow
   flow, used by BOTH the dedicated /mastodon-follow/ tool and the
   inline "Follow" buttons on category/listing pages.

   Security model (unchanged from the original tool):
   • PKCE: a random code_verifier (sessionStorage, transient) is
     hashed to a code_challenge for the authorize request, protecting
     the authorization code in transit.
   • The app's client_id + client_secret are cached per-instance in
     localStorage. Mastodon's /oauth/token requires the secret even
     with PKCE (it has no secret-less public clients); omitting it
     returns 401 invalid_client. These are app credentials, not the
     user's password.
   • The access token lives ONLY in sessionStorage — per browser tab.
     It survives navigation between pages in the same tab but is not
     shared with other tabs, and is dropped when the tab closes. This
     keeps it isolated from scripts on other same-origin pages/tabs.

   "Connect in place" model:
   • Every page that loads this script can start the OAuth flow with
     redirect_uri = the current page. When a Follow is requested while
     no token exists, the target account is stashed as a "pending
     follow" in sessionStorage, OAuth runs, the browser returns to the
     SAME page, and resumePending() completes the follow automatically.
================================================================ */
(function (global) {
  "use strict";

  var APP_NAME = "YouTubers on Mastodon Follow Pack";
  var APP_WEBSITE = "https://matthewdeanmartin.github.io/youtuberfinder/";
  var DEFAULT_SCOPES = "profile read:accounts read:search read:statuses read:follows write:follows";

  var noop = function () {};
  var _log = noop;

  function log(msg, level) { try { _log(msg, level || "info"); } catch (e) {} }

  /* ── Instance (kept in memory + localStorage, no DOM dependency) ── */
  var LS_INSTANCE_KEY = "mf-pack:lastInstance";
  var _instance = "";

  function normalizeInstance(raw) {
    return (raw || "").trim().replace(/^https?:\/\//i, "").replace(/\/+$/g, "");
  }
  function setInstance(raw) {
    _instance = normalizeInstance(raw);
    if (_instance) localStorage.setItem(LS_INSTANCE_KEY, _instance);
    return _instance;
  }
  function getInstance() {
    if (!_instance) _instance = normalizeInstance(localStorage.getItem(LS_INSTANCE_KEY) || "");
    return _instance;
  }
  function instanceBase() {
    var inst = getInstance();
    if (!inst) throw new Error("No Mastodon instance set.");
    return "https://" + inst;
  }

  function redirectUri() {
    if (location.origin === "null") {
      return location.href.split("?")[0].split("#")[0];
    }
    return location.origin + location.pathname;
  }

  /* ── Storage ─────────────────────────────────────────────────── */
  function lsAppKey(inst) { return "mf-pack:" + inst + ":app"; }
  function getApp(inst) {
    var raw = localStorage.getItem(lsAppKey(inst));
    return raw ? JSON.parse(raw) : null;
  }
  function setApp(inst, app) {
    localStorage.setItem(lsAppKey(inst), JSON.stringify(app));
  }

  function getToken() {
    var inst = getInstance();
    var raw = inst ? sessionStorage.getItem("mf-pack:" + inst + ":token") : null;
    return raw ? JSON.parse(raw) : null;
  }
  function setToken(inst, tokenObj) {
    sessionStorage.setItem("mf-pack:" + inst + ":token", JSON.stringify(tokenObj));
  }
  function clearToken(inst) {
    sessionStorage.removeItem("mf-pack:" + inst + ":token");
  }

  function getVerifier() { return sessionStorage.getItem("mf-pack:pkce:verifier"); }
  function setVerifier(v) { sessionStorage.setItem("mf-pack:pkce:verifier", v); }
  function clearVerifier() { sessionStorage.removeItem("mf-pack:pkce:verifier"); }
  function getOAuthState() { return sessionStorage.getItem("mf-pack:pkce:state"); }
  function setOAuthState(s) { sessionStorage.setItem("mf-pack:pkce:state", s); }
  function clearOAuthState() { sessionStorage.removeItem("mf-pack:pkce:state"); }

  // Pending follow: the account to auto-follow after a connect-in-place hop.
  function getPendingFollow() { return sessionStorage.getItem("mf-pack:pendingFollow") || ""; }
  function setPendingFollow(acct) { sessionStorage.setItem("mf-pack:pendingFollow", acct); }
  function clearPendingFollow() { sessionStorage.removeItem("mf-pack:pendingFollow"); }

  function isConnected() { return !!getToken(); }

  /* ── PKCE helpers ────────────────────────────────────────────── */
  function generateVerifier() {
    var arr = new Uint8Array(64);
    crypto.getRandomValues(arr);
    return btoa(String.fromCharCode.apply(null, arr))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
  }
  async function sha256Base64Url(plain) {
    var data = new TextEncoder().encode(plain);
    var hash = await crypto.subtle.digest("SHA-256", data);
    return btoa(String.fromCharCode.apply(null, new Uint8Array(hash)))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
  }

  /* ── API fetch ───────────────────────────────────────────────── */
  async function apiFetch(path, options) {
    options = options || {};
    var url = path.indexOf("http") === 0 ? path : instanceBase() + path;
    var res = await fetch(url, options);
    var text = await res.text();
    var data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!res.ok) {
      var detail = (typeof data === "object" && data && data.error) ? data.error : text;
      throw new Error(res.status + " " + res.statusText + ": " + detail);
    }
    return data;
  }

  /* ── App registration ────────────────────────────────────────── */
  async function ensureAppRegistered(inst) {
    var cached = getApp(inst);
    // Re-use the cached registration only when both the redirect_uri AND the
    // scopes match. If DEFAULT_SCOPES has grown (e.g. read:statuses was added),
    // the old app can't grant the new scope, so we must re-register.
    if (
      cached &&
      cached.client_id &&
      cached.client_secret &&
      cached.redirect_uri === redirectUri() &&
      cached.scopes === DEFAULT_SCOPES
    ) {
      return cached;
    }
    var body = new FormData();
    body.set("client_name", APP_NAME);
    body.set("redirect_uris", redirectUri());
    body.set("scopes", DEFAULT_SCOPES);
    body.set("website", APP_WEBSITE);
    var app = await apiFetch("/api/v1/apps", { method: "POST", body: body });
    var record = {
      client_id: app.client_id,
      client_secret: app.client_secret,
      redirect_uri: redirectUri(),
      scopes: DEFAULT_SCOPES,
    };
    setApp(inst, record);
    log("App registered on " + inst + " (client credentials cached).");
    return record;
  }

  /* ── Authorize (leaves the page) ─────────────────────────────── */
  async function beginAuthorize() {
    var inst = getInstance();
    if (!inst) throw new Error("Set an instance first.");
    var app = await ensureAppRegistered(inst);
    var verifier = generateVerifier();
    var challenge = await sha256Base64Url(verifier);
    var state = crypto.randomUUID();
    setVerifier(verifier);
    setOAuthState(state);
    var params = new URLSearchParams({
      response_type: "code",
      client_id: app.client_id,
      redirect_uri: redirectUri(),
      scope: DEFAULT_SCOPES,
      state: state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    log("Redirecting to Mastodon authorization…");
    location.href = "https://" + inst + "/oauth/authorize?" + params;
  }

  /* ── Handle the OAuth callback (exchange code for token) ─────── */
  async function handleCallback() {
    var url = new URL(location.href);
    var code = url.searchParams.get("code");
    if (!code) return false;

    var inst = getInstance();
    var expectedState = getOAuthState();
    var returnedState = url.searchParams.get("state");
    if (expectedState && returnedState !== expectedState) {
      clearVerifier(); clearOAuthState();
      throw new Error("OAuth state mismatch – possible CSRF. Aborting.");
    }
    var verifier = getVerifier();
    if (!verifier) throw new Error("PKCE verifier missing from session. Please connect again.");
    var app = getApp(inst);
    if (!app || !app.client_id || !app.client_secret) {
      throw new Error("No app registration found. Please connect again.");
    }

    var body = new URLSearchParams({
      grant_type: "authorization_code",
      code: code,
      client_id: app.client_id,
      client_secret: app.client_secret,
      redirect_uri: redirectUri(),
      scope: DEFAULT_SCOPES,
      code_verifier: verifier,
    });
    var token = await apiFetch("/oauth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body,
    });
    setToken(inst, {
      access_token: token.access_token,
      token_type: token.token_type,
      scope: token.scope,
      created_at: new Date().toISOString(),
    });
    clearVerifier();
    clearOAuthState();
    history.replaceState({}, document.title, redirectUri());
    log("Authorization successful. Token stored in session (this tab only).", "ok");
    return true;
  }

  function authHeaders() {
    var token = getToken();
    if (!token || !token.access_token) throw new Error("Not connected.");
    return { Authorization: "Bearer " + token.access_token };
  }

  async function verifyCredentials() {
    var acct = await apiFetch("/api/v1/accounts/verify_credentials", { headers: authHeaders() });
    log("Logged in as @" + acct.acct + " on " + getInstance() + ".", "ok");
    return acct;
  }

  /* ── Resolve & follow ────────────────────────────────────────── */
  async function resolveAccount(acct) {
    var params = new URLSearchParams({ q: acct, type: "accounts", resolve: "true", limit: "5" });
    var result = await apiFetch("/api/v2/search?" + params, { headers: authHeaders() });
    var accounts = result.accounts || [];
    var wanted = acct.toLowerCase();
    var exact = accounts.find(function (a) {
      return String(a.acct || "").toLowerCase() === wanted ||
        String(a.url || "").toLowerCase().indexOf("/@" + wanted.split("@")[0]) !== -1;
    });
    if (!exact) {
      var cands = accounts.map(function (a) { return a.acct; }).filter(Boolean).join(", ");
      throw new Error("Could not resolve @" + acct + (cands ? ". Candidates: " + cands : ""));
    }
    return exact;
  }

  async function accountStatuses(id, opts) {
    opts = opts || {};
    var params = new URLSearchParams({
      limit: String(opts.limit || 10),
      exclude_replies: "true",
      exclude_reblogs: "false",
    });
    return apiFetch(
      "/api/v1/accounts/" + encodeURIComponent(id) + "/statuses?" + params,
      { headers: authHeaders() }
    );
  }

  async function followAccountId(id) {
    return apiFetch("/api/v1/accounts/" + encodeURIComponent(id) + "/follow", {
      method: "POST",
      headers: authHeaders(),
    });
  }

  async function getRelationship(id) {
    var params = new URLSearchParams();
    params.append("id[]", id);
    var rels = await apiFetch("/api/v1/accounts/relationships?" + params, { headers: authHeaders() });
    return rels[0] || null;
  }

  /* Resolve a handle WITHOUT forcing the home instance to fetch it remotely
     (resolve=false). This only returns accounts the instance already knows —
     crucially, every account you already follow — so it is cheap enough to run
     for a whole page on load. Returns the matching account or null. */
  async function resolveKnown(acct) {
    var params = new URLSearchParams({ q: acct, type: "accounts", resolve: "false", limit: "5" });
    var result = await apiFetch("/api/v2/search?" + params, { headers: authHeaders() });
    var accounts = result.accounts || [];
    var wanted = acct.toLowerCase();
    return accounts.find(function (a) {
      return String(a.acct || "").toLowerCase() === wanted ||
        String(a.url || "").toLowerCase().indexOf("/@" + wanted.split("@")[0]) !== -1;
    }) || null;
  }

  /* For a list of handles, return a map acct -> "following" | "requested" | null.
     Used on page load (when connected) to pre-mark creators you already follow.
     Resolves only locally-known accounts and batches the relationships call, so
     the cost is one search per handle plus a single relationships request.
     Never throws: on any error a handle is simply reported as null (unknown). */
  async function followStatuses(accts, onResolve) {
    onResolve = onResolve || noop;
    var result = {};
    var idToAcct = {};
    var ids = [];
    for (var i = 0; i < accts.length; i++) {
      var acct = accts[i];
      result[acct] = null;
      try {
        var account = await resolveKnown(acct);
        if (account && account.id) {
          idToAcct[account.id] = acct;
          ids.push(account.id);
        }
      } catch (e) { /* leave as null */ }
    }
    if (!ids.length) return result;
    try {
      var params = new URLSearchParams();
      ids.forEach(function (id) { params.append("id[]", id); });
      var rels = await apiFetch("/api/v1/accounts/relationships?" + params, { headers: authHeaders() });
      (rels || []).forEach(function (rel) {
        var acct = idToAcct[rel.id];
        if (!acct) return;
        var state = rel.following ? "following" : rel.requested ? "requested" : null;
        result[acct] = state;
        onResolve(acct, state);
      });
    } catch (e) { /* leave resolved-but-unknown as null */ }
    return result;
  }

  /* Resolve + follow a handle. Returns a status string:
     "following" | "requested" | "already" | "unknown". Throws on error. */
  async function follow(acct, onStatus) {
    onStatus = onStatus || noop;
    onStatus("resolving");
    var account = await resolveAccount(acct);
    var before = await getRelationship(account.id);
    if (before && before.following) {
      onStatus("already");
      log("Already following @" + acct, "ok");
      return "already";
    }
    onStatus("following");
    var rel = await followAccountId(account.id);
    if (rel.following) {
      log("Followed @" + acct, "ok");
      onStatus("following-done");
      return "following";
    }
    if (rel.requested) {
      log("Follow request sent to @" + acct, "warn");
      onStatus("requested");
      return "requested";
    }
    log("Unexpected relationship for @" + acct + ": " + JSON.stringify(rel), "warn");
    onStatus("unknown");
    return "unknown";
  }

  /* Connect-in-place: ensure we have a token, then follow `acct`.
     If no token, stash the pending follow and start OAuth (this
     navigates away and returns to the same page). */
  async function connectAndFollow(acct, opts) {
    opts = opts || {};
    if (isConnected()) {
      return follow(acct, opts.onStatus);
    }
    var inst = getInstance();
    if (!inst && typeof opts.promptInstance === "function") {
      inst = setInstance(await opts.promptInstance());
    }
    if (!inst) throw new Error("A Mastodon instance is required to follow.");
    setPendingFollow(acct);
    await beginAuthorize();
    // (page navigates away here)
  }

  function logout() {
    var inst = getInstance();
    if (!inst) return;
    clearToken(inst);
    clearVerifier();
    clearOAuthState();
    clearPendingFollow();
    localStorage.removeItem(lsAppKey(inst));
    log("Session and cached app credentials cleared for " + inst + ".");
  }

  /* After a callback, finish any pending follow. Returns the acct (or null). */
  async function resumePending(onStatus) {
    var acct = getPendingFollow();
    if (!acct || !isConnected()) return null;
    clearPendingFollow();
    await follow(acct, onStatus);
    return acct;
  }

  /* ── Public API ──────────────────────────────────────────────── */
  global.MastodonFollow = {
    DEFAULT_SCOPES: DEFAULT_SCOPES,
    init: function (opts) { if (opts && opts.log) _log = opts.log; },
    normalizeInstance: normalizeInstance,
    setInstance: setInstance,
    getInstance: getInstance,
    instanceBase: instanceBase,
    redirectUri: redirectUri,
    getApp: getApp,
    isConnected: isConnected,
    beginAuthorize: beginAuthorize,
    handleCallback: handleCallback,
    verifyCredentials: verifyCredentials,
    resolveAccount: resolveAccount,
    accountStatuses: accountStatuses,
    follow: follow,
    followStatuses: followStatuses,
    connectAndFollow: connectAndFollow,
    resumePending: resumePending,
    getPendingFollow: getPendingFollow,
    clearPendingFollow: clearPendingFollow,
    logout: logout,
  };
})(window);
