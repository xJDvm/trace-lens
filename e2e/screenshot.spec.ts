import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

/** The README images. Resolved from this file, so the repository never stores an absolute path. */
const DOCS_DIR = fileURLToPath(new URL("../docs/", import.meta.url));

// Two device pixels per CSS pixel keep the README images sharp on high-DPI screens.
test.use({ deviceScaleFactor: 2, viewport: { width: 1200, height: 800 } });

test("screenshot: error trace waterfall and trace list for the README", async ({ page }) => {
  await page.goto("/#/");

  const filters = page.getByRole("group", { name: "Trace filters" });
  const rows = page.getByTestId("trace-row");
  const errorsOnly = page.waitForResponse(
    (response) => response.url().includes("/api/traces") && response.url().includes("error=true"),
  );
  await filters.getByLabel("Status").selectOption("true");
  await errorsOnly;
  await expect(rows.first()).toBeVisible();
  await expect(rows.first().locator(".badge-error")).toBeVisible();
  await page.screenshot({ path: `${DOCS_DIR}list.png`, animations: "disabled" });

  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(/#\/trace\/[0-9a-f]{32}$/);

  const waterfall = page.getByTestId("waterfall-row");
  const failedRows = page.locator('[data-testid="waterfall-row"].wf-row-error');
  await expect(waterfall.first()).toBeVisible();
  await expect(failedRows.first()).toBeVisible();

  // Select the last failed span: the failure is shown in the details panel, not only in the bars.
  const failedRow = failedRows.last();
  await failedRow.getByRole("button").click();
  await expect(failedRow.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  const details = page.getByTestId("span-details");
  await expect(details.locator(".text-error").first()).toBeVisible();

  const view = page.getByRole("region", { name: "Trace", exact: true });
  await expect(view).toBeVisible();
  await view.screenshot({ path: `${DOCS_DIR}screenshot.png`, animations: "disabled" });
});
