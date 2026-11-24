/* RELUX Lead Management – lightweight UI behaviour (no framework). */
(function () {
  "use strict";

  // Sidebar toggle (mobile)
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.getElementById("sidebar-backdrop");
  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("-translate-x-full", !open);
    if (backdrop) backdrop.classList.toggle("hidden", !open);
    document.body.classList.toggle("overflow-hidden", open);
  }
  document.querySelectorAll("[data-sidebar-open]").forEach(function (el) {
    el.addEventListener("click", function () { setSidebar(true); });
  });
  document.querySelectorAll("[data-sidebar-close]").forEach(function (el) {
    el.addEventListener("click", function () { setSidebar(false); });
  });

  // Dropdowns
  document.querySelectorAll("[data-dropdown]").forEach(function (dd) {
    var toggle = dd.querySelector("[data-dropdown-toggle]");
    var menu = dd.querySelector("[data-dropdown-menu]");
    if (!toggle || !menu) return;
    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.classList.contains("hidden");
      document.querySelectorAll("[data-dropdown-menu]").forEach(function (m) { m.classList.add("hidden"); });
      menu.classList.toggle("hidden", !open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll("[data-dropdown-menu]").forEach(function (m) { m.classList.add("hidden"); });
  });

  // Dismissible flash messages (auto-hide success after 6s)
  document.querySelectorAll("[data-dismiss]").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.parentElement.remove(); });
  });
  setTimeout(function () {
    document.querySelectorAll("#flash-messages .bg-emerald-50").forEach(function (el) { el.remove(); });
  }, 6000);

  // Confirmation modal for destructive forms: <form data-confirm="Message">
  var modal = document.getElementById("confirm-modal");
  var pendingForm = null;
  function closeModal() {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    pendingForm = null;
  }
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-confirm]") || form.dataset.confirmed === "1" || !modal) return;
    e.preventDefault();
    pendingForm = form;
    document.getElementById("confirm-text").textContent = form.dataset.confirm;
    var ok = document.getElementById("confirm-ok");
    ok.textContent = form.dataset.confirmLabel || "Confirm";
    ok.className = form.dataset.confirmStyle === "primary" ? "btn-primary" : "btn-danger";
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    ok.focus();
  }, true);
  if (modal) {
    modal.querySelectorAll("[data-confirm-cancel]").forEach(function (el) { el.addEventListener("click", closeModal); });
    document.getElementById("confirm-ok").addEventListener("click", function () {
      if (pendingForm) {
        var f = pendingForm;
        f.dataset.confirmed = "1";
        closeModal();
        if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); }
      }
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });
  }

  // Prevent double submits on forms marked data-once
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-once]") || e.defaultPrevented) return;
    if (form.dataset.submitting === "1") { e.preventDefault(); return; }
    form.dataset.submitting = "1";
    // Disable after the browser has captured the form data (keeps the clicked button's name/value).
    setTimeout(function () {
      form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) {
        b.disabled = true;
        if (b.dataset.loadingText) b.textContent = b.dataset.loadingText;
      });
    }, 0);
  });

  // Auto-submit filter selects: <select data-autosubmit>
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form && el.form.submit(); });
  });

  // Select-all checkboxes: <input type=checkbox data-select-all="name">
  document.querySelectorAll("[data-select-all]").forEach(function (master) {
    master.addEventListener("change", function () {
      document.querySelectorAll('input[type=checkbox][name="' + master.dataset.selectAll + '"]').forEach(function (cb) {
        cb.checked = master.checked;
      });
      document.dispatchEvent(new Event("selection-changed"));
    });
  });
  function updateSelectionCount() {
    document.querySelectorAll("[data-selection-count]").forEach(function (el) {
      var n = document.querySelectorAll('input[type=checkbox][name="' + el.dataset.selectionCount + '"]:checked').length;
      el.textContent = n;
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("input[type=checkbox]")) updateSelectionCount();
  });
  document.addEventListener("selection-changed", updateSelectionCount);

  // Copy-to-clipboard buttons: <button data-copy="text">
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      navigator.clipboard && navigator.clipboard.writeText(btn.dataset.copy).then(function () {
        var old = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(function () { btn.textContent = old; }, 1500);
      });
    });
  });

  // Simple modal open/close: <button data-modal-open="id">, inside modal [data-modal-close]
  document.querySelectorAll("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var m = document.getElementById(btn.dataset.modalOpen);
      if (m) { m.classList.remove("hidden"); m.classList.add("flex"); }
    });
  });
  document.querySelectorAll("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var m = btn.closest("[data-modal]");
      if (m) { m.classList.add("hidden"); m.classList.remove("flex"); }
    });
  });
})();
