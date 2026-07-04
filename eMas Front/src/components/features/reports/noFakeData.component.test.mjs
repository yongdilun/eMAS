import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  act,
  createViteSsrServer,
  click,
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

test('ReportPreview renders date range objects without raw object text', async () => {
  const { default: ReportPreview } = await server.ssrLoadModule('/src/components/features/reports/ReportPreview.jsx')
  const view = await render(React.createElement(ReportPreview, {
    dateRange: { start: '2026-05-01', end: '2026-05-07' },
    data: {
      data: [
        {
          date: { start: '2026-05-01', end: '2026-05-07' },
          units: 42,
          planned: 50,
        },
      ],
    },
    loading: false,
  }))

  assert.match(view.text(), /2026-05-01 - 2026-05-07/)
  assert.doesNotMatch(view.text(), /\[object Object\]/)

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

test('CalendarPicker highlights continuous ranges and selects full report months', async () => {
  const { default: CalendarPicker } = await server.ssrLoadModule('/src/components/features/reports/CalendarPicker.jsx')

  function CalendarHarness() {
    const [range, setRange] = React.useState({
      startDate: '2026-06-01',
      endDate: '2026-06-30',
    })
    return React.createElement(CalendarPicker, {
      startDate: range.startDate,
      endDate: range.endDate,
      onDateRangeChange: setRange,
    })
  }

  const view = await render(React.createElement(CalendarHarness))

  const customCalendarButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
    button.textContent.includes('Custom calendar'),
  )
  await click(customCalendarButton)

  assert.equal(view.container.querySelector('[data-report-day="2026-06-01"]')?.getAttribute('data-range-start'), 'true')
  assert.equal(view.container.querySelector('[data-report-day="2026-06-15"]')?.getAttribute('data-in-range'), 'true')
  assert.equal(view.container.querySelector('[data-report-day="2026-06-30"]')?.getAttribute('data-range-end'), 'true')

  await changeValue(view.container.querySelector('select[aria-label="Monthly report month"]'), '2026-02')

  await waitFor(() => {
    assert.equal(view.container.querySelector('input[aria-label="Report start date"]').value, '2026-02-01')
    assert.equal(view.container.querySelector('input[aria-label="Report end date"]').value, '2026-02-28')
  })

  await view.unmount()
})

async function changeValue(element, value) {
  assert.ok(element, 'Expected form element')
  await act(async () => {
    element.value = value
    element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }))
    element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }))
  })
}

test('Reports page sends selected date range and dropdown filters to PDF API', async () => {
  const previousFetch = globalThis.fetch
  const previousCreateObjectURL = URL.createObjectURL
  const previousRevokeObjectURL = URL.revokeObjectURL
  const reportRequests = []

  URL.createObjectURL = () => 'blob:report-preview'
  URL.revokeObjectURL = () => {}
  globalThis.fetch = async (url) => {
    const parsed = new URL(String(url))
    if (parsed.pathname.endsWith('/machines')) {
      return Response.json({ success: true, data: [{ machine_id: 'M-PRS-01', machine_name: 'Hydraulic Press 01' }] })
    }
    if (parsed.pathname.endsWith('/jobs')) {
      return Response.json({ success: true, data: [{ job_id: 'JOB-RPT-001', product_id: 'P-005' }] })
    }
    if (parsed.pathname.endsWith('/products')) {
      return Response.json({ success: true, data: [{ product_id: 'P-005', product_name: 'Control Bracket' }] })
    }
    if (parsed.pathname.endsWith('/inventory/materials')) {
      return Response.json({ success: true, data: [{ material_id: 'MAT-008', material_name: 'Steel Sheet' }] })
    }
    if (parsed.pathname.endsWith('/reports/production-output')) {
      reportRequests.push(parsed)
      return new Response(new Blob(['%PDF-1.7'], { type: 'application/pdf' }), {
        status: 200,
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': 'inline; filename="production-output-test.pdf"',
        },
      })
    }
    return Response.json({ success: true, data: [] })
  }

  try {
    const { ToastProvider } = await server.ssrLoadModule('/src/context/ToastContext.jsx')
    const { default: Reports } = await server.ssrLoadModule('/src/pages/Reports.jsx')
    const view = await render(React.createElement(ToastProvider, null, React.createElement(Reports)))

    const filterButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent.includes('Optional filters'),
    )
    await click(filterButton)

    await waitFor(() => {
      assert.ok(view.container.querySelector('select[aria-label="Machine ID"] option[value="M-PRS-01"]'))
    })

    await changeValue(view.container.querySelector('input[aria-label="Report start date"]'), '2026-06-05')
    await changeValue(view.container.querySelector('input[aria-label="Report end date"]'), '2026-07-04')
    await changeValue(view.container.querySelector('select[aria-label="Machine ID"]'), 'M-PRS-01')
    await changeValue(view.container.querySelector('select[aria-label="Job ID"]'), 'JOB-RPT-001')
    await changeValue(view.container.querySelector('select[aria-label="Product ID"]'), 'P-005')

    const generateButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent.includes('Generate PDF'),
    )
    await click(generateButton)

    await waitFor(() => assert.equal(reportRequests.length, 1))
    const query = reportRequests[0].searchParams
    assert.equal(query.get('start'), '2026-06-05T00:00:00Z')
    assert.equal(query.get('end'), '2026-07-04T23:59:59Z')
    assert.equal(query.get('machine_id'), 'M-PRS-01')
    assert.equal(query.get('job_id'), 'JOB-RPT-001')
    assert.equal(query.get('product_id'), 'P-005')

    await waitFor(() => assert.match(view.text(), /Download PDF/))
    await view.unmount()
  } finally {
    globalThis.fetch = previousFetch
    URL.createObjectURL = previousCreateObjectURL
    URL.revokeObjectURL = previousRevokeObjectURL
  }
})
