/**
 * lang-filter.js — client-side language filter for the YouTuber directory.
 *
 * Works by reading `data-lang` attributes stamped on every table row and
 * list item during the static build, then showing/hiding them based on the
 * visitor's browser language preference (navigator.languages).
 *
 * All forms of English (en-US, en-GB, en-AU, …) are normalised to "en".
 * The user's choice (filtered vs. all) is persisted in localStorage.
 *
 * Section headings/wrappers carry `data-lang-section` and are hidden when
 * every item inside them is filtered out.
 */
(function () {
  "use strict";

  /** Normalise a BCP 47 tag to its base language code ("en-US" -> "en"). */
  function baseLang(tag) {
    return (tag || "").split("-")[0].toLowerCase();
  }

  /**
   * Build the set of preferred base language codes from navigator.languages.
   * Always includes "en" as a fallback so English content is never orphaned.
   */
  function preferredLangs() {
    var langs = navigator.languages
      ? Array.prototype.slice.call(navigator.languages)
      : navigator.language
      ? [navigator.language]
      : ["en"];
    var bases = langs.map(baseLang).filter(Boolean);
    // Deduplicate while preserving order.
    var seen = {};
    return bases.filter(function (l) {
      if (seen[l]) return false;
      seen[l] = true;
      return true;
    });
  }

  var preferred = preferredLangs();

  /** Return true if the item's language should be visible in filtered mode. */
  function isPreferred(lang) {
    if (!lang) return true; // no tag = always show
    return preferred.indexOf(baseLang(lang)) !== -1;
  }

  /**
   * Apply (or remove) the language filter.
   * @param {boolean} showAll  When true every item is shown regardless of lang.
   */
  function applyFilter(showAll) {
    // 1. Show/hide individual rows and list items.
    var items = document.querySelectorAll("[data-lang]");
    for (var i = 0; i < items.length; i++) {
      var el = items[i];
      el.hidden = !showAll && !isPreferred(el.getAttribute("data-lang"));
    }

    // 2. Hide entire section wrappers when all their items are hidden.
    var sections = document.querySelectorAll("[data-lang-section]");
    for (var s = 0; s < sections.length; s++) {
      var section = sections[s];
      if (showAll) {
        section.hidden = false;
        continue;
      }
      var children = section.querySelectorAll("[data-lang]");
      var anyVisible = false;
      for (var c = 0; c < children.length; c++) {
        if (!children[c].hidden) {
          anyVisible = true;
          break;
        }
      }
      section.hidden = !anyVisible;
    }

    // 3. Update the toggle button label and state.
    var btn = document.getElementById("lang-filter-btn");
    if (btn) {
      btn.textContent = showAll
        ? "\u{1F30D} Show my language only"
        : "\u{1F30D} Show all languages";
      btn.setAttribute("aria-pressed", showAll ? "false" : "true");
    }

    // 4. Show/hide the "no results" banner if present.
    var banner = document.getElementById("lang-filter-empty");
    if (banner) {
      var allHidden = true;
      for (var j = 0; j < items.length; j++) {
        if (!items[j].hidden) {
          allHidden = false;
          break;
        }
      }
      banner.hidden = !allHidden || showAll;
    }
  }

  function init() {
    var btn = document.getElementById("lang-filter-btn");
    if (!btn) return; // no filter UI on this page

    // Restore persisted preference; default to filtered (false = filtering on).
    var stored = localStorage.getItem("lang-show-all");
    var showAll = stored === "true";

    btn.addEventListener("click", function () {
      showAll = !showAll;
      try {
        localStorage.setItem("lang-show-all", showAll);
      } catch (_) {}
      applyFilter(showAll);
    });

    applyFilter(showAll);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
