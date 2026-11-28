export function mountDiscordStickers(api, body, mediaPath, signal, download) {
  const features = document.documentElement.dataset;
  if (features.discordStickers !== "true") return;

  const discordActions = document.createElement("div");
  discordActions.className = "discord-sticker-actions";
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
  openDiscord.className = "discord-sticker-link";
  openDiscord.textContent = "Open Discord server";
  openDiscord.hidden = true;
  discordActions.append(discord, destination, status, openDiscord);
  body.append(discordActions);

  let added = false;
  const eligible = () => !signal.aborted && !download?.hidden;
  function path() {
    return `/sticker-integrations${mediaPath().replace(/\/media$/, "")}`;
  }

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
      const sticker = await api.request(`${path()}/discord`, {
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
