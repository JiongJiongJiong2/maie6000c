const preferenceKey = "memeretrieve-motion";

export function mountMotion(button, onDisable) {
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let preference = "on";

  function loadPreference() {
    try {
      preference = localStorage.getItem(preferenceKey) || "on";
    } catch {
      // The motion control also works without optional browser storage.
    }
  }

  function enabled() {
    return preference !== "off" && !reducedMotion.matches;
  }

  function update() {
    const active = enabled();
    document.documentElement.dataset.motion = active ? "on" : "off";
    button.setAttribute("aria-pressed", String(active));
    button.textContent = reducedMotion.matches
      ? "Motion: reduced"
      : `Motion: ${active ? "on" : "off"}`;
    button.disabled = reducedMotion.matches;
    if (!active) onDisable();
  }

  button.addEventListener("click", () => {
    preference = enabled() ? "off" : "on";
    try {
      localStorage.setItem(preferenceKey, preference);
    } catch {
      // Keep the preference for the current page.
    }
    update();
  });
  reducedMotion.addEventListener("change", update);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      loadPreference();
      update();
    }
  });
  loadPreference();
  update();
  return enabled;
}
