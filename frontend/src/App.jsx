import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import ClientSelector from './pages/ClientSelector'
import Onboarding from './pages/Onboarding'
import Catalogo from './pages/Catalogo'
import AsientosPendientes from './pages/AsientosPendientes'
import BalanceComprobacion from './pages/BalanceComprobacion'
import CierrePeriodo from './pages/CierrePeriodo'
import CierreAnual from './pages/CierreAnual'
import Apertura from './pages/Apertura'
import Mayor from './pages/Mayor'
import ActivosFijos from './pages/ActivosFijos'
import LibrosDigitales from './pages/LibrosDigitales'
import PerfilFiscal from './pages/PerfilFiscal'
import { useApp } from './context/AppContext'

// Guard de ruta — espera hidratación antes de decidir
function ProtectedRoute({ children }) {
    const { state } = useApp()

    // Mientras el token se está leyendo, no hacer nada (evita redirect prematuro)
    if (state.authLoading) {
        return (
            <div style={{
                minHeight: '100vh', display: 'flex', alignItems: 'center',
                justifyContent: 'center', background: 'var(--bg-primary)',
                color: 'var(--text-secondary)', fontSize: '0.95rem'
            }}>
                ⏳ Cargando sesión...
            </div>
        )
    }

    if (!state.user) {
        window.location.href = 'https://app.genomaio.com/partner_login.html'
        return null
    }
    return children
}

// Placeholder para rutas pendientes
function ComingSoon({ name }) {
    return (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '3rem', marginBottom: 16 }}>🚧</div>
            <h2 style={{ marginBottom: 8, color: 'var(--text-secondary)' }}>{name}</h2>
            <p style={{ fontSize: '0.9rem' }}>Este módulo está en desarrollo · Paso siguiente</p>
        </div>
    )
}

function AppLayout() {
    const { state } = useApp()

    // Prioridad 1: si no hay tenant elegido, ir al selector
    if (!state.tenant) {
        return <Navigate to="/select" replace />
    }

    // Prioridad 2: si el tenant nunca eligió modo de catálogo, ir al onboarding
    // Solo aplica a usuarios standalone (los partner_linked no tienen catálogo propio)
    if (state.catalogMode === null && state.user?.tenant_type === 'standalone') {
        return <Onboarding />
    }

    return (
        <div className={`app-shell${state.sidebarOpen ? ' sidebar-open' : ''}`}>
            <Sidebar />
            <Header />
            <main className="main-content">
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/diario" element={<AsientosPendientes />} />
                    <Route path="/mayor" element={<Mayor />} />
                    <Route path="/balance" element={<BalanceComprobacion />} />
                    <Route path="/auxiliares/activos" element={<ActivosFijos />} />
                    <Route path="/integracion" element={<ComingSoon name="Integración Facturador" />} />
                    <Route path="/asientos" element={<AsientosPendientes />} />
                    <Route path="/catalogo" element={<Catalogo />} />
                    <Route path="/declaraciones" element={<ComingSoon name="Declaraciones Tribu-CR" />} />
                    <Route path="/prorrata" element={<ComingSoon name="Prorrata IVA" />} />
                    <Route path="/reportes" element={<ComingSoon name="Estados Financieros" />} />
                    <Route path="/cierre" element={<CierrePeriodo />} />
                    <Route path="/cierre-anual" element={<CierreAnual />} />
                    <Route path="/libros-digitales" element={<LibrosDigitales />} />
                    <Route path="/config" element={<Navigate to="/config/apertura" replace />} />
                    <Route path="/config/apertura" element={<Apertura />} />
                    <Route path="/config/perfil-fiscal" element={<PerfilFiscal />} />
                    <Route path="*" element={<ComingSoon name="Página no encontrada" />} />
                </Routes>
            </main>
        </div>
    )
}

export default function App() {
    return (
        <BrowserRouter>
            <AppProvider>
                <Routes>
                    {/* Selector de empresas — puerta de entrada al sistema contable */}
                    <Route
                        path="/select"
                        element={
                            <ProtectedRoute>
                                <ClientSelector />
                            </ProtectedRoute>
                        }
                    />
                    {/* Todas las demás rutas pasan por ProtectedRoute + AppLayout */}
                    <Route
                        path="/*"
                        element={
                            <ProtectedRoute>
                                <AppLayout />
                            </ProtectedRoute>
                        }
                    />
                </Routes>
            </AppProvider>
        </BrowserRouter>
    )
}
