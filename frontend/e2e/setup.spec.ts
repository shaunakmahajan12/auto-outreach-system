import { test, expect } from '@playwright/test';

test('setup checklist follows provider, import and experience readiness', async ({ page }) => {
  let imported = false;
  await page.route('**/api/settings', async route => {
    const response = await route.fetch();
    await route.fulfill({
      json: {
        ...(await response.json()),
        demo: false,
        onboarding_required: !imported,
        tsenta_connected: true,
        search_configured: false,
        approved_experience_count: 0,
        ollama: {
          available: false,
          model: 'fictional-model',
          message: 'Fictional unavailable model',
        },
      },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const setup = page.getByRole('region', { name: 'Workspace setup' });
  await expect(setup).toContainText('Import your complete initial history');
  await expect(setup.getByRole('button', { name: 'Add approved experience' })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  imported = true;
  await setup.getByRole('button', { name: 'Refresh setup status' }).click();
  await expect(setup).toContainText('Initial history imported.');
  await expect(setup.getByRole('button', { name: 'Add approved experience' })).toBeEnabled();
  await setup.getByRole('button', { name: 'Add approved experience' }).click();
  await expect(page.getByRole('button', { name: 'Add experience', exact: true })).toBeVisible();
});
