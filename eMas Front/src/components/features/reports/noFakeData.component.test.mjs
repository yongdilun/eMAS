import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  createViteSsrServer,
  installDom,
  render,
  waitFor,
} from '../../../test/reactComponentTestUtils.mjs'

let server
let cleanupDom

test.before(async () => {
  cleanupDom = installDom()
  server = await createViteSsrServer()
})

test.after(async () => {
  await server?.close()
  cleanupDom?.()
})

test('ReportPreview shows unavailable state instead of demo report rows', async () => {
  const { default: ReportPreview } = await server.ssrLoadModule('/src/components/features/reports/ReportPreview.jsx')
  const view = await render(React.createElement(ReportPreview, { data: null, loading: false }))

  assert.match(view.text(), /No demo report rows are being shown/)
  assert.doesNotMatch(view.text(), /Widget A|Product A|Sample Product/)

  await view.unmount()
})

test('UtilizationChart shows unavailable state instead of demo utilization values', async () => {
  const { default: UtilizationChart } = await server.ssrLoadModule('/src/components/features/machines/UtilizationChart.jsx')
  const view = await render(React.createElement(UtilizationChart, { machines: [], utilizationData: null }))

  assert.match(view.text(), /No demo machine values are being shown/)
  assert.doesNotMatch(view.text(), /CNC Mill 01|Lathe 01|Welding Robot/)

  await view.unmount()
})

test('HighRiskJobsTable shows backend unavailable state instead of seeded risk rows', async () => {
  const { predictiveApi } = await server.ssrLoadModule('/src/services/api.js')
  predictiveApi.highRiskJobs = async () => {
    throw new Error('backend unavailable')
  }
  const { default: HighRiskJobsTable } = await server.ssrLoadModule('/src/components/features/predictive/HighRiskJobsTable.jsx')
  const view = await render(React.createElement(HighRiskJobsTable))

  await waitFor(() => assert.match(view.text(), /No demo risk rows are being shown/))
  assert.doesNotMatch(view.text(), /JOB-SEED|JOB-2403|Bearing wear/)

  await view.unmount()
})
