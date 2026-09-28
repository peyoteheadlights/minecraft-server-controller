/* Applies the saved appearance before the first paint, so a dark-mode user
   never sees a white flash. Loaded as a file because the page's
   Content-Security-Policy forbids inline scripts. */
(function () {
  try {
    var saved = localStorage.getItem("mcsc_theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) { /* storage unavailable: follow the system setting */ }
})();
