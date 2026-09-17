// Regression: ISSUE-005, 009, 010 plus the adversarial UI flows from the QA pass
// Found by /qa on 2026-09-17
// Report: .gstack/qa-reports/qa-report-localhost-2026-09-17.md
import { expect, test, type Page } from "@playwright/test";
import { API, createJob, history, removeCompany, uniq } from "./helpers";

// Lists are TTL-cached; rows seeded through the API need the app's own refresh. Refresh
// reruns the app and can drop ?page=, so navigate through the sidebar like a user.
async function gotoFresh(page: Page, name: "Companies" | "Jobs") {
  await page.goto("/");
  // A click sent before the session finishes its first run is dropped.
  await expect(page.getByText(/Counts updated/)).toBeVisible();
  await page.getByRole("button", { name: "↻ Refresh data" }).click();
  await expect(page.getByText(/Counts updated/)).toBeVisible();
  // Jobs and Companies both have a Search box, so wait on something only the target page has.
  const marker = name === "Companies" ? "Add company" : "Add job";
  await expect(async () => {
    await page.getByRole("radiogroup", { name: "Navigation" }).getByText(name, { exact: false }).click();
    await expect(page).toHaveURL(new RegExp(`page=${name}`), { timeout: 3000 });
    await expect(page.getByRole("button", { name: marker })).toBeVisible({ timeout: 3000 });
  }).toPass();
}

async function openAddCompanyByName(page: Page) {
  await page.goto("/?page=Companies");
  await page.getByRole("button", { name: "Add company" }).first().click();
  await page.getByRole("dialog").getByRole("tab", { name: "By name" }).click();
}

async function fillAndSubmit(page: Page, name: string, url = "") {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Company name *", exact: true }).fill(name);
  await dialog.getByRole("textbox", { name: "Company name *", exact: true }).press("Enter");
  if (url) {
    await dialog.getByRole("textbox", { name: "Careers URL", exact: true }).fill(url);
    await dialog.getByRole("textbox", { name: "Careers URL", exact: true }).press("Enter");
  }
  await dialog.getByRole("button", { name: "Add company" }).click();
}

test.describe("Companies: add dialog", () => {
  test("whitespace-only name is refused and nothing is stored", async ({ page, request }) => {
    const before = await (await request.get(`${API}/api/starred`)).json();
    await openAddCompanyByName(page);
    await fillAndSubmit(page, "   ");
    await expect(page.getByRole("alert").filter({ hasText: "Company name is required." }).first()).toBeVisible();
    expect(await (await request.get(`${API}/api/starred`)).json()).toHaveLength(before.length);
  });

  test("javascript: careers URL is refused with a URL hint", async ({ page, request }) => {
    const name = uniq("xss");
    try {
      await openAddCompanyByName(page);
      await fillAndSubmit(page, name, "javascript:alert(document.domain)");
      await expect(page.getByRole("alert").filter({ hasText: "must start with http:// or https://" })).toBeVisible();
      await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
      const check = await request.get(`${API}/api/starred/check`, { params: { company: name } });
      expect(await check.json()).toEqual({ is_starred: false });
    } finally {
      await removeCompany(request, "starred", name);
    }
  });

  test("editing a careers URL to javascript: shows an error instead of Saved", async ({ page, request }) => {
    const name = uniq("edit");
    const created = await request.post(`${API}/api/starred`, {
      data: { company_name: name, careers_url: "https://example.test/careers" },
    });
    expect(created.status()).toBe(201);
    try {
      await gotoFresh(page, "Companies");
      // A rerun still in flight replaces the input and drops what was typed; retry until it sticks.
      await expect(async () => {
        await page.getByRole("textbox", { name: "Search" }).fill(name);
        await page.getByRole("textbox", { name: "Search" }).press("Enter");
        await expect(page.getByText("1 company", { exact: true })).toBeVisible({ timeout: 3000 });
      }).toPass();
      await page.getByRole("button", { name: "⋯" }).first().click();
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      const url = page.getByRole("textbox", { name: "Careers URL", exact: true });
      await url.fill("javascript:alert(1)");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await expect(page.getByRole("alert").filter({ hasText: "Could not save" })).toBeVisible();
      await expect(page.getByText(/^Saved /)).toHaveCount(0);
      const rows: { company_name: string; careers_url: string }[] = await (await request.get(`${API}/api/starred`)).json();
      expect(rows.find((r) => r.company_name === name)?.careers_url).toBe("https://example.test/careers");
    } finally {
      await removeCompany(request, "starred", name);
    }
  });

  test("double-submitting the same company from two tabs stores one row", async ({ browser, request }) => {
    const name = uniq("twotabs");
    const ctx = await browser.newContext();
    const [tabA, tabB] = [await ctx.newPage(), await ctx.newPage()];
    try {
      await openAddCompanyByName(tabA);
      await openAddCompanyByName(tabB);
      await Promise.all([fillAndSubmit(tabA, name), fillAndSubmit(tabB, name)]);
      await expect
        .poll(async () => (await (await request.get(`${API}/api/starred/check`, { params: { company: name } })).json()).is_starred)
        .toBe(true);
      const rows: { company_name: string }[] = await (await request.get(`${API}/api/starred`)).json();
      expect(rows.filter((r) => r.company_name === name)).toHaveLength(1);
    } finally {
      await ctx.close();
      await removeCompany(request, "starred", name);
    }
  });
});

test.describe("Jobs: status changes", () => {
  let jobId: string;
  let title: string;

  test.beforeEach(async ({ request }) => {
    jobId = uniq("job");
    title = `QA E2E ${jobId}`;
    await createJob(request, jobId, title);
  });

  test.afterEach(async ({ request }) => {
    await request.delete(`${API}/api/jobs/filtered/${jobId}`);
  });

  const statusBox = (page: Page) => page.getByRole("combobox", { name: /Status/ }).first();

  async function openJob(page: Page) {
    await gotoFresh(page, "Jobs");
    await expect(async () => {
      await page.getByRole("textbox", { name: "Search" }).fill(title);
      await page.getByRole("textbox", { name: "Search" }).press("Enter");
      await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible({ timeout: 3000 });
    }).toPass();
  }

  async function choose(page: Page, label: string) {
    // A rerun can close the popover between opening it and picking; reopen and retry.
    await expect(async () => {
      await statusBox(page).click();
      await page.getByRole("option", { name: label, exact: true }).click({ timeout: 3000 });
    }).toPass();
    // Streamlit reruns and replaces the widget; the next click must land on the new one.
    await expect(statusBox(page)).toHaveAccessibleName(new RegExp(`Selected ${label}`));
  }

  test("rapid consecutive changes land in order with one history row each", async ({ page, request }) => {
    await openJob(page);
    for (const label of ["Applied", "Interview", "Rejected"]) await choose(page, label);
    await expect.poll(() => history(request, jobId)).toEqual(["new", "applied", "interview", "rejected"]);
  });

  test("refresh right after a change keeps the change", async ({ page, request }) => {
    await openJob(page);
    await choose(page, "Offer");
    await page.reload();
    await expect.poll(() => history(request, jobId)).toEqual(["new", "offer"]);
    await openJob(page);
    await expect(statusBox(page)).toHaveAccessibleName(/Selected Offer/);
  });

  test("same change from a second tab adds no duplicate history", async ({ browser, request }) => {
    const ctx = await browser.newContext();
    const [tabA, tabB] = [await ctx.newPage(), await ctx.newPage()];
    try {
      await openJob(tabA);
      await openJob(tabB);
      await choose(tabA, "Applied");
      await expect.poll(() => history(request, jobId)).toEqual(["new", "applied"]);
      await choose(tabB, "Applied");
      await tabB.waitForTimeout(1500);
      expect(await history(request, jobId)).toEqual(["new", "applied"]);
    } finally {
      await ctx.close();
    }
  });
});
