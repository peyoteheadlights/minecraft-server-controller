/* Applies the saved theme and Simple/Technical choice before the first
   paint, so nobody sees a white flash or the wrong amount of detail.
   Loaded as a file because the page's Content-Security-Policy forbids
   inline scripts. The account's saved choices arrive after sign-in and
   replace these if they differ. */
(function () {
  var root = document.documentElement;
  try {
    var theme = localStorage.getItem("mcsc_theme");
    if (theme === "light" || theme === "dark" || theme === "graphite" || theme === "contrast") {
      root.setAttribute("data-theme", theme);
    }
    root.setAttribute("data-mode", localStorage.getItem("mcsc_mode") === "technical" ? "technical" : "simple");
  } catch (e) {
    root.setAttribute("data-mode", "simple");  /* storage unavailable: the defaults */
  }
})();
