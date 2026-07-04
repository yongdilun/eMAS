import { Suspense, lazy, useState } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider } from './context/ToastContext'
import Layout from './components/layout/Layout'
import FloatingChatButton from './components/shared/FloatingChatButton'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Jobs = lazy(() => import('./pages/Jobs'))
const Scheduling = lazy(() => import('./pages/Scheduling'))
const ShortageResolution = lazy(() => import('./pages/ShortageResolution'))
const ProductionData = lazy(() => import('./pages/ProductionData'))
const Reports = lazy(() => import('./pages/Reports'))
const MachineResources = lazy(() => import('./pages/MachineResources'))
const StorageInventory = lazy(() => import('./pages/StorageInventory'))
const Products = lazy(() => import('./pages/Products'))
const Settings = lazy(() => import('./pages/Settings'))
const AIAssistantModal = lazy(() => import('./components/features/chat/AIAssistantModal'))
const CHAT_EMERGENCY_DISABLED = ['1', 'true', 'on', 'yes'].includes(
    String(import.meta.env?.VITE_FACTORY_AGENT_EMERGENCY_DISABLED || '').trim().toLowerCase(),
)
const CHAT_EMERGENCY_DISABLED_REASON =
    import.meta.env?.VITE_FACTORY_AGENT_EMERGENCY_DISABLED_REASON ||
    'Factory Agent chat is temporarily disabled by the emergency feature flag. The rest of eMAS remains available.'

const PageLoadingFallback = () => (
    <div className="flex min-h-[240px] items-center justify-center text-sm text-ink-subtle" role="status">
        Loading...
    </div>
)

const ChatDisabledDiagnostic = ({ reason, onDismiss }) => (
    <div
        role="status"
        aria-live="polite"
        className="fixed bottom-20 right-6 z-50 w-[min(24rem,calc(100vw-3rem))] rounded-lg border border-amber-300 bg-surface-1 p-4 text-sm text-ink shadow-2xl"
    >
        <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
                <div className="font-semibold text-ink">AI Assistant disabled</div>
                <p className="mt-1 text-ink-muted">{reason}</p>
            </div>
            <button
                type="button"
                onClick={onDismiss}
                aria-label="Dismiss AI Assistant disabled diagnostic"
                className="rounded-md p-1 text-ink-subtle transition-colors hover:bg-surface-2 hover:text-ink"
            >
                <span className="material-symbols-outlined text-base">close</span>
            </button>
        </div>
    </div>
)

function App() {
    const [isChatOpen, setIsChatOpen] = useState(false)
    const [showChatDisabledDiagnostic, setShowChatDisabledDiagnostic] = useState(false)
    const handleChatButtonClick = () => {
        if (CHAT_EMERGENCY_DISABLED) {
            setIsChatOpen(false)
            setShowChatDisabledDiagnostic(true)
            return
        }
        setShowChatDisabledDiagnostic(false)
        setIsChatOpen(true)
    }

    return (
        <ThemeProvider>
            <ToastProvider>
                <Router>
                    <Layout>
                        <Suspense fallback={<PageLoadingFallback />}>
                            <Routes>
                                <Route path="/" element={<Dashboard />} />
                                <Route path="/jobs" element={<Jobs />} />
                                <Route path="/scheduling" element={<Scheduling />} />
                                <Route path="/scheduling/shortage-resolution" element={<ShortageResolution />} />
                                <Route path="/job-scheduling" element={<Navigate to="/scheduling" replace />} />
                                <Route path="/production-data" element={<ProductionData />} />
                                <Route path="/predictive-analysis" element={<Navigate to="/" replace />} />
                                <Route path="/reports" element={<Reports />} />
                                <Route path="/machine-resources" element={<MachineResources />} />
                                <Route path="/storage-inventory" element={<StorageInventory />} />
                                <Route path="/products" element={<Products />} />
                                <Route path="/settings" element={<Settings />} />
                            </Routes>
                        </Suspense>
                    </Layout>
                    <FloatingChatButton
                        onClick={handleChatButtonClick}
                        disabled={CHAT_EMERGENCY_DISABLED}
                        disabledReason={CHAT_EMERGENCY_DISABLED_REASON}
                    />
                    {showChatDisabledDiagnostic ? (
                        <ChatDisabledDiagnostic
                            reason={CHAT_EMERGENCY_DISABLED_REASON}
                            onDismiss={() => setShowChatDisabledDiagnostic(false)}
                        />
                    ) : null}
                    {isChatOpen && !CHAT_EMERGENCY_DISABLED ? (
                        <Suspense fallback={null}>
                            <AIAssistantModal isOpen={isChatOpen} onClose={() => setIsChatOpen(false)} />
                        </Suspense>
                    ) : null}
                </Router>
            </ToastProvider>
        </ThemeProvider>
    )
}

export default App


