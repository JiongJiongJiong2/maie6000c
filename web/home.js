import { mountMotion } from "./motion.js";
import { workspacePaths } from "./workspace.js";

// Older search links point to this anchor on the former combined page.
function followLegacySearchLink() {
  if (location.hash === "#workspace") {
    location.replace(workspacePaths.search + location.search + location.hash);
  }
}
followLegacySearchLink();
window.addEventListener("hashchange", followLegacySearchLink);

const art = document.getElementById("hero-art");
function resetEyes() {
  art.style.removeProperty("--eye-x");
  art.style.removeProperty("--eye-y");
}
const motionEnabled = mountMotion(
  document.getElementById("motion-toggle"),
  resetEyes,
);
const caption = document.getElementById("mascot-caption");
const mascotLines = [
  "I was framed. Literally.",
  "No thoughts. Just loops.",
  "Please return me to the group chat.",
  "I'm not lost. I'm buffering.",
  "head empty. GIF folder full.",
];
let boops = 0;

document.getElementById("mascot").addEventListener("click", () => {
  caption.textContent = mascotLines[boops++ % mascotLines.length];
});
art.addEventListener("pointermove", (event) => {
  if (!motionEnabled() || event.pointerType !== "mouse") return;
  const bounds = art.getBoundingClientRect();
  const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 12;
  const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 10;
  art.style.setProperty("--eye-x", `${x.toFixed(1)}px`);
  art.style.setProperty("--eye-y", `${y.toFixed(1)}px`);
});
art.addEventListener("pointerleave", resetEyes);
