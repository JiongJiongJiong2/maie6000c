// The source bitmap stays in the browser. Only the applied File enters a search.
export async function editScreenshot(file, savedRect) {
  const bitmap = await createImageBitmap(file);
  const { width, height } = bitmap;
  const full = { left: 0, top: 0, right: width, bottom: height };
  const dialog = document.getElementById("crop-dialog");
  const stage = document.getElementById("crop-stage");
  const preview = document.getElementById("crop-preview");
  const region = document.getElementById("crop-region");
  const edges = document.getElementById("crop-edges");
  const apply = document.getElementById("crop-apply");
  const size = document.getElementById("crop-size");
  const listeners = new AbortController();
  const options = { signal: listeners.signal };
  let selection;
  let drag;

  function readEdges() {
    const rect = Object.fromEntries(
      Array.from(edges.elements, (field) => [field.name, field.valueAsNumber]),
    );
    const valid =
      Array.from(edges.elements).every((field) => field.validity.valid) &&
      rect.left < rect.right &&
      rect.top < rect.bottom;
    selection = valid ? rect : null;
    apply.disabled = !valid;
    region.hidden = !valid;
    if (!valid) {
      size.textContent =
        "Use edges inside the image with positive width and height.";
      return;
    }
    const boxWidth = rect.right - rect.left;
    const boxHeight = rect.bottom - rect.top;
    Object.assign(region.style, {
      left: `${(100 * rect.left) / width}%`,
      top: `${(100 * rect.top) / height}%`,
      width: `${(100 * boxWidth) / width}%`,
      height: `${(100 * boxHeight) / height}%`,
    });
    size.textContent = `${boxWidth} × ${boxHeight} px selected from ${width} × ${height} px`;
  }

  function setEdges(rect) {
    for (const field of edges.elements) field.value = rect[field.name];
    readEdges();
  }

  function point(event) {
    const bounds = stage.getBoundingClientRect();
    return {
      x: Math.max(
        0,
        Math.min(
          width,
          Math.round(((event.clientX - bounds.left) * width) / bounds.width),
        ),
      ),
      y: Math.max(
        0,
        Math.min(
          height,
          Math.round(((event.clientY - bounds.top) * height) / bounds.height),
        ),
      ),
    };
  }

  function dragTo(event) {
    if (drag?.id !== event.pointerId) return;
    const { x, y } = point(event);
    if (x === drag.x || y === drag.y) return;
    setEdges({
      left: Math.min(drag.x, x),
      top: Math.min(drag.y, y),
      right: Math.max(drag.x, x),
      bottom: Math.max(drag.y, y),
    });
  }

  try {
    const scale = Math.min(1, 900 / Math.max(width, height));
    preview.width = Math.max(1, Math.round(width * scale));
    preview.height = Math.max(1, Math.round(height * scale));
    preview
      .getContext("2d")
      .drawImage(bitmap, 0, 0, preview.width, preview.height);
    stage.style.width = `min(100%, ${(42 * width) / height}vh)`;
    edges.elements.left.max = width - 1;
    edges.elements.top.max = height - 1;
    edges.elements.right.max = width;
    edges.elements.bottom.max = height;
    setEdges(savedRect || full);
    edges.addEventListener("input", readEdges, options);
    // Let pointer events draw the box without starting a native touch gesture
    // that can consume the user's next tap on Apply.
    stage.addEventListener("touchstart", (event) => event.preventDefault(), {
      ...options,
      passive: false,
    });
    stage.addEventListener(
      "pointerdown",
      (event) => {
        if (!event.isPrimary || event.button !== 0) return;
        drag = { ...point(event), id: event.pointerId, previous: selection };
        stage.setPointerCapture(event.pointerId);
      },
      options,
    );
    stage.addEventListener("pointermove", dragTo, options);
    stage.addEventListener(
      "pointerup",
      (event) => {
        if (drag?.id !== event.pointerId) return;
        dragTo(event);
        drag = null;
      },
      options,
    );
    stage.addEventListener(
      "pointercancel",
      (event) => {
        if (drag?.id !== event.pointerId) return;
        setEdges(drag.previous || full);
        drag = null;
      },
      options,
    );
    dialog.returnValue = "";
    dialog.showModal();
    await new Promise((resolve) =>
      dialog.addEventListener("close", resolve, { once: true }),
    );
    if (dialog.returnValue !== "apply" || !selection) return null;
    if (Object.keys(full).every((edge) => selection[edge] === full[edge])) {
      return { file, rect: null };
    }
    const output = document.createElement("canvas");
    output.width = selection.right - selection.left;
    output.height = selection.bottom - selection.top;
    output
      .getContext("2d")
      .drawImage(
        bitmap,
        selection.left,
        selection.top,
        output.width,
        output.height,
        0,
        0,
        output.width,
        output.height,
      );
    const blob = await new Promise((resolve) =>
      output.toBlob(resolve, "image/png"),
    );
    if (!blob || blob.size > 10 * 1024 * 1024) {
      throw new Error(
        "Could not save this crop within 10 MiB. Select a smaller area.",
      );
    }
    return {
      file: new File([blob], "screenshot-crop.png", { type: "image/png" }),
      rect: selection,
    };
  } finally {
    listeners.abort();
    bitmap.close();
    preview.width = preview.height = 1;
  }
}
