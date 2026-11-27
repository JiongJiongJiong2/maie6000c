// Isolated feasibility probe, not a supported import feature.
const nativeType = "net.whatsapp.third-party.sticker-pack";
const button = document.getElementById("try-import");
const status = document.getElementById("status");
const openLink = document.getElementById("open-whatsapp");
const diagnostics = document.getElementById("diagnostics");
const selector = document.getElementById("pack-kind");
const checkButton = document.getElementById("check-written");
const readbackStatus = document.getElementById("readback-status");
const report = {
  experimentVersion: 3,
  time: new Date().toISOString(),
  browser: navigator.userAgent,
  secureContext: window.isSecureContext,
  clipboardWrite: typeof navigator.clipboard?.write === "function",
  clipboardItem: typeof ClipboardItem !== "undefined",
  requestedType: nativeType,
  imported: "尚未验证；需在 WhatsApp 贴纸栏确认",
};
let packText;
let packs;
let expiry;
let writtenAt = 0;
let generation = 0;

function invalidateWrite() {
  generation++;
  writtenAt = 0;
  clearTimeout(expiry);
  openLink.hidden = true;
  checkButton.hidden = true;
  readbackStatus.hidden = true;
  delete report.readback;
  delete report.error;
  delete report.openDelayMs;
}

function selectPack() {
  invalidateWrite();
  const pack = packs[selector.value];
  packText = JSON.stringify(pack);
  report.packKind = selector.value;
  report.identifier = pack.identifier;
  report.packBytes = new Blob([packText]).size;
  report.result = "ready";
  report.phase = "ready";
  status.textContent =
    selector.value === "static"
      ? "A 静态对照包准备好了。先点第一步，再点第二步，观察 WhatsApp 是否仍报错 1000。"
      : "B 动画包准备好了。只有在 WhatsApp 贴纸栏中添加并能发送动画，才算最终目标完成。";
  button.textContent = "第一步：测试网页直接导入";
  button.disabled = false;
  showReport();
}

async function sha256(buffer) {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", buffer)),
  )
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function showReport() {
  diagnostics.textContent = JSON.stringify(report, null, 2);
}
showReport();

async function prepare() {
  try {
    const response = await fetch("./whatsapp-demo-pack.json", {
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok)
      throw new Error(`测试包请求失败：HTTP ${response.status}`);
    const bundle = await response.json();
    if (bundle.experiment_version !== 3)
      throw new Error("测试包版本不匹配，请刷新");
    packs = bundle.packs;
    for (const kind of ["static", "animated"]) {
      const pack = packs?.[kind];
      if (
        pack?.animated_sticker_pack !== (kind === "animated") ||
        pack.stickers?.length !== 3 ||
        !pack.tray_image
      ) {
        throw new Error("测试包内容不完整");
      }
    }
    if (
      !report.secureContext ||
      !report.clipboardWrite ||
      !report.clipboardItem
    ) {
      status.textContent =
        "这个浏览器没有提供本次实验需要的剪贴板写入能力。请使用 iPhone Safari 打开 HTTPS 测试链接。";
      report.result = "api_unavailable";
      button.textContent = "无法开始测试";
    } else {
      selector.disabled = false;
      selectPack();
    }
  } catch (error) {
    status.textContent = "测试包加载失败，请刷新重试。";
    report.result = "pack_load_failed";
    report.error = `${error.name}: ${error.message}`;
    button.textContent = "测试包未准备好";
  }
  showReport();
}

button.addEventListener("click", async () => {
  invalidateWrite();
  button.disabled = true;
  selector.disabled = true;
  report.time = new Date().toISOString();
  report.phase = "create_clipboard_item";
  try {
    // Keep creation and write within the click gesture. No fetch or permission
    // prompt is awaited first, which would invalidate Safari's user activation.
    const item = new ClipboardItem({
      [nativeType]: new Blob([packText], { type: nativeType }),
    });
    report.phase = "write_clipboard";
    await navigator.clipboard.write([item]);
    writtenAt = Date.now();
    report.result = "write_resolved_import_unverified";
    status.textContent =
      "浏览器报告写入完成，但尚未证明 WhatsApp 能读取。请在 60 秒内点击第二步，在 WhatsApp 中检查是否出现添加贴纸包界面。";
    openLink.hidden = false;
    checkButton.hidden = typeof navigator.clipboard.read !== "function";
    expiry = setTimeout(() => {
      openLink.hidden = true;
      checkButton.hidden = true;
      status.textContent =
        "测试写入已超过 60 秒，请重新点击第一步。网页无法设置原生剪贴板的自动过期。";
    }, 60000);
  } catch (error) {
    report.result = "clipboard_rejected";
    report.error = `${error.name}: ${error.message}`;
    status.textContent =
      "网页写入被浏览器拒绝，未进入 WhatsApp 导入步骤。请把下面的测试记录截图发给我；这不是 GIF 下载失败。";
  } finally {
    button.disabled = false;
    selector.disabled = false;
    button.textContent = "重新测试网页直接导入";
    showReport();
  }
});

openLink.addEventListener("click", (event) => {
  if (!writtenAt || Date.now() - writtenAt >= 60000) {
    event.preventDefault();
    invalidateWrite();
    status.textContent = "本次写入已过期，请重新点击第一步。";
    return;
  }
  report.openDelayMs = Date.now() - writtenAt;
  report.result = "open_requested_import_unverified";
  status.textContent =
    "已请求打开 WhatsApp。请确认添加后检查贴纸栏，并尝试发送；网页无法得知导入结果。";
  showReport();
});

checkButton.addEventListener("click", async () => {
  // Explicit user action only. Never log content or read plain text/images;
  // compare only the requested test type, and keep the result in this page.
  if (!writtenAt || Date.now() - writtenAt >= 60000) {
    invalidateWrite();
    status.textContent = "请重新点击第一步，再检查刚写入的数据。";
    return;
  }
  const attempt = generation;
  const expectedText = packText;
  checkButton.disabled = true;
  readbackStatus.hidden = false;
  readbackStatus.textContent =
    "正在检查。若 Safari 提示粘贴权限，请允许本次测试。";
  try {
    const items = await navigator.clipboard.read();
    const item = items.find((entry) => entry.types.includes(nativeType));
    let result;
    if (!item) {
      result = { result: "test_type_not_visible" };
    } else {
      const blob = await item.getType(nativeType);
      if (blob.size > 3 * 1024 * 1024) {
        result = { result: "unexpected_size", bytes: blob.size };
      } else {
        const actualHash = await sha256(await blob.arrayBuffer());
        const expectedHash = await sha256(
          new TextEncoder().encode(expectedText),
        );
        result = {
          result:
            actualHash === expectedHash ? "exact_match" : "different_data",
          bytes: blob.size,
        };
      }
    }
    if (attempt !== generation) return;
    report.readback = result;
    readbackStatus.textContent =
      result.result === "exact_match"
        ? "网页能读回完全相同的测试包。这只证明网页内的数据往返，不证明 WhatsApp 能读取原生格式。"
        : "网页未能读回相同的测试包。请把下面的测试记录截图发给我。";
  } catch (error) {
    if (attempt !== generation) return;
    report.readback = {
      result: "read_failed",
      error: `${error.name}: ${error.message}`,
    };
    readbackStatus.textContent =
      "读取未完成，不能据此判断测试包丢失。请把测试记录截图发给我。";
  } finally {
    checkButton.disabled = false;
    if (attempt === generation) showReport();
  }
});

selector.addEventListener("change", selectPack);
prepare();
