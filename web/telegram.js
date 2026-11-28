let session;
let active;

function sessionRequest(api, path, method, signal, body) {
  const headers = session ? { "X-Telegram-Session": session } : {};
  if (body) headers["Content-Type"] = "application/json";
  return api.request(`/telegram/${path}`, {
    method,
    signal,
    timeout: method === "POST" ? 60000 : 15000,
    headers,
    body: body && JSON.stringify(body),
  });
}

export async function disconnectTelegram(api) {
  if (!session) return;
  const request = sessionRequest(api, "session", "DELETE");
  session = undefined;
  await request;
}

const dialog = document.querySelector("#telegram-save-dialog");
const status = document.querySelector("#telegram-save-status");
const qr = document.querySelector("#telegram-save-qr");
const close = document.querySelector("#telegram-save-close");
const disconnect = document.querySelector("#telegram-save-disconnect");
const loginForm = document.querySelector("#telegram-login-form");
const loginLabel = document.querySelector("#telegram-login-label");
const loginValue = document.querySelector("#telegram-login-value");
const loginSubmit = document.querySelector("#telegram-login-submit");
const loginSwitch = document.querySelector("#telegram-login-switch");
const regionField = document.querySelector("#telegram-login-region-field");
const regionSelect = document.querySelector("#telegram-login-region");
const loginHint = document.querySelector("#telegram-login-hint");
const restart = document.querySelector("#telegram-login-restart");
const retry = document.querySelector("#telegram-save-retry");

function messageFor(error) {
  if (error.code === "network_error")
    return "The connection was interrupted. Check your network and try again.";
  if (error.status === 401)
    return "Sign in to MemeRetrieve before saving to Telegram.";
  if (error.code === "telegram_collection_full")
    return "Your Telegram GIF collection is full. Remove a saved GIF in Telegram, then try again.";
  if (error.code === "media_expired" || error.code === "candidate_not_found")
    return "This GIF is no longer available. Start a new search and choose a GIF.";
  return error.serverMessage || error.message;
}

function clearQr() {
  qr.hidden = true;
  qr.removeAttribute("src");
}

close.addEventListener("click", () => dialog.close());
dialog.addEventListener("cancel", (event) => {
  if (close.disabled) event.preventDefault();
});
dialog.addEventListener("close", () => {
  active?.abort();
  clearQr();
});

function setSession(result) {
  if (typeof result.session !== "string" || !result.session)
    throw new Error("Could not start a Telegram session. Try again.");
  session = result.session;
}

async function authorizeQr(api, signal) {
  setSession(await sessionRequest(api, "session", "POST"));
  while (!signal.aborted) {
    const result = await sessionRequest(api, "session", "GET", signal);
    if (result.state === "authorized") return;
    if (result.state === "failed") {
      const error = new Error(
        result.message || "Telegram sign-in failed. Try again.",
      );
      error.code = result.code;
      throw error;
    }
    if (result.state !== "waiting")
      throw new Error("Could not confirm your Telegram sign-in. Try again.");
    if (result.qr) {
      const src = `data:image/png;base64,${result.qr}`;
      if (qr.getAttribute("src") !== src) qr.src = src;
      qr.hidden = false;
      status.textContent =
        "In the Telegram app, go to Settings → Devices → Link Desktop Device and scan this QR code. This opens a temporary session and saves the selected GIF.";
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

async function authorizePhone(api, signal) {
  if (signal.aborted) return;
  if (regionSelect.options.length === 1) {
    status.textContent = "Loading country codes…";
    const regions = await sessionRequest(api, "regions", "GET", signal);
    const names =
      typeof Intl.DisplayNames === "function"
        ? new Intl.DisplayNames(["en"], { type: "region" })
        : null;
    const options = Object.entries(regions)
      .map(([code, prefix]) => [
        code,
        `${names?.of(code) || code} (+${prefix})`,
      ])
      .sort((a, b) => a[1].localeCompare(b[1], "en"));
    regionSelect.append(
      ...options.map(([code, label]) => new Option(label, code)),
    );
    const region = navigator.language
      .match(/-([a-z]{2})$/i)?.[1]
      ?.toUpperCase();
    if (region && regions[region]) regionSelect.value = region;
  }
  if (signal.aborted) return;
  let step = "phone";
  let phone = "";
  let cooldownUntil = 0;
  let verifyAfter = 0;
  const fields = {
    phone: [
      "Telegram phone number",
      "tel",
      "tel",
      "tel",
      "Get verification code",
      "Use the phone number linked to your Telegram account. This opens a temporary Telegram session for up to 15 minutes.",
    ],
    code: [
      "Telegram verification code",
      "text",
      "numeric",
      "one-time-code",
      "Confirm and save",
      "Check your phone for the Telegram verification code, then return to this tab to enter it.",
    ],
    password: [
      "Telegram two-step verification password",
      "password",
      "text",
      "off",
      "Confirm and save",
      "Enter your Telegram two-step verification password to continue.",
    ],
  };
  function updateCooldown() {
    const seconds = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
    const submitDelay =
      step === "phone"
        ? seconds
        : Math.max(0, Math.ceil((verifyAfter - Date.now()) / 1000));
    restart.disabled = seconds > 0;
    restart.textContent = seconds
      ? `Request a new code in ${seconds}s`
      : "Change number or request a new code";
    loginSubmit.disabled = submitting || submitDelay > 0;
    loginSubmit.textContent =
      submitDelay > 0 ? `Try again in ${submitDelay}s` : fields[step][4];
  }
  function render(message) {
    const [label, type, mode, complete, , help] = fields[step];
    loginLabel.textContent = label;
    loginValue.type = type;
    loginValue.inputMode = mode;
    loginValue.autocomplete = complete;
    loginValue.maxLength =
      step === "password" ? 256 : step === "phone" ? 40 : 10;
    loginValue.value = step === "phone" ? phone : "";
    regionField.hidden = step !== "phone";
    restart.hidden = step === "phone";
    loginHint.textContent =
      step === "phone"
        ? "Choose a country code and enter your local number, or paste the full number, such as +852 5555 0123."
        : step === "code"
          ? "Didn't get a code? Check the Telegram service chat. You can request a new code when the countdown ends."
          : "Use the two-step verification password you set in Telegram.";
    status.textContent = message || help;
    updateCooldown();
  }
  let submitting = false;
  loginForm.hidden = false;
  render();
  const timer = setInterval(updateCooldown, 250);
  return new Promise((resolve, reject) => {
    const abort = () => {
      if (!submitting) resolve();
    };
    const restartPhone = (message) => {
      void disconnectTelegram(api).catch(() => {});
      step = "phone";
      render(message);
    };
    signal.addEventListener("abort", abort, { once: true });
    restart.onclick = () => {
      if (!submitting && !restart.disabled)
        restartPhone("Check your number, then request a new code.");
    };
    loginForm.onsubmit = async (event) => {
      event.preventDefault();
      if (submitting || loginSubmit.disabled || signal.aborted) return;
      let value = loginValue.value;
      if (step === "phone") {
        phone = value;
        const compact = value
          .normalize("NFKC")
          .trim()
          .replace(/[\s()-]/g, "");
        if (
          !/^\+?[0-9]{4,15}$/.test(compact) ||
          (!regionSelect.value && !/^\+|^00/.test(compact))
        ) {
          status.textContent =
            "Choose a country code and enter a phone number, or enter the full number starting with +.";
          return;
        }
      } else {
        if (step === "code") {
          value = value.normalize("NFKC").trim();
          if (!/^[0-9]{3,10}$/.test(value)) {
            status.textContent = "Enter the numeric code Telegram sent you.";
            return;
          }
        }
        loginValue.value = "";
      }
      submitting = true;
      status.textContent =
        step === "phone" ? "Requesting a code…" : "Verifying…";
      updateCooldown();
      try {
        const result = await sessionRequest(
          api,
          `session/${step}`,
          "POST",
          step === "phone" ? undefined : signal,
          step === "phone"
            ? { phone: value, region: regionSelect.value || null }
            : { value },
        );
        if (step === "phone") {
          setSession(result);
          cooldownUntil =
            Date.now() + Math.max(0, result.retry_after || 0) * 1000;
          verifyAfter = 0;
        }
        if (signal.aborted || result.state === "authorized") {
          resolve();
          return;
        }
        if (!["code", "password"].includes(result.state))
          throw new Error(
            "Could not confirm your Telegram sign-in. Try again.",
          );
        step = result.state;
        render(result.message);
      } catch (error) {
        if (signal.aborted) resolve();
        else if (error.status === 401) reject(error);
        else if (
          [
            "telegram_session_missing",
            "telegram_code_expired",
            "telegram_login_restart",
          ].includes(error.code)
        )
          restartPhone(messageFor(error));
        else {
          if (error.retryAfter > 0) {
            const retryAt = Date.now() + error.retryAfter * 1000;
            if (step === "phone") cooldownUntil = retryAt;
            else verifyAfter = retryAt;
          }
          status.textContent = messageFor(error);
        }
      } finally {
        submitting = false;
        updateCooldown();
      }
    };
  }).finally(() => {
    clearInterval(timer);
    loginForm.onsubmit = null;
    restart.onclick = null;
    loginForm.hidden = true;
    loginValue.value = "";
  });
}

function waitForRetry(label, delay, signal) {
  if (signal.aborted) return Promise.resolve(false);
  const available = Date.now() + Math.max(0, delay) * 1000;
  retry.hidden = false;
  const render = () => {
    const seconds = Math.max(0, Math.ceil((available - Date.now()) / 1000));
    retry.disabled = seconds > 0;
    retry.textContent = seconds ? `Try again in ${seconds}s` : label;
  };
  render();
  const timer = setInterval(render, 250);
  return new Promise((resolve) => {
    retry.onclick = () => resolve(true);
    signal.addEventListener("abort", () => resolve(false), { once: true });
  }).finally(() => {
    clearInterval(timer);
    retry.onclick = null;
    retry.hidden = true;
  });
}

async function authorize(api, signal) {
  if (session) {
    const result = await sessionRequest(api, "session", "GET", signal);
    if (result.state === "authorized") return;
    await disconnectTelegram(api);
  }
  if (signal.aborted) return;
  if (matchMedia("(pointer: coarse)").matches) {
    await authorizePhone(api, signal);
    return;
  }
  const qrController = new AbortController();
  let usePhone = false;
  const abort = () => qrController.abort();
  signal.addEventListener("abort", abort, { once: true });
  loginSwitch.hidden = false;
  loginSwitch.onclick = () => {
    usePhone = true;
    abort();
  };
  try {
    await authorizeQr(api, qrController.signal);
  } catch (error) {
    if (error.code === "telegram_qr_password_required") usePhone = true;
    if (!usePhone) throw error;
  } finally {
    signal.removeEventListener("abort", abort);
    loginSwitch.hidden = true;
    loginSwitch.onclick = null;
  }
  if (usePhone && !signal.aborted) {
    clearQr();
    await disconnectTelegram(api);
    await authorizePhone(api, signal);
  }
}

async function collect(api, candidateId, cardSignal) {
  if (active || dialog.open || cardSignal.aborted) return;
  const controller = new AbortController();
  active = controller;
  const { signal } = controller;
  const abort = () => {
    controller.abort();
    if (!close.disabled && dialog.open) dialog.close();
  };
  cardSignal.addEventListener("abort", abort, { once: true });
  let authorized = false;
  let requestedSave = false;
  close.disabled = false;
  disconnect.hidden = true;
  status.textContent = "Connecting to Telegram…";
  dialog.showModal();
  try {
    try {
      await authorize(api, signal);
    } catch (error) {
      if (error.code !== "telegram_session_missing" || signal.aborted)
        throw error;
      session = undefined;
      await authorize(api, signal);
    }
    if (signal.aborted) return;
    authorized = true;
    clearQr();
    while (!signal.aborted) {
      status.textContent = "Saving GIF…";
      close.disabled = true;
      requestedSave = true;
      try {
        const result = await sessionRequest(
          api,
          `gifs/${encodeURIComponent(candidateId)}`,
          "POST",
        );
        if (result.saved !== true)
          throw new Error("Telegram has not confirmed the save.");
        status.textContent =
          "Added to your saved GIFs in Telegram. Find it in the GIF picker in any chat.";
        break;
      } catch (error) {
        const expired = error.code === "telegram_session_missing";
        if (expired) {
          session = undefined;
          authorized = false;
        } else if (
          !(
            error.status === 429 ||
            error.status >= 500 ||
            error.code === "telegram_collection_full" ||
            error.code === "network_error"
          )
        ) {
          throw error;
        }
        status.textContent = messageFor(error);
        close.disabled = false;
        if (
          !(await waitForRetry(
            expired ? "Reconnect Telegram" : "Retry save",
            error.retryAfter || 0,
            signal,
          ))
        )
          break;
        if (expired) {
          await authorize(api, signal);
          if (signal.aborted) break;
          authorized = true;
          clearQr();
        }
      }
    }
  } catch (error) {
    if (error.code === "telegram_session_missing") {
      session = undefined;
      authorized = false;
    }
    if (dialog.open) status.textContent = messageFor(error);
  } finally {
    cardSignal.removeEventListener("abort", abort);
    clearQr();
    close.disabled = false;
    active = undefined;
    if (!authorized) void disconnectTelegram(api).catch(() => {});
    if (signal.aborted && requestedSave && dialog.open) dialog.close();
    disconnect.hidden = !authorized || !session;
    disconnect.onclick = async () => {
      disconnect.disabled = true;
      close.disabled = true;
      try {
        await disconnectTelegram(api);
        disconnect.hidden = true;
        status.textContent = "Disconnected from Telegram.";
      } catch (error) {
        status.textContent = messageFor(error);
      } finally {
        disconnect.disabled = false;
        close.disabled = false;
      }
    };
  }
}

export function mountTelegramSave(api, body, download, candidateId, signal) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = "Add to Telegram GIFs";
  button.setAttribute("aria-haspopup", "dialog");
  const syncVisibility = () => {
    button.hidden = download.hidden;
  };
  syncVisibility();
  download.addEventListener("eligibilitychange", syncVisibility);
  button.addEventListener("click", () => {
    if (!download.hidden) void collect(api, candidateId, signal);
  });
  body.append(button);
}
