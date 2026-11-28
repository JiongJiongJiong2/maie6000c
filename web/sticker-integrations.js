const signalPackPattern =
  /^https:\/\/signal\.art\/addstickers\/#pack_id=[a-f0-9]{32}&pack_key=[a-f0-9]{64}$/;

function stickerPath(mediaPath, platform) {
  return `/sticker-integrations${mediaPath().replace(/\/media$/, "")}/${platform}`;
}

export function mountDiscordStickers(api, body, mediaPath, signal, download) {
  const features = document.documentElement.dataset;
  if (features.discordStickers !== "true") return;

  const discordActions = document.createElement("div");
  discordActions.className = "sticker-export-actions";
  const discord = document.createElement("button");
  discord.type = "button";
  discord.className = "secondary";
  discord.textContent = "Add to Discord Stickers";
  const destination = document.createElement("p");
  const guild = features.discordGuildName || "the configured server";
  destination.textContent = `Shares this GIF with members of ${guild} as a server sticker.`;
  const status = document.createElement("p");
  status.className = "feedback";
  status.setAttribute("role", "status");
  const openDiscord = document.createElement("a");
  openDiscord.className = "sticker-export-link";
  openDiscord.textContent = "Open Discord server";
  openDiscord.hidden = true;
  discordActions.append(discord, destination, status, openDiscord);
  body.append(discordActions);

  let added = false;
  const eligible = () => !signal.aborted && !download?.hidden;
  function syncVisibility() {
    discordActions.hidden = !eligible();
  }

  discord.addEventListener("click", async () => {
    if (!eligible() || discord.disabled || added) return;
    discord.disabled = true;
    discord.textContent = "Adding to Discord…";
    destination.hidden = true;
    status.classList.remove("error");
    status.textContent = "Preparing and uploading the animated sticker…";
    try {
      const sticker = await api.request(stickerPath(mediaPath, "discord"), {
        method: "POST",
        signal,
      });
      if (!sticker?.id || !sticker.name)
        throw new Error("Discord did not confirm the sticker.");
      if (!signal.aborted) {
        added = true;
        discord.textContent = sticker.already_added
          ? "Already in Discord"
          : "Added to Discord";
        status.textContent = `Find “${sticker.name}” in the Stickers tab of a channel in ${guild}.`;
        if (/^[0-9]{17,20}$/.test(sticker.guild_id)) {
          openDiscord.href = `https://discord.com/channels/${sticker.guild_id}`;
          openDiscord.hidden = false;
        }
      }
    } catch (error) {
      if (!signal.aborted) {
        discord.textContent = "Retry adding to Discord";
        status.classList.add("error");
        status.textContent = error.serverMessage || error.message;
      }
    } finally {
      discord.disabled = added;
    }
  });

  download?.addEventListener("eligibilitychange", syncVisibility);
  syncVisibility();
}

export function mountSignalStickers(api, body, mediaPath, signal, download) {
  if (document.documentElement.dataset.signalStickers !== "true") return;

  const actions = document.createElement("div");
  actions.className = "sticker-export-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = "Add Sticker to Signal";
  const notice = document.createElement("p");
  notice.textContent =
    "Creates a pack with this GIF. Anyone with the link can open it.";
  const status = document.createElement("p");
  status.className = "feedback";
  status.setAttribute("role", "status");
  const install = document.createElement("a");
  install.className = "sticker-export-link";
  install.textContent = "Open Signal to install";
  install.referrerPolicy = "no-referrer";
  install.hidden = true;
  actions.append(button, notice, status, install);
  body.append(actions);

  const eligible = () => !signal.aborted && !download?.hidden;
  function syncVisibility() {
    actions.hidden = !eligible();
  }
  button.addEventListener("click", async () => {
    if (!eligible() || button.disabled) return;
    button.disabled = true;
    button.textContent = "Preparing Signal sticker…";
    status.classList.remove("error");
    status.textContent = "Preparing and uploading your animated sticker pack…";
    try {
      const pack = await api.request(stickerPath(mediaPath, "signal"), {
        method: "POST",
        timeout: 90000,
        signal,
      });
      if (signal.aborted) return;
      if (!signalPackPattern.test(pack?.url))
        throw new Error("Signal did not return a valid sticker pack link.");
      button.textContent = "Signal sticker ready";
      status.textContent =
        "Open Signal and tap Install to use it from the sticker picker.";
      install.href = pack.url;
      install.hidden = false;
    } catch (error) {
      if (signal.aborted) return;
      button.disabled = false;
      button.textContent = "Retry creating Signal sticker";
      status.classList.add("error");
      status.textContent = error.serverMessage || error.message;
    }
  });

  download?.addEventListener("eligibilitychange", syncVisibility);
  syncVisibility();
}
