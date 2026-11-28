export const workspacePaths = {
  home: "/web/",
  search: "/web/search",
  library: "/web/library",
  stickers: "/web/stickers",
};

const accountChangeKey = "memeretrieve-account-change";

export function announceAccountChange() {
  try {
    localStorage.setItem(
      accountChangeKey,
      crypto.getRandomValues(new Uint32Array(2)).join("-"),
    );
  } catch {
    // The server session still changes when browser storage is unavailable.
  }
}

export function mountWorkspace(api, page, navigate) {
  const sidebar = document.createElement("aside");
  sidebar.className = "workspace-sidebar";
  sidebar.innerHTML = `
    <a class="workspace-wordmark" href="${workspacePaths.home}" aria-label="MemeRetrieve home">
      <span class="workspace-logo" aria-hidden="true"><i></i><i></i></span>
      <span>MemeRetrieve</span>
    </a>
    <nav class="workspace-navigation" aria-label="Workspace">
      <a href="${workspacePaths.search}" data-page="search">
        <i class="workspace-icon icon-search" aria-hidden="true"></i><span>Search</span>
      </a>
      <a href="${workspacePaths.library}" data-page="library">
        <i class="workspace-icon icon-library" aria-hidden="true"></i><span>My Library</span>
      </a>
      <a href="${workspacePaths.stickers}" data-page="stickers">
        <i class="workspace-icon icon-stickers" aria-hidden="true"></i><span>Official Stickers</span>
      </a>
    </nav>
    <div class="workspace-account" hidden>
      <span class="workspace-avatar" aria-hidden="true"></span>
      <span id="account-name"></span>
      <button id="sign-out" type="button">Sign out</button>
      <p class="workspace-account-error" role="alert" hidden></p>
    </div>`;
  const skip = document.getElementById("workspace-skip");
  if (skip) skip.after(sidebar);
  else document.body.prepend(sidebar);

  const links = [...sidebar.querySelectorAll("[data-page]")];
  function selectPage(activePage) {
    for (const link of links) {
      if (link.dataset.page === activePage)
        link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }
  selectPage(page);

  sidebar.addEventListener("click", (event) => {
    if (
      event.button ||
      event.ctrlKey ||
      event.shiftKey ||
      event.metaKey ||
      event.altKey
    )
      return;
    const link = event.target.closest("a[href]");
    if (link?.dataset.page && navigate?.(link.dataset.page))
      event.preventDefault();
  });

  if (api.account) {
    sidebar.querySelector(".workspace-account").hidden = false;
    sidebar.querySelector(".workspace-avatar").textContent =
      api.account[0].toUpperCase();
    sidebar.querySelector("#account-name").textContent = api.account;
    sidebar.querySelector("#account-name").title = api.account;
    window.addEventListener("storage", (event) => {
      if (event.key === accountChangeKey)
        location.replace(workspacePaths.search);
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) location.reload();
    });

    const signOut = sidebar.querySelector("#sign-out");
    const error = sidebar.querySelector(".workspace-account-error");
    signOut.addEventListener("click", async () => {
      signOut.disabled = true;
      error.hidden = true;
      try {
        await api.request("/auth/logout", { method: "POST" });
        announceAccountChange();
        location.replace(workspacePaths.search);
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
        signOut.disabled = false;
      }
    });
  }

  return selectPage;
}
