const $ = (id) => document.getElementById(id);
const setupKey = "memeretrieve-owner-setup";
let setup = null;
if (location.pathname === "/web/sign-in") {
  setup =
    new URLSearchParams(location.hash.slice(1)).get("setup") ||
    sessionStorage.getItem(setupKey);
  if (setup) {
    sessionStorage.setItem(setupKey, setup);
    history.replaceState(null, "", location.pathname);
  }
}
const modes = $("account-modes");
const registerMode = modes.querySelector('[value="register"]');
registerMode.checked = Boolean(setup);
modes.querySelector('[value="login"]').checked = !setup;

function render() {
  const register = registerMode.checked;
  const title = register ? "Create an account" : "Sign in";
  document.title = title + " · MemeRetrieve";
  $("account-title").textContent = title;
  document.querySelector(".heading-sticker").dataset.sticker = register
    ? "glove"
    : "flower";
  $("account-intro").textContent =
    register && setup
      ? "Create an account for the GIF collection already on this Mac."
      : register
        ? "Choose a username and password for your new library."
        : "Open your personal collection.";
  $("account-submit").textContent = register ? "Create account" : "Sign in";
  $("password").autocomplete = register ? "new-password" : "current-password";
  $("password").minLength = register ? 8 : 1;
  $("password").placeholder = register ? "At least 8 characters" : "";
  $("account-error").hidden = true;
}
modes.addEventListener("change", () => {
  $("password").value = "";
  render();
});
$("account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("account-submit").disabled = true;
  const register = registerMode.checked;
  modes.disabled = true;
  try {
    const body = {
      username: $("username").value,
      password: $("password").value,
    };
    if (register && setup) body.owner_setup = setup;
    const response = await fetch(register ? "/auth/register" : "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "Check your username and password.",
      );
    sessionStorage.removeItem(setupKey);
    localStorage.setItem(
      "memeretrieve-account-change",
      crypto.getRandomValues(new Uint32Array(2)).join("-"),
    );
    location.replace("/web/");
  } catch (error) {
    $("account-error").textContent = error.message;
    $("account-error").hidden = false;
  } finally {
    $("account-submit").disabled = false;
    modes.disabled = false;
  }
});
render();

// Two matching strips make the horizontal loop seamless at every viewport width.
const parade = document.querySelector(".parade-track");
parade.append(parade.firstElementChild.cloneNode(true));

// Keep the clusters composed around the paper, with a little variation on each visit.
for (const sticker of document.querySelectorAll(
  ".sticker-cluster .account-sticker",
)) {
  sticker.style.setProperty(
    "--nudge-x",
    (Math.random() * 8 - 4).toFixed(1) + "px",
  );
  sticker.style.setProperty(
    "--nudge-y",
    (Math.random() * 6 - 3).toFixed(1) + "px",
  );
  sticker.style.setProperty(
    "--extra-turn",
    (Math.random() * 12 - 6).toFixed(1) + "deg",
  );
  sticker.style.setProperty("--delay", (-Math.random() * 6).toFixed(2) + "s");
}
