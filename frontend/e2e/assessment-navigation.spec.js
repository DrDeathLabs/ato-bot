import { expect, test } from '@playwright/test'

const username = process.env.E2E_USERNAME || 'e2e-admin'
const password = process.env.E2E_PASSWORD || 'e2e-local-password-change-me'
const projectId = process.env.E2E_PROJECT_ID
const assessmentId = process.env.E2E_ASSESSMENT_ID

test('assessment workspace navigation clears stale control context', async ({ page }) => {
  test.skip(!projectId || !assessmentId, 'Requires an existing governed assessment')

  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page).toHaveURL(/\/projects$/)

  await page.goto(`/projects/${projectId}/assessments/${assessmentId}?tab=findings&findingsView=flat&control=AC-1`)
  await expect(page.getByText('Control review workspace', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close control review drawer' }).click()
  await expect(page.getByRole('button', { name: 'Close control review drawer' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Outputs', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/assessments/${assessmentId}\\?tab=outputs`))
  expect(new URL(page.url()).searchParams.has('control')).toBeFalsy()
  await expect(page.getByText('Assessment finalization', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  expect(new URL(page.url()).searchParams.has('control')).toBeFalsy()
})
