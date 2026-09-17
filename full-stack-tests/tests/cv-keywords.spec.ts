// CV keywords are editable from Settings → CV: add, remove, clear, re-extract.
// Runs against the live stack and puts the original keywords back afterwards.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API } from "./helpers";

type Keywords = { titles: string[]; skills: string[] };

async function current(request: APIRequestContext): Promise<Keywords | null> {
  const body = await (await request.get(`${API}/api/cv/keywords`)).json();
  return body.keywords ? JSON.parse(body.keywords) : null;
}

async function restore(request: APIRequestContext, original: Keywords | null) {
  if (original) await request.put(`${API}/api/cv/keywords`, { data: original });
  else await request.delete(`${API}/api/cv/keywords`);
}

async function openCvTab(page: Page) {
  await page.goto("/");
  await expect(page.getByText(/Counts updated/)).toBeVisible();
  await page.getByRole("button", { name: "↻ Refresh data" }).click();
  await expect(page.getByText(/Counts updated/)).toBeVisible();
  await expect(async () => {
    await page.getByRole("radiogroup", { name: "Navigation" }).getByText("Settings").click();
    await page.getByRole("tab", { name: "CV", exact: true }).click({ timeout: 3000 });
    await expect(page.getByRole("button", { name: /Save keywords/ })).toBeVisible({ timeout: 3000 });
  }).toPass();
}

test.describe("CV keywords editor", () => {
  let original: Keywords | null;

  test.beforeEach(async ({ request }) => {
    const info = await (await request.get(`${API}/api/cv/info`)).json();
    test.skip(!info.exists, "needs an uploaded CV");
    original = await current(request);
  });

  test.afterEach(async ({ request }) => {
    await restore(request, original);
  });

  test("add a skill, remove one, save — the API keeps exactly that", async ({ page, request }) => {
    await request.put(`${API}/api/cv/keywords`, {
      data: { titles: ["QA E2E Title"], skills: ["qa-e2e-keep", "qa-e2e-drop"] },
    });
    await openCvTab(page);

    await page.getByRole("button", { name: "qa-e2e-drop, close by backspace" }).locator("svg").click();
    const skills = page.getByRole("combobox", { name: /Skills$/ });
    await skills.click();
    await page.keyboard.type("qa-e2e-added");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /Save keywords/ }).click();

    await expect(page.getByRole("alert").filter({ hasText: "Saved 1 titles and 2 skills" })).toBeVisible();
    expect(await current(request)).toEqual({ titles: ["QA E2E Title"], skills: ["qa-e2e-keep", "qa-e2e-added"] });
  });

  test("clearing every keyword saves empty lists and warns what that means", async ({ page, request }) => {
    await request.put(`${API}/api/cv/keywords`, { data: { titles: ["QA E2E Title"], skills: ["qa-e2e-a"] } });
    await openCvTab(page);

    await page.getByRole("button", { name: "QA E2E Title, close by backspace" }).locator("svg").click();
    await page.getByRole("button", { name: "qa-e2e-a, close by backspace" }).locator("svg").click();
    await page.getByRole("button", { name: /Save keywords/ }).click();

    await expect(page.getByRole("alert").filter({ hasText: "Keywords cleared" })).toBeVisible();
    expect(await current(request)).toEqual({ titles: [], skills: [] });
  });

  test("re-extract asks first; cancel keeps, delete forgets", async ({ page, request }) => {
    await request.put(`${API}/api/cv/keywords`, { data: { titles: ["QA E2E Title"], skills: [] } });
    await openCvTab(page);

    await page.getByRole("button", { name: /Re-extract from CV/ }).click();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(await current(request)).toEqual({ titles: ["QA E2E Title"], skills: [] });

    await page.getByRole("button", { name: /Re-extract from CV/ }).click();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Keywords deleted" })).toBeVisible();
    expect(await current(request)).toBeNull();
  });
});
