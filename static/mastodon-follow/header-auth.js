/*
 * Site-wide header authentication widget.
 *
 * Renders a Login button in the top corner of every page. When the visitor is
 * connected (a token exists in this tab's sessionStorage, managed by
 * follow-core.js), it shows their avatar + display name and a Log out control.
 *
 * Login reuses the existing PKCE OAuth flow: redirect_uri is the *current* page
 * (see MastodonFollow.redirectUri), so logging in from the header returns the
 * visitor to the page they started on. Because the flow redirects away and
 * back, every page must complete a pending callback on load — that is what the
 * handleCallback() call below does.
 */
(function () {
  "use strict";

  var MF = window.MastodonFollow;
  if (!MF) return; // follow-core.js failed to load; nothing to do.

  var mount = document.getElementById("header-auth");
  if (!mount) return;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else if (k === "text") node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function renderLoggedOut() {
    mount.textContent = "";
    var btn = el("button", {
      type: "button",
      class: "header-auth__login",
      text: "Log in",
    });
    btn.addEventListener("click", login);
    mount.appendChild(btn);
  }

  function renderLoggedIn(account) {
    mount.textContent = "";
    var profile = el("a", {
      class: "header-auth__profile",
      href: account.url || "#",
      target: "_blank",
      rel: "noopener noreferrer",
      title: "@" + account.acct,
    });
    if (account.avatar) {
      profile.appendChild(el("img", {
        class: "header-auth__avatar",
        src: account.avatar,
        alt: "",
        width: "28",
        height: "28",
        loading: "lazy",
      }));
    }
    profile.appendChild(el("span", {
      class: "header-auth__name",
      text: account.display_name || account.username || account.acct,
    }));
    var logout = el("button", {
      type: "button",
      class: "header-auth__logout",
      text: "Log out",
      title: "Log out",
    });
    logout.addEventListener("click", function () {
      MF.logout();
      renderLoggedOut();
    });
    mount.appendChild(profile);
    mount.appendChild(logout);
  }

  function login() {
    // Ask which Mastodon instance to authorize against. follow-core stores it
    // in localStorage, so a returning visitor is only prompted once.
    var current = MF.getInstance();
    var raw = window.prompt(
      "Your Mastodon server (e.g. mastodon.social):",
      current || ""
    );
    if (!raw) return;
    MF.setInstance(raw);
    MF.beginAuthorize().catch(function (err) {
      window.alert("Could not start login: " + (err && err.message ? err.message : err));
    });
  }

  async function refresh() {
    if (!MF.isConnected()) {
      renderLoggedOut();
      return;
    }
    try {
      var account = await MF.verifyCredentials();
      renderLoggedIn(account);
    } catch (e) {
      // Token expired/revoked — fall back to logged-out.
      MF.logout();
      renderLoggedOut();
    }
  }

  async function start() {
    // Complete an OAuth redirect if we just came back from the provider. The
    // follow page also calls handleCallback(); both are idempotent (no `code`
    // param ⇒ no-op), so a header login that lands on the follow page still
    // works, and vice versa.
    try {
      await MF.handleCallback();
    } catch (e) {
      // Surface nothing in the header; the follow page logs auth errors.
    }
    await refresh();
  }

  start();
})();
