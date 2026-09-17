// Regression: ISSUE-001, 003, 004, 005, 006, 007 — API accepted bad input and 500'd on races
// Found by /qa on 2026-09-17
// Report: .gstack/qa-reports/qa-report-localhost-2026-09-17.md
import { expect, test } from "@playwright/test";
import { API, createJob, history, removeCompany, uniq } from "./helpers";

test.describe("input validation", () => {
  for (const path of ["blocked", "blocked/toggle", "starred", "starred/toggle"]) {
    for (const name of ["", "   "]) {
      test(`POST /api/${path} rejects blank name ${JSON.stringify(name)}`, async ({ request }) => {
        const res = await request.post(`${API}/api/${path}`, { data: { company_name: name } });
        expect(res.status()).toBe(422);
      });
    }
  }

  for (const url of ["javascript:alert(1)", "file:///etc/passwd", "acme.test/careers"]) {
    test(`starred rejects careers_url ${url}`, async ({ request }) => {
      const name = uniq("url");
      const res = await request.post(`${API}/api/starred`, { data: { company_name: name, careers_url: url } });
      expect(res.status()).toBe(422);
      await removeCompany(request, "starred", name);
    });
  }

  test("schedule refuses non-ASCII digits and keeps the stored time", async ({ request }) => {
    const before = await (await request.get(`${API}/api/settings/schedule`)).json();
    const res = await request.put(`${API}/api/settings/schedule`, { data: { at_time: "١٢:٠٠" } });
    expect(res.status()).toBe(400);
    const after = await (await request.get(`${API}/api/settings/schedule`)).json();
    expect(after.at_time).toBe(before.at_time);
  });

  test("status update on a missing job is 404", async ({ request }) => {
    const res = await request.patch(`${API}/api/jobs/filtered/${uniq("missing")}/status`, {
      data: { user_status: "applied" },
    });
    expect(res.status()).toBe(404);
  });
});

test.describe("concurrent mutations", () => {
  for (const kind of ["blocked", "starred"] as const) {
    test(`10 parallel adds to ${kind}: one 201, the rest 409, one row`, async ({ request }) => {
      const name = uniq(`race-${kind}`);
      try {
        const codes = await Promise.all(
          Array.from({ length: 10 }, () =>
            request.post(`${API}/api/${kind}`, { data: { company_name: name } }).then((r) => r.status()),
          ),
        );
        expect(codes.filter((c) => c === 201)).toHaveLength(1);
        expect(codes.filter((c) => c === 409)).toHaveLength(9);
        const rows: { company_name: string }[] = await (await request.get(`${API}/api/${kind}`)).json();
        expect(rows.filter((r) => r.company_name === name)).toHaveLength(1);
      } finally {
        await removeCompany(request, kind, name);
      }
    });

    test(`10 parallel toggles on ${kind} never 500`, async ({ request }) => {
      const name = uniq(`toggle-${kind}`);
      try {
        const codes = await Promise.all(
          Array.from({ length: 10 }, () =>
            request.post(`${API}/api/${kind}/toggle`, { data: { company_name: name } }).then((r) => r.status()),
          ),
        );
        expect(codes.every((c) => c === 200)).toBe(true);
      } finally {
        await removeCompany(request, kind, name);
      }
    });
  }

  test("10 parallel identical status changes write one history row", async ({ request }) => {
    const id = uniq("job");
    await createJob(request, id, `QA E2E race ${id}`);
    try {
      const codes = await Promise.all(
        Array.from({ length: 10 }, () =>
          request
            .patch(`${API}/api/jobs/filtered/${id}/status`, { data: { user_status: "applied" } })
            .then((r) => r.status()),
        ),
      );
      expect(codes.every((c) => c === 200)).toBe(true);
      expect(await history(request, id)).toEqual(["new", "applied"]);
    } finally {
      await request.delete(`${API}/api/jobs/filtered/${id}`);
    }
  });
});

// Regression: ISSUE-002 — unblocking a variant spelling reported unblocked while still blocked
test("toggling a variant spelling unblocks the company for real", async ({ request }) => {
  const base = uniq("acme");
  try {
    expect((await request.post(`${API}/api/blocked`, { data: { company_name: base } })).status()).toBe(201);
    const toggled = await request.post(`${API}/api/blocked/toggle`, { data: { company_name: `${base}, Inc.` } });
    expect(await toggled.json()).toEqual({ is_blocked: false });
    const check = await request.get(`${API}/api/blocked/check`, { params: { company: `${base}, Inc.` } });
    expect(await check.json()).toEqual({ is_blocked: false });
  } finally {
    await removeCompany(request, "blocked", base);
    await removeCompany(request, "blocked", `${base}, inc.`);
  }
});
