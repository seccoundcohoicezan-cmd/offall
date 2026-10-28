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
  await page.getByRole("button", { name: "Menu akun" }).click();
  await page.getByRole("menuitem", { name: "Keluar" }).click();
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
  await page.getByLabel("Pilih model", { exact: true }).selectOption("mock/mock-strong");
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

// The live site runs on plain HTTP where crypto.randomUUID does not exist.
test("sending works without crypto.randomUUID (non-HTTPS)", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, "randomUUID", { value: undefined, configurable: true });
  });
  await page.goto("/register");
  await page.getByLabel("Email").fill(`e2e-http-${Date.now()}@example.com`);
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
  await page.getByLabel("Tulis pesan").fill("halo tanpa https");
  await page.getByRole("button", { name: "Kirim pesan" }).click();
  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]+$/);
  await expect(page.getByRole("article", { name: "Jawaban AI" }).last()).toContainText("halo tanpa https", {
    timeout: 15_000,
  });
  await expect(page.getByText("randomUUID")).toHaveCount(0);
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("chat, chat list sheet and model sheet on a phone", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Email").fill(`e2e-mobile-${Date.now()}@example.com`);
    await page.getByLabel("Password").fill("rahasia123");
    await page.getByRole("button", { name: "Buat akun" }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole("navigation", { name: "Navigasi bawah" })).toBeVisible();

    await page
      .getByRole("navigation", { name: "Navigasi bawah" })
      .getByRole("link", { name: "Provider" })
      .click();
    await page.getByLabel("Provider").selectOption("mock");
    await page.getByRole("button", { name: "Tambah provider" }).click();
    const card = page.locator("section", { hasText: "Mock (demo/test)" });
    await card.getByLabel("API key").fill("demo-good-key-1");
    await card.getByRole("button", { name: "Tambah key" }).click();
    await expect(card.getByTestId("key-row")).toHaveCount(1);

    await page
      .getByRole("navigation", { name: "Navigasi bawah" })
      .getByRole("link", { name: "Chat" })
      .click();
    await page.getByRole("button", { name: "Pilih model & agent" }).click();
    const sheet = page.getByRole("dialog", { name: "Model & Agent" });
    await sheet.getByText("Mock Fast").click();
    await expect(sheet).toHaveCount(0);
    await page.getByLabel("Tulis pesan").fill("halo dari hp");
    await page.getByRole("button", { name: "Kirim pesan" }).click();
    await expect(page.getByRole("article", { name: "Jawaban AI" }).last()).toContainText("[mock-fast]", {
      timeout: 15_000,
    });

    // no horizontal scrolling on a phone
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);

    await page.getByRole("button", { name: "Daftar chat" }).click();
    await expect(page.getByRole("dialog", { name: "Daftar chat" }).getByText("halo dari hp")).toBeVisible();
  });
});

// Needs an existing admin account (the first user of the instance).
const ADMIN = process.env.E2E_ADMIN_EMAIL;
test("admin creates, disables and re-enables a user", async ({ browser }) => {
  test.skip(!ADMIN, "set E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD");
  const admin = await browser.newPage();
  await admin.goto("/login");
  await admin.getByLabel("Email").fill(ADMIN!);
  await admin.getByLabel("Password").fill(process.env.E2E_ADMIN_PASSWORD ?? "rahasia123");
  await admin.getByRole("button", { name: "Masuk" }).click();
  await expect(admin).toHaveURL(/\/chat$/);
  await admin.getByRole("button", { name: "Menu akun" }).click();
  await admin.getByRole("menuitem", { name: "Manajemen user" }).click();
  await expect(admin.getByRole("heading", { name: "Manajemen User" })).toBeVisible();

  const email = `staff-${Date.now()}@example.com`;
  await admin.getByLabel("Email").fill(email);
  await admin.getByLabel("Password awal").fill("staffpass1");
  await admin.getByRole("button", { name: "Buat akun" }).click();
  const row = admin.getByTestId("user-row").filter({ hasText: email });
  await expect(row).toBeVisible();

  const staff = await browser.newPage();
  await staff.goto("/login");
  await staff.getByLabel("Email").fill(email);
  await staff.getByLabel("Password").fill("staffpass1");
  await staff.getByRole("button", { name: "Masuk" }).click();
  await expect(staff).toHaveURL(/\/chat$/);
  await staff.goto("/admin");
  await expect(staff.getByText("Khusus admin")).toBeVisible();

  await row.getByRole("switch", { name: `Aktifkan ${email}` }).click();
  await expect(row.getByText("Nonaktif")).toBeVisible();
  await staff.reload();
  await expect(staff).toHaveURL(/\/login$/, { timeout: 10_000 });
  await staff.getByLabel("Email").fill(email);
  await staff.getByLabel("Password").fill("staffpass1");
  await staff.getByRole("button", { name: "Masuk" }).click();
  await expect(staff.getByRole("alert").filter({ hasText: "dinonaktifkan" })).toBeVisible();

  await row.getByRole("switch", { name: `Aktifkan ${email}` }).click();
  await expect(row.getByText("Nonaktif")).toHaveCount(0);
});

test("memory: teach a fact, answer uses it, history search finds old chat", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`e2e-mem-${Date.now()}@example.com`);
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

  await page.goto("/memory");
  await page
    .getByLabel("Ajari AI sesuatu tentangmu")
    .fill("Pengguna sedang membangun aplikasi kasir berbasis Laravel.");
  await page.getByRole("button", { name: "Simpan" }).click();
  await expect(page.getByTestId("memory-row")).toHaveCount(1);

  await page.goto("/chat");
  await page.getByLabel("Tulis pesan").fill("Saran fitur untuk aplikasi kasir Laravel saya?");
  await page.getByRole("button", { name: "Kirim pesan" }).click();
  const answer = page.getByRole("article", { name: "Jawaban AI" }).last();
  await expect(answer).toContainText("kasir", { timeout: 15_000 });
  await expect(answer).toContainText("1 memori");

  await page.goto("/memory");
  await page.getByRole("tab", { name: "Cari riwayat" }).click();
  await page.getByLabel("Cari di semua percakapan").fill("kasir");
  await page.getByRole("button", { name: "Cari" }).click();
  await expect(page.getByTestId("history-hit").first()).toContainText("kasir");
  await page.getByRole("tab", { name: "Log aktivitas" }).click();
  await expect(page.getByText("memory.create")).toBeVisible();
});

// Needs an OpenAI-compatible 9Router (or stand-in) reachable from the API server.
const ROUTER = process.env.E2E_9ROUTER_URL;
test("9Router: add endpoint, sync models, chat through it", async ({ page }) => {
  test.skip(!ROUTER, "set E2E_9ROUTER_URL");
  await page.goto("/register");
  await page.getByLabel("Email").fill(`e2e-9r-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("rahasia123");
  await page.getByRole("button", { name: "Buat akun" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto("/providers");
  await page.getByLabel("Provider").selectOption("9router");
  await page.getByLabel(/Base URL/).fill(ROUTER!);
  await page.getByRole("button", { name: "Tambah provider" }).click();
  const card = page.locator("section", { hasText: "9Router (OpenAI-compatible)" });
  await expect(card.getByTestId("key-row")).toHaveCount(1);
  await card.getByRole("button", { name: /Sinkron/ }).click();
  await expect(card.getByText("cc/claude-sonnet-4.5")).toBeVisible();

  await page.goto("/chat");
  await page.getByLabel("Pilih model", { exact: true }).selectOption("9router/cc/claude-sonnet-4.5");
  await page.getByLabel("Tulis pesan").fill("halo lewat 9router");
  await page.getByRole("button", { name: "Kirim pesan" }).click();
  const answer = page.getByRole("article", { name: "Jawaban AI" }).last();
  await expect(answer).toContainText("[9router:cc/claude-sonnet-4.5]", { timeout: 20_000 });
  await expect(answer.getByTestId("model-badge")).toHaveText("9router/cc/claude-sonnet-4.5");
});
