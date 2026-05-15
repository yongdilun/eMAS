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
const PredictiveAnalysis = lazy(() => import('./pages/PredictiveAnalysis'))
const Reports = lazy(() => import('./pages/Reports'))
const MachineResources = lazy(() => import('./pages/MachineResources'))
const StorageInventory = lazy(() => import('./pages/StorageInventory'))
const Products = lazy(() => import('./pages/Products'))
const Settings = lazy(() => import('./pages/Settings'))
const AIAssistantModal = lazy(() => import('./components/features/chat/AIAssistantModal'))

const PageLoadingFallback = () => (
    <div className="flex min-h-[240px] items-center justify-center text-sm text-ink-subtle" role="status">
        Loading...
    </div>
)

function App() {
    const [isChatOpen, setIsChatOpen] = useState(false)

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
                                <Route path="/predictive-analysis" element={<PredictiveAnalysis />} />
                                <Route path="/reports" element={<Reports />} />
                                <Route path="/machine-resources" element={<MachineResources />} />
                                <Route path="/storage-inventory" element={<StorageInventory />} />
                                <Route path="/products" element={<Products />} />
                                <Route path="/settings" element={<Settings />} />
                            </Routes>
                        </Suspense>
                    </Layout>
                    <FloatingChatButton onClick={() => setIsChatOpen(true)} />
                    {isChatOpen ? (
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


