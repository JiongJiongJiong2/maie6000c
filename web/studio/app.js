"use strict";
const $ = (id) => document.getElementById(id);
let editing = null;
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
async function api(url, options) {
  const r = await fetch(url, options);
  let data;
  try {
    data = await r.json();
  } catch {
    throw new Error("服务返回了无法读取的响应");
  }
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "请求失败，请检查输入或稍后重试",
    );
  return data;
}
function status(text, error = false) {
  $("status").textContent = text;
  $("status").className = error ? "error" : "";
}
function busy(form, value) {
  form.querySelectorAll("button").forEach((b) => (b.disabled = value));
}
function card(c) {
  const box = node("article", undefined, "card"),
    media = node("div", undefined, "media"),
    img = node("img");
  img.src = c.media_url;
  img.alt = c.title || "候选梗图";
  img.loading = "lazy";
  img.onerror = () => {
    media.replaceChildren(
      node("p", "图片加载失败，请查看来源或重试。", "error"),
    );
  };
  media.append(img);
  const body = node("div", undefined, "cardbody");
  body.append(node("h3", c.title || "未命名图片"));
  body.append(
    node(
      "div",
      `${c.provider} · ${c.format} · ${c.width} × ${c.height} · ${c.frames} 帧${c.animated ? " · 动图" : ""}`,
      "meta",
    ),
  );
  if (c.source_url) {
    try {
      const u = new URL(c.source_url);
      if (u.protocol === "https:") {
        const a = node("a", "查看来源页面 ↗", "source");
        a.href = u.href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        body.append(a);
      }
    } catch {}
  }
  const actions = node("div", undefined, "actions"),
    save = node("button", c.saved ? "已收藏 ✓" : "确认收藏 ＋");
  save.disabled = !!c.saved;
  save.onclick = async () => {
    save.disabled = true;
    save.textContent = "正在建立索引…";
    try {
      const r = await api(`/api/candidates/${encodeURIComponent(c.id)}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      save.textContent = "已收藏 ✓";
      c.saved = true;
      status(r.duplicate ? "这张图已在收藏中。" : "已保存到收藏，索引完成。");
      if (save.closest("#edit-preview"))
        $("edit-status").textContent = "已收藏，图片索引完成。";
      await loadLibrary();
    } catch (e) {
      status(e.message, true);
      if (save.closest("#edit-preview"))
        $("edit-status").textContent = e.message;
      save.textContent = "确认收藏 ＋";
      save.disabled = false;
    }
  };
  actions.append(save);
  if (c.editable && !c.animated) {
    const edit = node("button", "空白模板加字");
    edit.className = "secondary";
    edit.onclick = () => {
      editing = c;
      $("edit-original").src = c.media_url;
      $("top").value = "";
      $("bottom").value = "";
      $("edit-preview").replaceChildren();
      $("edit-status").textContent = "";
      $("editor").showModal();
      $("top").focus();
    };
    actions.append(edit);
  }
  body.append(actions);
  box.append(media, body);
  return box;
}
function render(id, items) {
  $(id).replaceChildren(
    ...(items.length
      ? items.map(card)
      : [
          node(
            "p",
            id === "library"
              ? "收藏还空着。检查候选后，点击「确认收藏」。"
              : "没有找到候选，试试换一种描述。",
            "empty",
          ),
        ]),
  );
}
async function loadLibrary() {
  try {
    const r = await api("/api/library");
    render("library", r.items);
    $("library-count").textContent = `${r.items.length} 张已收藏`;
  } catch (e) {
    $("library").replaceChildren(node("p", e.message, "error"));
  }
}
$("reference").onchange = () => {
  $("reference-name").textContent =
    $("reference").files[0]?.name || "可只用文字，也可用截图搜索收藏";
};
$("search-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  if (!$("query").value.trim() && !$("reference").files.length) {
    status("请填写描述，或添加参考截图。", true);
    return;
  }
  const data = new FormData();
  data.append("query", $("query").value);
  data.append("scope", $("scope").value);
  if ($("reference").files[0]) data.append("image", $("reference").files[0]);
  busy(form, true);
  status("正在寻找原图与模板，检索可能需要约 90 秒…");
  $("warnings").replaceChildren();
  try {
    const r = await api("/api/search", { method: "POST", body: data });
    render("results", r.candidates);
    $("result-count").textContent = `${r.candidates.length} 张候选`;
    $("warnings").replaceChildren(...r.warnings.map((w) => node("p", w)));
    $("trace").replaceChildren(
      ...r.trace.map((t) => node("p", `${t.step}：${t.detail}`)),
    );
    $("tracebox").hidden = !r.trace.length;
    status("检索完成。请检查画面与来源，再确认收藏。");
  } catch (e) {
    status(e.message, true);
  } finally {
    busy(form, false);
  }
};
$("import-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = e.currentTarget,
    data = new FormData();
  data.append("image", $("upload").files[0]);
  data.append("title", $("upload-title").value);
  data.append("blank_template", String($("blank").checked));
  busy(form, true);
  status("正在检查导入图片…");
  try {
    const c = await api("/api/import", { method: "POST", body: data });
    $("results").replaceChildren(card(c));
    $("result-count").textContent = "1 张导入候选";
    status("导入完成，尚未收藏。请检查图片后确认收藏。");
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    status(e.message, true);
  } finally {
    busy(form, false);
  }
};
$("edit-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  busy(form, true);
  $("edit-status").textContent = "正在生成预览…";
  try {
    const c = await api(
      `/api/candidates/${encodeURIComponent(editing.id)}/edit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          top_text: $("top").value,
          bottom_text: $("bottom").value,
        }),
      },
    );
    $("edit-preview").replaceChildren(card(c));
    $("edit-status").textContent =
      "新候选已生成，尚未收藏。原始模板显示在上方。";
  } catch (e) {
    $("edit-status").textContent = e.message;
  } finally {
    busy(form, false);
  }
};
$("refresh").onclick = loadLibrary;
api("/api/config")
  .then((c) => {
    $("config").textContent =
      `中文查询助手：${c.planner_configured ? "已配置（认证以请求为准）" : "未配置"} · 联网来源：Imgflip 模板目录 · 扩展网页搜索：${c.web_search_configured ? "已配置（认证以请求为准）" : "未配置"}`;
  })
  .catch(() => {
    $("config").textContent = "服务连接失败，可刷新重试";
  });
loadLibrary();
