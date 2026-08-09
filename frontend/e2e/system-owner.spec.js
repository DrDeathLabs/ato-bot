import { expect, test } from '@playwright/test'

const username = process.env.E2E_USERNAME || 'e2e-admin'
const password = process.env.E2E_PASSWORD || 'e2e-local-password-change-me'

async function login(page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page).toHaveURL(/\/projects$/)
}

test('assigns and displays the FISMA system owner for a project', async ({ page }) => {
  await login(page)

  const stamp = Date.now()
  const ownerName = `e2e-owner-${stamp}`
  const accessToken = await page.evaluate(() => sessionStorage.getItem('access_token'))
  const ownerResponse = await page.request.post('/api/users', {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: {
      username: ownerName,
      email: `${ownerName}@example.com`,
      password: `E2E-Owner-${stamp}!pass`,
      role: 'system_owner',
    },
  })
  expect(ownerResponse.ok()).toBeTruthy()
  const owner = await ownerResponse.json()
  const projectName = `E2E System Owner ${stamp}`

  try {
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
    await page.getByRole('button', { name: 'New Project' }).click()
    const ownerSelect = page.getByLabel('FISMA System Owner')
    const ownerOption = ownerSelect.locator(`option[value="${owner.id}"]`)
    await expect(ownerOption).toHaveCount(1)

    await page.getByLabel('System Name *').fill(projectName)
    await page.getByLabel('Description').fill('Disposable system-owner assignment browser test.')
    await page.getByLabel('System Type').fill('Web Application')
    await page.getByLabel('Impact Baseline *').selectOption('moderate')
    await ownerSelect.selectOption(String(owner.id))
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(page.getByText(projectName, { exact: true })).toBeVisible()
    await expect(page.getByText(`FISMA System Owner: ${ownerName}`, { exact: true })).toBeVisible()

    await page.getByText(projectName, { exact: true }).click()
    await expect(page.getByText('FISMA accountability', { exact: true })).toBeVisible()
    await expect(page.locator('#project-system-owner')).toHaveValue(String(owner.id))
    await expect(page.getByText(`${ownerName} is assigned as the FISMA System Owner.`, { exact: true })).toBeVisible()

    await page.getByRole('link', { name: 'Projects', exact: true }).click()
    const projectCard = page.getByText(projectName, { exact: true }).locator('xpath=ancestor::div[contains(@class,"cursor-pointer")]')
    await projectCard.getByTitle('Delete project').click()
    await page.getByRole('button', { name: 'Delete Project', exact: true }).click()
    await expect(page.getByText(projectName, { exact: true })).toHaveCount(0)
  } finally {
    await page.request.patch(`/api/users/${owner.id}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { is_active: false },
    })
  }
})
