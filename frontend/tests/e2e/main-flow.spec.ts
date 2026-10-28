import { expect, test } from "@playwright/test";

// Needs the stack running with ENABLE_MOCK_PROVIDER=true (no real provider is called).
test("login → add keys → send → close tab → reopen → answer is there", async ({ browser }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("rahasia123");
  await page.getByRole("button", { name: "Buat akun" }).click();
  await expect(page).toHaveURL(/\/chat$/);

  // Logout + login again so the login form is covered too.
  await page.getByRole("button", { name: "Keluar" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("rahasia123");
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page).toHaveURL(/\/chat$/);

  // Provider with two accounts: A is rate-limited by the mock, B works.
  await page.goto("/providers");
  await expect(page.getByText("Gunakan hanya key milik sendiri")).toBeVisible();
  await page.getByLabel("Provider").selectOption("mock");
  await page.getByRole("button", { name: "Tambah provider" }).click();
  const card = page.locator("section", { hasText: "Mock (demo/test)" });
  await card.getByLabel("Label").fill("Akun A");
  await card.getByLabel("API key").fill("demo-ratelimit-key-A");
  await card.getByRole("button", { name: "Tambah key" }).click();
  await expect(card.getByTestId("key-row")).toHaveCount(1);
  await card.getByLabel("Label").fill("Akun B");
  await card.getByLabel("API key").fill("demo-good-key-B");
  await card.getByRole("button", { name: "Tambah key" }).click();
  await expect(card.getByTestId("key-row")).toHaveCount(2);
  await expect(page.getByText("demo-ratelimit-key-A")).toHaveCount(0); // never shown in full

  // Send a message, then close the tab right away.
  await page.goto("/chat");
  await page.getByLabel("Pilih model").selectOption("mock/mock-strong");
  await page.getByLabel("Tulis pesan").fill("Jelaskan rotasi API key secara singkat");
  await page.getByRole("button", { name: "Kirim pesan" }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]+$/);
  const chatUrl = page.url();
  await page.close();

  await new Promise((r) => setTimeout(r, 2500)); // worker keeps going with no browser attached

  const reopened = await context.newPage();
  await reopened.goto(chatUrl);
  const answer = reopened.getByRole("article", { name: "Jawaban AI" }).last();
  await expect(answer).toContainText("Jawaban untuk: Jelaskan rotasi API key secara singkat", {
    timeout: 15_000,
  });
  await expect(answer.getByTestId("model-badge")).toHaveText("mock/mock-strong");

  // Key A was rotated out (cooldown), B served the answer.
  await reopened.goto("/providers");
  const rows = reopened.getByTestId("key-row");
  await expect(rows.nth(0)).toContainText("Cooldown");
  await expect(rows.nth(1)).toContainText("Aktif");

  await reopened.goto("/usage");
  await expect(reopened.getByText("Per key (Akun A/B/C)")).toBeVisible();
  await expect(reopened.getByRole("cell", { name: /Akun B/ })).toBeVisible();
  await context.close();
});

test("live streaming reconnects after reload mid-answer", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`e2e-live-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("rahasia123");
  await page.getByRole("button", { name: "Buat akun" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto("/providers");
  await page.getByLabel("Provider").selectOption("mock");
  await page.getByRole("button", { name: "Tambah provider" }).click();
  const card = page.locator("section", { hasText: "Mock (demo/test)" });
  await card.getByLabel("API key").fill("demo-good-key-1");
  await card.getByRole("button", { name: "Tambah key" }).click();
  await expect(card.getByTestId("key-row")).toHaveCount(1);

  await page.goto("/chat");
  const long = "Tulis daftar " + Array.from({ length: 25 }, (_, i) => `poin${i}`).join(" ");
  await page.getByLabel("Tulis pesan").fill(long);
  await page.getByRole("button", { name: "Kirim pesan" }).click();
  await expect(page.getByTestId("live-answer")).toBeVisible({ timeout: 10_000 });
  await page.reload();
  const answer = page.getByRole("article", { name: "Jawaban AI" }).last();
  await expect(answer).toContainText("poin24", { timeout: 20_000 });
});
