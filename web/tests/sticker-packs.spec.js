import { expect, test } from "@playwright/test";

test.skip(!process.env.WEB_BACKEND_TEST, "Requires the disposable backend");

test("a public visitor can find, preview and download the official demo pack", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/stickers/");
  await expect(
    page.getByRole("heading", { name: "Sticker pack directory" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View pack: Tin Can Club" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);

  await page.getByRole("button", { name: "Try a sample" }).click();
  const result = page.getByRole("region", { name: "Sticker pack found" });
  await expect(
    result.getByRole("heading", { name: "Pond Post" }),
  ).toBeVisible();
  await expect(result.getByText("Closest to your screenshot")).toBeVisible();

  const play = result.getByRole("button", {
    name: "Play animation for Tea break",
  });
  await play.click();
  await expect(
    result.getByRole("button", { name: "Stop animation for Tea break" }),
  ).toBeVisible();
  await expect(result.locator('img[src$="/tea-break/original"]')).toBeVisible();

  const downloaded = page.waitForEvent("download");
  await result.getByRole("button", { name: "Download sticker pack" }).click();
  expect((await downloaded).suggestedFilename()).toBe("pond-post.zip");

  await page.getByRole("button", { name: "View pack: Tin Can Club" }).click();
  const dialog = page.getByRole("dialog", { name: "Tin Can Club" });
  await expect(dialog.getByText("Published by MemeRetrieve")).toBeVisible();
  await expect(dialog.getByText("Roll out")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "View pack: Tin Can Club" }),
  ).toBeFocused();
});

test("a catalog miss shows a verified link and a clearly labeled candidate", async ({
  page,
}) => {
  const target = "https://store.line.me/stickershop/product/547/en";
  const crop = await page.request.get("/__test__/crop");
  await page.route("**/stickers/search?*", (route) =>
    route.fulfill({
      json: {
        matches: [],
        web: {
          state: "matched",
          links: [
            {
              title: "Hello Kitty",
              url: target,
              channel: "LINE STORE",
              publisher: "SANRIO",
            },
          ],
          leads: [
            {
              title: "Hello Kitty stickers",
              url: "https://sticker.ly/s/ABCD12",
              channel: "Sticker.ly",
              match_basis: "text",
            },
            {
              title: "Hello Kitty community collection",
              url: "https://www.duitang.com/album/?id=48123",
              channel: "Duitang sticker collection",
              match_basis: "series",
            },
          ],
        },
      },
    }),
  );
  await page.goto("/stickers/");
  await page.locator("#screenshot").setInputFiles({
    name: "outside-catalog.png",
    mimeType: "image/png",
    buffer: await crop.body(),
  });
  await page.getByRole("button", { name: "Find pickup links" }).click();
  const result = page.getByRole("region", {
    name: "Verified pickup link found",
  });
  await expect(
    result.getByText("LINE STORE · SANRIO · store.line.me"),
  ).toBeVisible();
  await expect(
    result.getByRole("link", { name: "Open pickup link" }),
  ).toHaveAttribute("href", target);
  await expect(
    result.getByRole("heading", { name: "Candidate pages" }),
  ).toBeVisible();
  await expect(
    result.getByText("Name or text match · artwork unverified"),
  ).toBeVisible();
  await expect(
    result
      .getByRole("article")
      .filter({
        has: page.getByRole("heading", {
          name: "Hello Kitty stickers",
          exact: true,
        }),
      })
      .getByRole("link", { name: "Open candidate page" }),
  ).toHaveAttribute("href", "https://sticker.ly/s/ABCD12");
  await expect(
    result.getByText("Related pack or collection · exact sticker unverified"),
  ).toBeVisible();
});
