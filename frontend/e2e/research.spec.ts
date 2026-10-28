import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const TERMINAL_STATUS = /Completed|Partial answer|Not enough evidence|Failed|Cancelled|Interrupted/;

async function expectNoAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function startFixtureRun(page: Page, question: string, fault?: string) {
  await page.goto("/research");
  await page.getByLabel("Research question").fill(question);
  await expect(page.getByRole("radio", { name: /Live web research/ })).toBeDisabled();
  await expect(page.getByRole("radio", { name: /Fixture demo/ })).toBeChecked();
  if (fault) {
    await page.getByText("Advanced: simulate a failure (testing)").click();
    await page.getByLabel("Inject a provider failure to see how the run degrades.").selectOption({ label: fault });
  }
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page).toHaveURL(/\/research\/run_[0-9a-f]{24}$/);
}

test("landing page states what the product does and passes an accessibility scan @mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Clear answers. Evidence you can inspect." })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Research" })).toBeVisible();
  await expect(nav.getByRole("link", { name: /GitHub/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "View sample" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await expectNoAxeViolations(page);
});

test("the sample opens a cited report whose evidence can be inspected by keyboard", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "View sample" }).click();
  await expect(page).toHaveURL(/\/research\/run_[0-9a-f]{24}$/);
  await expect(page.getByText("Fixture demo · synthetic sources").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Short answer" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();

  const citation = page.getByRole("button", { name: /^Show evidence E\d+$/ }).first();
  await citation.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Passage" })).toBeVisible();
  await expect(dialog.getByText("Synthetic fixture source written for the demo. It is not a real web page.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(citation).toBeFocused();

  await page.getByText("Execution details").click();
  await expect(page.getByText(/Prompt version/)).toBeVisible();
  await expectNoAxeViolations(page);
});

test("a fixture run streams progress to a report that can be exported", async ({ page }) => {
  await startFixtureRun(page, "Which open-source vector databases suit a startup building RAG products?");
  await expect(page.getByRole("heading", { name: "Short answer" })).toBeVisible();
  await expect(page.getByText(TERMINAL_STATUS).first()).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export Markdown" }).click();
  expect((await download).suggestedFilename()).toMatch(/^predixion-run_[0-9a-f]{24}\.md$/);

  await page.getByText("Run progress and activity").click();
  await expect(page.getByText("Research finished.")).toBeAttached();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
});

test("a question that is too short is rejected with an accessible error", async ({ page }) => {
  await page.goto("/research");
  await page.getByLabel("Research question").fill("hi");
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter a question of at least");
  await expect(page.getByLabel("Research question")).toHaveAttribute("aria-invalid", "true");
  await expect(page).toHaveURL(/\/research$/);
  await expectNoAxeViolations(page);
});

test("a search outage ends the run with an explanation instead of an invented answer", async ({ page }) => {
  await startFixtureRun(page, "Which open-source vector databases suit a startup building RAG products?", "Search provider is down");
  await expect(page.getByText(/Failed|Not enough evidence/).first()).toBeVisible();
  await expect(page.getByText(/provider was unavailable|No relevant sources|Not enough evidence to answer|ended without a report/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Key findings" })).toHaveCount(0);
  await expectNoAxeViolations(page);
});

test("an unknown run shows a not-found state", async ({ page }) => {
  await page.goto("/research/run_000000000000000000000000");
  await expect(page.getByRole("heading", { name: "Run not found" })).toBeVisible();
  await expect(page.getByRole("link", { name: "New research" })).toBeVisible();
});
