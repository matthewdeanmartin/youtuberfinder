/* ================================================================
   Inline "Follow on Mastodon" buttons (category & listing pages)
   ----------------------------------------------------------------
   Progressive enhancement over the per-creator buttons emitted by
   generate_pages.py (<button class="creator-follow" data-mastodon-acct
   hidden>). Requires window.MastodonFollow (follow-core.js), loaded
   just before this script.

   Behaviour (decided with the user):
   • Token lives in sessionStorage — per browser tab. If the user
     already connected in this tab, Follow happens inline.
   • If not connected, clicking Follow connects IN PLACE: we prompt
     for the instance if unknown, stash a pending follow, run OAuth
     (which briefly leaves to the instance and returns to THIS page),
     then auto-complete the follow on return. No redirect to the
     dedicated tool.
================================================================ */
(function () {
  "use strict";

  var MF = window.MastodonFollow;
  if (!MF) return;  // core failed to load; leave buttons hidden

  MF.init({
    log: function (msg, level) {
      if (level === "error") console.error(msg);
      else console.log(msg);
    },
  });

  function setButtonState(btn, text, disabled) {
    btn.textContent = text;
    btn.disabled = !!disabled;
  }

  function statusHandler(btn, acct) {
    return function (state) {
      if (state === "resolving")           setButtonState(btn, "Resolving…", true);
      else if (state === "following")      setButtonState(btn, "Following…", true);
      else if (state === "already")        markFollowing(btn);
      else if (state === "following-done") markFollowing(btn);
      else if (state === "requested")      markRequested(btn);
      else if (state === "unknown")        setButtonState(btn, "Check Mastodon", false);
    };
  }

  function markFollowing(btn) {
    setButtonState(btn, "✓ Following", true);
    btn.classList.add("creator-follow--following");
  }
  function markRequested(btn) {
    setButtonState(btn, "⏳ Requested", true);
    btn.classList.add("creator-follow--following");
  }

  function promptInstance() {
    var current = MF.getInstance();
    var answer = window.prompt(
      "Which Mastodon instance are you on?\n(e.g. mastodon.social)",
      current || ""
    );
    return answer || "";
  }

  async function onFollowClick(btn) {
    var acct = btn.getAttribute("data-mastodon-acct");
    if (!acct) return;
    var reset = btn.textContent;
    try {
      await MF.connectAndFollow(acct, {
        onStatus: statusHandler(btn, acct),
        promptInstance: promptInstance,
      });
      // If we reach here connected, the follow ran inline. If not connected,
      // connectAndFollow has already navigated away to authorize.
    } catch (err) {
      console.error("Follow failed for @" + acct + ": " + err.message);
      setButtonState(btn, "Retry follow", false);
      btn.title = err.message;
      setTimeout(function () { if (btn.textContent === "Retry follow") btn.textContent = reset; }, 4000);
    }
  }

  function wireButtons() {
    var buttons = document.querySelectorAll(".creator-follow[data-mastodon-acct]");
    buttons.forEach(function (btn) {
      btn.hidden = false;  // reveal now that JS + core are available
      btn.addEventListener("click", function () { onFollowClick(btn); });
    });
    return buttons;
  }

  async function init() {
    var buttons = wireButtons();

    // Complete the OAuth handshake if we just came back from the instance,
    // then resume any pending follow that triggered the connect.
    try {
      await MF.handleCallback();
    } catch (err) {
      console.error("OAuth callback error: " + err.message);
      return;
    }
    if (!MF.isConnected()) return;

    var pending = MF.getPendingFollow();
    if (pending) {
      var pendBtn = null;
      buttons.forEach(function (b) {
        if (b.getAttribute("data-mastodon-acct") === pending) pendBtn = b;
      });
      try {
        await MF.resumePending(pendBtn ? statusHandler(pendBtn, pending) : undefined);
      } catch (err) {
        console.error("Pending follow failed: " + err.message);
      }
    }

    // Pre-mark creators already followed in this account. One search per
    // handle (locally-known only) + a single batched relationships call.
    await markAlreadyFollowing(buttons);
  }

  async function markAlreadyFollowing(buttons) {
    var byAcct = {};
    var accts = [];
    buttons.forEach(function (btn) {
      var acct = btn.getAttribute("data-mastodon-acct");
      if (acct) { byAcct[acct] = btn; accts.push(acct); }
    });
    if (!accts.length) return;
    try {
      await MF.followStatuses(accts, function (acct, state) {
        var btn = byAcct[acct];
        if (!btn) return;
        if (state === "following") markFollowing(btn);
        else if (state === "requested") markRequested(btn);
      });
    } catch (err) {
      console.error("Follow-status check failed: " + err.message);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
