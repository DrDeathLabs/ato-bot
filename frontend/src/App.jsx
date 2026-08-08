import { Component, lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import Login from './pages/Login'
import ProjectList from './pages/ProjectList'
import ProjectDetail from './pages/ProjectDetail'
import AssessmentView from './pages/AssessmentView'
import UserManagement from './pages/UserManagement'
import AuditLog from './pages/security/AuditLog'
import ProjectAuditLog from './pages/ProjectAuditLog'
import SecurityDashboard from './pages/admin/SecurityDashboard'
import PromptManager from './pages/admin/PromptManager'
import IngestionConfig from './pages/admin/IngestionConfig'
import CommonControls from './pages/CommonControls'
import EnterprisePolicies from './pages/EnterprisePolicies'
import EnterpriseProcedures from './pages/EnterpriseProcedures'
import TestDatasetPage from './pages/TestDatasetPage'
import ControlCatalogPage from './pages/ControlCatalogPage'
import SystemKnowledgePage from './pages/SystemKnowledgePage'
import CalibrationPage from './pages/CalibrationPage'
import AssessmentPolicyPage from './pages/AssessmentPolicyPage'
import SspWorkbenchPage from './pages/SspWorkbenchPage'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import { ControlReferenceProvider } from './components/ControlReference'

const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'))
const CatoDashboardPage = lazy(() => import('./pages/CatoDashboardPage'))
const experimentalCatoEnabled = import.meta.env.VITE_ENABLE_EXPERIMENTAL_CATO === 'true'

function ExperimentalCatoRoute({ children }) {
  const { id } = useParams()
  if (!experimentalCatoEnabled) return <Navigate to={`/projects/${id}`} replace />
  return <Suspense fallback={<div className="p-8 text-sm text-gray-500">Loading experimental workspace...</div>}>{children}</Suspense>
}

class ErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div className="p-8">
          <h2 className="text-red-600 font-bold mb-2">Page error</h2>
          <pre className="text-xs bg-red-50 border border-red-200 rounded p-3 text-red-800 whitespace-pre-wrap break-words">
            {this.state.error?.message}{'\n\n'}{this.state.error?.stack}
          </pre>
          <button
            onClick={() => { this.setState({ error: null }); window.history.back() }}
            className="mt-3 text-sm text-blue-600 underline"
          >
            Go back
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  return (
    <ControlReferenceProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/projects" replace />} />
              <Route path="/dashboard" element={<Navigate to="/projects" replace />} />
              <Route path="/projects" element={<ProjectList />} />
              <Route path="/projects/:id" element={<ErrorBoundary><ProjectDetail /></ErrorBoundary>} />
              <Route path="/projects/:id/integrations" element={<ExperimentalCatoRoute><ErrorBoundary><IntegrationsPage /></ErrorBoundary></ExperimentalCatoRoute>} />
              <Route path="/projects/:id/cato-dashboard" element={<ExperimentalCatoRoute><ErrorBoundary><CatoDashboardPage /></ErrorBoundary></ExperimentalCatoRoute>} />
              <Route path="/projects/:id/architecture-tools" element={<ErrorBoundary><SystemKnowledgePage /></ErrorBoundary>} />
              <Route path="/projects/:id/calibration" element={<ErrorBoundary><CalibrationPage /></ErrorBoundary>} />
              <Route path="/assessment-policy" element={<ErrorBoundary><AssessmentPolicyPage /></ErrorBoundary>} />
              <Route path="/projects/:id/ssp-workbench" element={<ErrorBoundary><SspWorkbenchPage /></ErrorBoundary>} />
              <Route path="/projects/:projectId/assessments/:assessmentId" element={<ErrorBoundary><AssessmentView /></ErrorBoundary>} />
              <Route path="/projects/:id/audit-log" element={<ErrorBoundary><ProjectAuditLog /></ErrorBoundary>} />
              <Route path="/projects/:id/test-dataset" element={<ErrorBoundary><TestDatasetPage /></ErrorBoundary>} />
              <Route path="/users" element={<UserManagement />} />
              <Route path="/security/audit-log" element={<AuditLog />} />
              <Route path="/admin/dashboard" element={<SecurityDashboard />} />
              <Route path="/admin/prompts" element={<ErrorBoundary><PromptManager /></ErrorBoundary>} />
              <Route path="/admin/ai-runtime" element={<ErrorBoundary><IngestionConfig /></ErrorBoundary>} />
              <Route path="/admin/ingestion-config" element={<Navigate to="/admin/ai-runtime" replace />} />
              <Route path="/common-controls" element={<ErrorBoundary><CommonControls /></ErrorBoundary>} />
              <Route path="/enterprise-policies" element={<ErrorBoundary><EnterprisePolicies /></ErrorBoundary>} />
              <Route path="/enterprise-procedures" element={<ErrorBoundary><EnterpriseProcedures /></ErrorBoundary>} />
              <Route path="/control-catalog" element={<ErrorBoundary><ControlCatalogPage /></ErrorBoundary>} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </BrowserRouter>
    </ControlReferenceProvider>
  )
}
