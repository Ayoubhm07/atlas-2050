import { expect, test, type Page } from "@playwright/test";

/** Trois parcours critiques (docs/plan-sprints.md, S6.1), contre l'API locale réelle. */

/** Le formulaire est monté à l'approche de sa section (LazyMount) : on y descend. */
async function openEstimator(page: Page): Promise<void> {
  await page.locator("#estimer").scrollIntoViewIfNeeded();
  await expect(page.getByRole("radio", { name: "Commune" }).first()).toBeAttached();
}

async function chooseCommune(page: Page, label: string, name: string, typed: string): Promise<void> {
  const combo = page.getByRole("combobox", { name: label, exact: true }).last();
  await combo.fill(typed);
  await page.getByRole("option", { name: new RegExp(`^${name}`) }).click();
}

test("recherche, fiche, scénario 2050 : fourchettes réelles, climat en blanc", async ({ page }) => {
  await page.goto("/");
  await openEstimator(page);
  await page.getByRole("radio", { name: "Commune" }).first().check();
  await chooseCommune(page, "Commune", "Bordeaux", "Bord");
  await page.locator("#bien-dpe").selectOption("G");
  await page.getByRole("button", { name: /Estimer et projeter en 2050/ }).click();

  const fiche = page.getByRole("article");
  await expect(fiche.getByRole("heading", { level: 3 })).toContainText("Bordeaux");
  await expect(fiche.getByText(/^En 2050, statu quo, classe G/)).toBeVisible();
  // le prix d'aujourd'hui est au mix DPE moyen : l'écart affiché est l'effet de la classe
  await expect(fiche.getByText(/DPE au mix moyen des ventes/)).toBeVisible();
  await expect(fiche.getByText(/l'effet de la classe G$/)).toBeVisible();
  // climat : deux cartouches « indisponible (DRIAS) », aucun chiffre
  await expect(fiche.locator(".tag-drias")).toHaveCount(2);
  await expect(fiche.getByText("non chiffré")).toHaveCount(2);
  // waterfall refermé sur la prédiction du modèle
  await expect(fiche.getByText("Prédiction du modèle")).toBeVisible();
  // la loi Climat : la classe G est signalée
  await expect(fiche.getByText(/location interdite des logements classés G \(c'est la classe de ce bien\)/)).toBeVisible();
  // aucun tiret cadratin dans le texte visible
  expect(await page.locator("body").innerText()).not.toMatch(/—/);
});

test("filtres de la carte : années réelles puis 2050 en terra incognita", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("img", { name: /hexagones H3/ })).toBeVisible();
  await page.getByRole("button", { name: "Soulever le relief" }).click();
  await expect(page.getByTestId("carte-3d").locator("canvas").first()).toBeVisible();
  const legende = page.locator("#legende-prix");
  await expect(legende).toContainText(/hexagones r7/);
  const toutes = await legende.innerText();

  await page.getByRole("radio", { name: "2024", exact: true }).check();
  await expect(legende).not.toHaveText(toutes);

  await page.getByLabel("Type de bien").selectOption("Appartement");
  await expect(legende).toContainText(/hexagones r7/);

  await page.getByRole("radio", { name: "2050", exact: true }).check();
  await expect(page.getByRole("heading", { name: "2050 n'est pas sur la carte." })).toBeVisible();
  await expect(page.getByText("indisponible (DRIAS)").first()).toBeVisible();
  await page.getByRole("button", { name: "Revenir aux ventes relevées" }).click();
  await expect(page.getByRole("radio", { name: "2021 à 2024" })).toBeChecked();
});

test("comparaison de deux lieux pour le même bien, même échelle", async ({ page }) => {
  await page.goto("/");
  await openEstimator(page);
  await page.getByRole("radio", { name: "Commune" }).first().check();
  await chooseCommune(page, "Commune", "Bordeaux", "Bord");
  await page.getByLabel("Comparer avec un second lieu, pour le même bien").check();
  await chooseCommune(page, "Commune", "Arcachon", "Arcach");
  await page.getByRole("button", { name: "Estimer et comparer" }).click();

  const resume = page.getByRole("region", { name: /Bordeaux et Arcachon, même bien/ });
  await expect(resume).toBeVisible();
  await expect(resume.getByRole("columnheader", { name: "B par rapport à A" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(2);
});

test("sans JavaScript : titre, affiche et méthode lisibles", async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ce que la Gironde vaut");
  await expect(page.getByRole("img", { name: /hexagones H3/ })).toBeVisible();
  await expect(page.getByText(/ventes de logements relevées/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /Ce que le modèle sait/ })).toBeVisible();
  await expect(page.getByText(/demande JavaScript/)).toBeVisible();
  await ctx.close();
});

test("clavier : le relief se soulève au clavier et le focus passe sur la carte", async ({ page }) => {
  await page.goto("/");
  const raise = page.getByRole("button", { name: "Soulever le relief" });
  await raise.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("canvas.maplibregl-canvas")).toBeFocused({ timeout: 30_000 });
});

test("affiche : visible et dimensionnée sans JavaScript, aucun débordement horizontal", async ({ browser }, info) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false, viewport: info.project.use.viewport ?? undefined });
  const page = await ctx.newPage();
  await page.goto("/");
  const box = await page.getByRole("img", { name: /Relevé des prix/ }).boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(200);
  expect(box?.height ?? 0).toBeGreaterThan(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await ctx.close();
});

test("2050 sur téléphone : bandeau compact, les hachures restent visibles", async ({ page }, info) => {
  test.skip(info.project.name !== "telephone", "disposition propre au téléphone");
  await page.goto("/");
  await page.getByRole("button", { name: "Soulever le relief" }).click();
  await expect(page.getByTestId("carte-3d").locator("canvas").first()).toBeVisible();
  await page.getByRole("radio", { name: "2050", exact: true }).check();
  const card = page.getByRole("region", { name: "2050 n'est pas sur la carte." });
  await expect(card).toBeVisible();
  const view = await page.getByRole("region", { name: "Carte du relevé" }).boundingBox();
  const c = await card.boundingBox();
  expect(c && view ? c.height / view.height : 1).toBeLessThanOrEqual(0.5);
  expect(c && view ? c.y : 0).toBeGreaterThan(view?.y ?? 0);
});

test("mouvement réduit : aucune animation CSS ne tourne", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const running = await page.evaluate(
    () => document.getAnimations().filter((a) => a.playState === "running" && Number(a.effect?.getTiming().duration ?? 0) > 1).length,
  );
  expect(running).toBe(0);
  await ctx.close();
});
