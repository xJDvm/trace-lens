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

  const service = page.getByLabel("Service");
  await expect(service.locator('option[value="checkout"]')).toBeAttached();
  if ((await service.inputValue()) === "checkout") {
    // Choosing the value that is already selected fires no change event, so leave it first.
    const names = await service
      .locator("option")
      .evaluateAll((options) =>
        options
          .map((option) => option.value)
          .filter((value) => value !== "" && value !== "checkout"),
      );
    const other = names[0];
    if (other === undefined) {
      throw new Error("the service list offers no service besides checkout");
    }
    await service.selectOption(other);
    await expect(page).toHaveURL(
      (url) => url.hash === `#/latency?service=${encodeURIComponent(other)}`,
    );
  }
  await service.selectOption("checkout");
  await expect(page).toHaveURL(/#\/latency\?service=checkout$/);

  const tiles = page.locator(".latency-tile");
  await expect(tiles).toHaveCount(3);
  await expect(tiles.first().locator("dt")).toHaveText("p50");
  await expect(page.locator(".latency-chart")).toBeVisible();
});

test("service map: shows demo services and opens the latency view of one", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Service map" }).click();
  await expect(page).toHaveURL(/#\/map$/);

  const map = page.getByRole("region", { name: "Service map" });
  const nodes = map.getByRole("link");
  await expect(nodes.first()).toBeVisible();
  expect(await nodes.count()).toBeGreaterThanOrEqual(3);

  await nodes.first().click();
  await expect(page).toHaveURL(/#\/latency\?service=[^&]+$/);
  await expect(page.locator(".latency-tile")).toHaveCount(3);
});

test("flame graph: a trace has one frame per span", async ({ page }) => {
  await page.goto("/");

  const rows = page.getByTestId("trace-row");
  await expect(rows.first()).toBeVisible();
  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(TRACE_HASH);

  const waterfallRows = page.getByTestId("waterfall-row");
  await expect(waterfallRows.first()).toBeVisible();
  const spanCount = await waterfallRows.count();

  const flameTab = page.getByRole("button", { name: "Flame graph", exact: true });
  await flameTab.click();
  await expect(flameTab).toHaveAttribute("aria-pressed", "true");

  const frames = page
    .getByRole("group", { name: "Flame graph of the spans" })
    .locator(".flame-frame");
  await expect(frames.first()).toBeVisible();
  await expect(frames).toHaveCount(spanCount);
});
