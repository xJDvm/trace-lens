import { expect, test } from "@playwright/test";

const TRACE_HASH = /#\/trace\/[0-9a-f]{32}$/;

test("browse demo traces: list, filter, open a trace and inspect a span", async ({ page }) => {
  await page.goto("/");

  const filters = page.getByRole("group", { name: "Trace filters" });
  const rows = page.getByTestId("trace-row");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThanOrEqual(1);

  const filtered = page.waitForResponse(
    (response) =>
      response.url().includes("/api/traces") && response.url().includes("service=checkout"),
  );
  await filters.getByLabel("Service").selectOption("checkout");
  await filtered;
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThanOrEqual(1);

  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(TRACE_HASH);

  const waterfallRows = page.getByTestId("waterfall-row");
  await expect(waterfallRows.first()).toBeVisible();
  expect(await waterfallRows.count()).toBeGreaterThanOrEqual(2);
  await expect(waterfallRows.first().locator(".span-service")).toHaveText("web-frontend");

  const details = page.getByTestId("span-details");
  await expect(details).toBeVisible();
  await expect(details.getByRole("heading", { level: 3 })).toHaveText(
    (await waterfallRows.first().locator(".span-name").textContent()) ?? "",
  );

  const lastRow = waterfallRows.last();
  await lastRow.getByRole("button").click();
  await expect(lastRow.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  await expect(details.getByRole("heading", { level: 3 })).toHaveText(
    (await lastRow.locator(".span-name").textContent()) ?? "",
  );
});

test("latency view shows percentile tiles and a histogram for a service", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Latency and histogram" }).click();
  await expect(page).toHaveURL(/#\/latency$/);

  await page.getByLabel("Service").selectOption("checkout");
  await expect(page).toHaveURL(/#\/latency\?service=checkout$/);

  const tiles = page.locator(".latency-tile");
  await expect(tiles).toHaveCount(3);
  await expect(tiles.first().locator("dt")).toHaveText("p50");
  await expect(page.locator(".latency-chart")).toBeVisible();
});
