import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles/index.css'
import logger from './services/logger'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    logger.error('eMAS crashed — unhandled render error', error, {
      componentStack: info?.componentStack,
    })
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#0f1e23', color: '#e5e7eb', fontFamily: 'Inter, sans-serif', padding: '2rem' }}>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#f87171', marginBottom: '1rem' }}>⚠ Application Error</h1>
          <p style={{ color: '#9ca3af', marginBottom: '1.5rem', textAlign: 'center', maxWidth: 500 }}>
            Something went wrong during rendering. Open the browser console (F12) for details.
          </p>
          <pre style={{ background: '#162b32', padding: '1rem', borderRadius: '0.5rem', fontSize: '0.75rem', color: '#f87171', maxWidth: 700, overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {this.state.error?.toString()}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: '1.5rem', padding: '0.5rem 1.5rem', background: '#00C2FF', color: '#0f1e23', border: 'none', borderRadius: '0.5rem', fontWeight: 600, cursor: 'pointer', fontSize: '0.875rem' }}
          >
            Reload Page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
