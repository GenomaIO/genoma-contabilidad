import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import Dashboard from './pages/Dashboard'
import { useApp } from './context/AppContext'

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

    return (
        <div className={`app-shell${state.sidebarOpen ? ' sidebar-open' : ''}`}>
            <Sidebar />
            <Header />
            <main className="main-content">
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/diario" element={<ComingSoon name="Libro Diario" />} />
                    <Route path="/mayor" element={<ComingSoon name="Mayor General" />} />
                    <Route path="/balance" element={<ComingSoon name="Balance de Comprobación" />} />
                    <Route path="/integracion" element={<ComingSoon name="Integración Facturador" />} />
                    <Route path="/asientos" element={<ComingSoon name="Asientos Internos" />} />
                    <Route path="/catalogo" element={<ComingSoon name="Catálogo Contable" />} />
                    <Route path="/declaraciones" element={<ComingSoon name="Declaraciones Tribu-CR" />} />
                    <Route path="/prorrata" element={<ComingSoon name="Prorrata IVA" />} />
                    <Route path="/reportes" element={<ComingSoon name="Estados Financieros" />} />
                    <Route path="/cierre" element={<ComingSoon name="Cierre de Período" />} />
                    <Route path="/config" element={<ComingSoon name="Configuración" />} />
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
                <AppLayout />
            </AppProvider>
        </BrowserRouter>
    )
}
