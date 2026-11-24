/* Shared Tailwind theme – used by the CDN runtime (development) and by the standalone CLI build. */
(function () {
  var theme = {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"] },
      colors: {
        brand: {
          50: "#ecf8f0", 100: "#d2eedb", 200: "#a7dcb9", 300: "#72c491", 400: "#43a96a",
          500: "#24914f", 600: "#1b8042", 700: "#166737", 800: "#14522f", 900: "#114428",
        },
        electric: {
          50: "#eef5ff", 100: "#d9e8ff", 200: "#bcd7ff", 300: "#8ebdff", 400: "#5998ff",
          500: "#3373ff", 600: "#0f5bf5", 700: "#0a47e1", 800: "#0f3bb6", 900: "#13368f",
        },
      },
      boxShadow: { glow: "0 10px 40px -12px rgba(15, 91, 245, 0.35)" },
    },
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { content: ["./templates/**/*.html", "./static/js/**/*.js", "./apps/**/*.py"], theme: theme };
  } else if (typeof tailwind !== "undefined") {
    tailwind.config = { theme: theme };
  }
})();
