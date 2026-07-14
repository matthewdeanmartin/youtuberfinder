/**
 * category-controls.js — search + sort controls for category listings.
 *
 * Each category page emits a `.list-controls` toolbar carrying
 * `data-controls="<section>"`, paired with a `<ul>` inside the
 * `[data-lang-section="<section>"]` wrapper. Every `<li>` in that list carries:
 *   data-name        — casefolded creator name (search + alpha sort key)
 *   data-score        — combined popularity score (the build default sort)
 *   data-followers     — Mastodon follower count (-1 = unknown)
 *   data-subscribers   — YouTube subscriber count (-1 = unknown)
 *
 * Behaviour:
 *   • Search box filters items by substring match on data-name.
 *   • "Top picks" sorts by data-score descending (the build default).
 *   • "Most subscribers" / "Most followed" sort by the individual metric.
 *   • "A–Z" sorts by data-name ascending.
 *   • "Shuffle" randomises the order (Fisher–Yates).
 *
 * Search hides items via the `is-search-hidden` class — kept separate from
 * lang-filter.js, which toggles the `hidden` attribute. An item is only visible
 * when neither mechanism hides it, so the two filters compose cleanly.
 */
(function () {
  "use strict";

  function items(list) {
    return Array.prototype.slice.call(list.querySelectorAll(":scope > li"));
  }

  function num(li, attr) {
    var n = parseFloat(li.getAttribute(attr));
    return isNaN(n) ? -1 : n;
  }

  function name(li) {
    return li.getAttribute("data-name") || "";
  }

  function reorder(list, ordered) {
    // Re-append in the desired order; appendChild moves existing nodes.
    ordered.forEach(function (li) {
      list.appendChild(li);
    });
  }

  function sortNumeric(list, attr) {
    reorder(
      list,
      items(list).sort(function (a, b) {
        return num(b, attr) - num(a, attr) || (name(a) < name(b) ? -1 : 1);
      })
    );
  }

  function sortAlpha(list) {
    reorder(
      list,
      items(list).sort(function (a, b) {
        return name(a) < name(b) ? -1 : name(a) > name(b) ? 1 : 0;
      })
    );
  }

  function shuffle(list) {
    var arr = items(list);
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i];
      arr[i] = arr[j];
      arr[j] = tmp;
    }
    reorder(list, arr);
  }

  function applySearch(list, query, emptyEl) {
    var q = query.trim().toLowerCase();
    var anyVisible = false;
    items(list).forEach(function (li) {
      var hit = !q || name(li).indexOf(q) !== -1;
      li.classList.toggle("is-search-hidden", !hit);
      // An item still counts as visible only if lang-filter hasn't hidden it.
      if (hit && !li.hidden) anyVisible = true;
    });
    if (emptyEl) emptyEl.hidden = anyVisible || !q;
  }

  function setActive(buttons, active) {
    buttons.forEach(function (btn) {
      var on = btn === active;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function wire(controls) {
    var section = document.querySelector(
      '[data-lang-section="' + controls.getAttribute("data-controls") + '"]'
    );
    var list = section && section.querySelector("ul");
    if (!list) return;

    controls.hidden = false; // reveal now that JS is driving it

    var search = controls.querySelector("[data-controls-search]");
    var emptyEl = controls.querySelector("[data-controls-empty]");
    var buttons = Array.prototype.slice.call(
      controls.querySelectorAll("[data-controls-sort]")
    );

    if (search) {
      search.addEventListener("input", function () {
        applySearch(list, search.value, emptyEl);
      });
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mode = btn.getAttribute("data-controls-sort");
        if (mode === "alpha") sortAlpha(list);
        else if (mode === "shuffle") shuffle(list);
        else if (mode === "subscribers") sortNumeric(list, "data-subscribers");
        else if (mode === "followers") sortNumeric(list, "data-followers");
        else sortNumeric(list, "data-score");
        setActive(buttons, mode === "shuffle" ? null : btn);
        if (search && search.value) applySearch(list, search.value, emptyEl);
      });
    });

    // Default state mirrors the build order (popularity score desc).
    var def = controls.querySelector('[data-controls-sort="score"]');
    if (def) setActive(buttons, def);
  }

  function init() {
    var all = document.querySelectorAll("[data-controls]");
    for (var i = 0; i < all.length; i++) wire(all[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
