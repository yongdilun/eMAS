import assert from 'node:assert/strict'
import test from 'node:test'
import {
  React,
  createViteSsrServer,
  installDom,
  render,
  waitFor,
} from '../test/reactComponentTestUtils.mjs'

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

function countToastMessages(container, message) {
  return Array.from(container.querySelectorAll('p')).filter(
    (node) => node.textContent.trim() === message,
  ).length
}

async function renderToastRun(run) {
  const { ToastProvider, useToast } = await server.ssrLoadModule('/src/context/ToastContext.jsx')

  const ToastRunner = () => {
    const toast = useToast()
    const hasRun = React.useRef(false)

    React.useEffect(() => {
      if (hasRun.current) return
      hasRun.current = true
      run(toast)
    }, [run, toast])

    return null
  }

  return render(
    React.createElement(
      ToastProvider,
      null,
      React.createElement(ToastRunner),
    ),
  )
}

async function renderToastSequence(sequence) {
  const { ToastProvider, useToast } = await server.ssrLoadModule('/src/context/ToastContext.jsx')

  const ToastRunner = () => {
    const toast = useToast()
    const [done, setDone] = React.useState(false)
    const hasRun = React.useRef(false)

    React.useEffect(() => {
      if (hasRun.current) return
      hasRun.current = true
      sequence(toast, () => setDone(true))
    }, [sequence, toast])

    return done ? React.createElement('span', { 'data-test-ready': 'true' }, 'done') : null
  }

  return render(
    React.createElement(
      ToastProvider,
      null,
      React.createElement(ToastRunner),
    ),
  )
}

test('ToastProvider dedupes repeated session-expired errors with the same dedupe key', async () => {
  const message = 'Your session has expired. Please refresh and try again.'
  const view = await renderToastRun((toast) => {
    toast.error(message, { dedupeKey: 'auth-expired', duration: 0 })
    toast.error(message, { dedupeKey: 'auth-expired', duration: 0 })
    toast.error(message, { dedupeKey: 'auth-expired', duration: 0 })
  })

  await waitFor(() => assert.equal(countToastMessages(view.container, message), 1))

  await view.unmount()
})

test('ToastProvider suppresses repeated auth-expired toast after the first visible cycle', async () => {
  const message = 'Your session has expired. Please refresh and try again.'
  const view = await renderToastSequence((toast, done) => {
    const id = toast.error(message, { dedupeKey: 'auth-expired', duration: 0 })
    toast.dismiss(id)
    setTimeout(() => {
      toast.error(message, { dedupeKey: 'auth-expired', duration: 0 })
      done()
    }, 350)
  })

  await waitFor(() => {
    assert.ok(view.container.querySelector('[data-test-ready="true"]'))
    assert.equal(countToastMessages(view.container, message), 0)
  })

  await view.unmount()
})

test('ToastProvider allows different messages or different dedupe keys', async () => {
  const validationError = 'Machine ID is required.'
  const retryLater = 'Could not save settings. Try again later.'
  const view = await renderToastRun((toast) => {
    toast.error(validationError, { dedupeKey: 'settings-save', duration: 0 })
    toast.error(retryLater, { dedupeKey: 'settings-save', duration: 0 })
    toast.error(validationError, { dedupeKey: 'machine-form', duration: 0 })
  })

  await waitFor(() => {
    assert.equal(view.container.querySelectorAll('p').length, 3)
    assert.equal(countToastMessages(view.container, validationError), 2)
    assert.equal(countToastMessages(view.container, retryLater), 1)
  })

  await view.unmount()
})
