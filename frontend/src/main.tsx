import './styles.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import { RequireAuth } from './components/RequireAuth'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import RiskPage from './pages/RiskPage'
import MinesPage from './pages/MinesPage'
import MineDetailPage from './pages/MineDetailPage'
import EnvironmentPage from './pages/EnvironmentPage'
import CompliancePage from './pages/CompliancePage'
import AlertsPage from './pages/AlertsPage'
import IncidentsPage from './pages/IncidentsPage'
import InspectionsPage from './pages/InspectionsPage'
import CorrectiveActionsPage from './pages/CorrectiveActionsPage'
import ZonesPage from './pages/ZonesPage'
import CameraEventsPage from './pages/CameraEventsPage'
import LiveDetectionPage from './pages/LiveDetectionPage'
import UsersPage from './pages/UsersPage'
import AcceptInvitationPage from './pages/AcceptInvitationPage'
import ProfilePage from './pages/ProfilePage'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/accept-invitation/:token" element={<AcceptInvitationPage />} />
          <Route element={<RequireAuth><Layout /></RequireAuth>}>
            <Route path="/" element={<App />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/risk" element={<RiskPage />} />
            <Route path="/mines" element={<MinesPage />} />
            <Route path="/mines/:mineId" element={<MineDetailPage />} />
            <Route path="/environment" element={<EnvironmentPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/inspections" element={<InspectionsPage />} />
            <Route path="/corrective-actions" element={<CorrectiveActionsPage />} />
            <Route path="/zones" element={<ZonesPage />} />
            <Route path="/camera-events" element={<CameraEventsPage />} />
            <Route path="/live-detection" element={<LiveDetectionPage />} />
            <Route path="/users" element={<RequireAuth roles={['admin']}><UsersPage /></RequireAuth>} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
