import { expect, test } from '@playwright/test'

const username = process.env.E2E_USERNAME || 'e2e-admin'
const password = process.env.E2E_PASSWORD || 'e2e-local-password-change-me'

async function login(page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page).toHaveURL(/\/projects$/)
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
}

test('login, feature metadata, project isolation shell, and logout work', async ({ page, request }) => {
  const featureResponse = await request.get('/api/meta/features')
  expect(featureResponse.ok()).toBeTruthy()
  const featurePayload = await featureResponse.json()
  expect(featurePayload.features).toBeTruthy()

  await login(page)
  const projectName = `E2E Release Gate ${Date.now()}`
  await page.getByRole('button', { name: 'New Project' }).click()
  await page.getByLabel('System Name *').fill(projectName)
  await page.getByLabel('Description').fill('Disposable project created by the browser release gate.')
  await page.getByLabel('System Type').fill('Web Application')
  await page.getByLabel('Impact Baseline *').selectOption('moderate')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText(projectName, { exact: true })).toBeVisible()

  const projectCard = page.getByText(projectName, { exact: true }).locator('xpath=ancestor::div[contains(@class,"cursor-pointer")]')
  await projectCard.getByTitle('Delete project').click()
  await expect(page.getByRole('heading', { name: 'Delete Project?' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Project', exact: true }).click()
  await expect(page.getByText(projectName, { exact: true })).toHaveCount(0)

  await page.getByText('Sign Out', { exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
})

test('invalid credentials do not create an authenticated session', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Username').fill('not-a-user')
  await page.getByLabel('Password').fill('invalid-password')
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page.getByText(/invalid|failed/i)).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})
