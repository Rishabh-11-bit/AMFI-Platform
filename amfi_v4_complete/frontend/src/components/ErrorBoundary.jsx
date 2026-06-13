import { Component } from 'react'

/**
 * Catches unhandled React errors and renders a friendly recovery screen
 * instead of crashing the entire UI to a blank page.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[AMFI] Unhandled React error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div style={{
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        minHeight:      '100vh',
        background:     'var(--bg, #0d1117)',
        color:          'var(--text, #e6edf3)',
        fontFamily:     'monospace',
        padding:        '2rem',
        textAlign:      'center',
      }}>
        <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>⚠️</div>
        <h1 style={{ color: '#f85149', marginBottom: '0.5rem' }}>
          Unexpected Error
        </h1>
        <p style={{ color: '#8b949e', marginBottom: '1.5rem', maxWidth: '500px' }}>
          Something went wrong in the AMFI interface. The error has been logged
          to the browser console.
        </p>

        {this.state.error && (
          <pre style={{
            background:   '#161b22',
            border:       '1px solid #30363d',
            borderRadius: '6px',
            padding:      '1rem',
            fontSize:     '0.75rem',
            color:        '#f85149',
            maxWidth:     '700px',
            overflowX:    'auto',
            marginBottom: '1.5rem',
            textAlign:    'left',
          }}>
            {this.state.error.toString()}
            {this.state.errorInfo?.componentStack}
          </pre>
        )}

        <button
          onClick={this.handleReload}
          style={{
            background:   '#238636',
            color:        '#fff',
            border:       'none',
            borderRadius: '6px',
            padding:      '0.6rem 1.5rem',
            fontSize:     '0.9rem',
            cursor:       'pointer',
            fontFamily:   'monospace',
          }}
        >
          Reload AMFI
        </button>
      </div>
    )
  }
}
