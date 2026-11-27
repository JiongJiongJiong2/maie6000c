import { test, expect } from "@playwright/test";

test("real browser clipboard attempt records result without claiming import", async ({
  page,
}, testInfo) => {
  await page.goto("/web/whatsapp-import.html");
  await page.getByRole("button", { name: "第一步：测试网页直接导入" }).click();
  await expect(page.locator("#diagnostics")).toContainText(
    /clipboard_rejected|write_resolved_import_unverified/,
  );
  const report = JSON.parse(await page.locator("#diagnostics").textContent());
  expect(["clipboard_rejected", "write_resolved_import_unverified"]).toContain(
    report.result,
  );
  expect(report.imported).toContain("尚未验证");
  if (report.result === "clipboard_rejected") {
    expect(report.error).toBeTruthy();
    await expect(page.locator("#open-whatsapp")).toBeHidden();
  }
  await testInfo.attach("real-clipboard-result", {
    body: JSON.stringify(report, null, 2),
    contentType: "application/json",
  });
  console.log("Real browser result:", JSON.stringify(report));
});

test("write rejection never exposes WhatsApp launch and permits retry", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        write: async () => {
          throw new DOMException("Test format rejection", "NotAllowedError");
        },
      },
    });
  });
  await page.goto("/web/whatsapp-import.html");
  await page.getByRole("button", { name: "第一步：测试网页直接导入" }).click();
  await expect(page.locator("#diagnostics")).toContainText(
    "NotAllowedError: Test format rejection",
  );
  await expect(page.locator("#open-whatsapp")).toBeHidden();
  await expect(
    page.getByRole("button", { name: "重新测试网页直接导入" }),
  ).toBeEnabled();
});

test("resolved write uses native type and real pack but still requires human confirmation", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        write: async (items) => {
          const type = "net.whatsapp.third-party.sticker-pack";
          const blob = await items[0].getType(type);
          window.probeWritten = {
            types: items[0].types,
            pack: JSON.parse(await blob.text()),
          };
        },
      },
    });
  });
  await page.goto("/web/whatsapp-import.html");
  await expect(page.locator("#pack-kind")).toBeEnabled();
  await page.locator("#pack-kind").selectOption("animated");
  await page.getByRole("button", { name: "第一步：测试网页直接导入" }).click();
  await expect(page.locator("#open-whatsapp")).toBeVisible();
  const result = await page.evaluate(() => window.probeWritten);
  expect(result.types).toEqual(["net.whatsapp.third-party.sticker-pack"]);
  expect(result.pack.animated_sticker_pack).toBe(true);
  expect(result.pack.stickers).toHaveLength(3);
  for (const sticker of result.pack.stickers) {
    const data = Buffer.from(sticker.image_data, "base64");
    expect(data.subarray(8, 12).toString()).toBe("WEBP");
    expect(data.length).toBeLessThanOrEqual(500 * 1024);
  }
  await expect(page.locator("#status")).toContainText(
    "尚未证明 WhatsApp 能读取",
  );
});

test("missing demo pack cannot trigger clipboard or WhatsApp", async ({
  page,
}) => {
  await page.route("**/whatsapp-demo-pack.json", (route) =>
    route.fulfill({ status: 404 }),
  );
  await page.goto("/web/whatsapp-import.html");
  await expect(page.locator("#status")).toContainText("测试包加载失败");
  await expect(page.locator("#try-import")).toBeDisabled();
  await expect(page.locator("#open-whatsapp")).toBeHidden();
});

for (const readResult of ["exact", "missing", "denied"]) {
  test(`static control and explicit readback: ${readResult}`, async ({
    page,
  }) => {
    await page.addInitScript((readResult) => {
      window.readCalls = 0;
      Object.defineProperty(navigator, "clipboard", {
        value: {
          write: async (items) => {
            window.writtenItems = items;
          },
          read: async () => {
            window.readCalls++;
            if (readResult === "denied")
              throw new DOMException("Denied by user", "NotAllowedError");
            if (readResult === "missing")
              return [
                {
                  types: ["text/plain"],
                  getType: () => {
                    throw new Error("Must not read other content");
                  },
                },
              ];
            return window.writtenItems;
          },
        },
      });
    }, readResult);
    await page.goto("/web/whatsapp-import.html");
    await page
      .getByRole("button", { name: "第一步：测试网页直接导入" })
      .click();
    await expect(page.locator("#check-written")).toBeVisible();
    expect(await page.evaluate(() => window.readCalls)).toBe(0);
    const pack = await page.evaluate(async () =>
      JSON.parse(
        await (
          await window.writtenItems[0].getType(
            "net.whatsapp.third-party.sticker-pack",
          )
        ).text(),
      ),
    );
    expect(pack.animated_sticker_pack).toBe(false);
    expect(pack.stickers).toHaveLength(3);
    for (const sticker of pack.stickers) {
      const webp = Buffer.from(sticker.image_data, "base64");
      expect(webp.subarray(0, 4).toString()).toBe("RIFF");
      expect(webp.subarray(8, 12).toString()).toBe("WEBP");
      expect(webp.length).toBeLessThanOrEqual(100 * 1024);
    }
    await page.locator("#check-written").click();
    const expected = {
      exact: "exact_match",
      missing: "test_type_not_visible",
      denied: "read_failed",
    }[readResult];
    await expect(page.locator("#diagnostics")).toContainText(expected);
    expect(await page.evaluate(() => window.readCalls)).toBe(1);
    if (readResult === "exact")
      await expect(page.locator("#readback-status")).toContainText(
        "不证明 WhatsApp 能读取",
      );
  });
}

test("switching packs invalidates the previous write and pending readback", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: {
        write: async () => {},
        read: () =>
          new Promise((resolve) => {
            window.finishRead = resolve;
          }),
      },
    });
  });
  await page.goto("/web/whatsapp-import.html");
  await page.getByRole("button", { name: "第一步：测试网页直接导入" }).click();
  await page.locator("#check-written").click();
  await page.locator("#pack-kind").selectOption("animated");
  await page.evaluate(() => window.finishRead([]));
  await expect(page.locator("#open-whatsapp")).toBeHidden();
  await expect(page.locator("#check-written")).toBeHidden();
  const report = JSON.parse(await page.locator("#diagnostics").textContent());
  expect(report.packKind).toBe("animated");
  expect(report.readback).toBeUndefined();
  expect(report.result).toBe("ready");
});
