import { useState } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider } from './context/ToastContext'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Scheduling from './pages/Scheduling'
import ShortageResolution from './pages/ShortageResolution'
import ProductionData from './pages/ProductionData'
import PredictiveAnalysis from './pages/PredictiveAnalysis'
import Reports from './pages/Reports'
import MachineResources from './pages/MachineResources'
import StorageInventory from './pages/StorageInventory'
import Products from './pages/Products'
import Settings from './pages/Settings'
import FloatingChatButton from './components/shared/FloatingChatButton'
import AIAssistantModal from './components/features/chat/AIAssistantModal'

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false)

  return (
    <ThemeProvider>
      <ToastProvider>
      <Router>
        <Layout>
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
        </Layout>
        <FloatingChatButton onClick={() => setIsChatOpen(true)} />
        <AIAssistantModal isOpen={isChatOpen} onClose={() => setIsChatOpen(false)} />
      </Router>
      </ToastProvider>
    </ThemeProvider>
  )
}

export default App


