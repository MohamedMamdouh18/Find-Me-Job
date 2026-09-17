import type { APIRequestContext } from "@playwright/test";

export const API = process.env.API_URL ?? "http://127.0.0.1:8001";

export const uniq = (label: string) => `qa-e2e-${label}-${Date.now()}`;

export async function removeCompany(request: APIRequestContext, kind: "blocked" | "starred", name: string) {
  const rows: { id: number; company_name: string }[] = await (await request.get(`${API}/api/${kind}`)).json();
  for (const row of rows.filter((r) => r.company_name === name.toLowerCase())) {
    await request.delete(`${API}/api/${kind}/${row.id}`);
  }
}

export async function createJob(request: APIRequestContext, id: string, title: string) {
  const res = await request.post(`${API}/api/jobs/filtered`, {
    data: {
      id,
      title,
      company: "QA E2E Co",
      location: "Remote",
      applylink: "https://example.test/apply",
      description: "Synthetic job created by the full stack test suite.",
      website: "LinkedIn",
      score: 99,
      ai_status: "fit",
    },
  });
  if (!res.ok()) throw new Error(`createJob failed: ${res.status()}`);
}

export async function history(request: APIRequestContext, id: string): Promise<string[]> {
  const rows: { status: string }[] = await (await request.get(`${API}/api/jobs/filtered/${id}/history`)).json();
  return rows.map((r) => r.status);
}
