/**
 * ClientSelector — Selector de empresas / despacho contable
 *
 * Puerta de entrada al sistema contable para ambos tipos de usuario:
 *   - partner_linked : ve sus clientes importados del Facturador
 *   - standalone     : ve sus empresas propias + puede crear nuevas
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export default function ClientSelector() {
    const { state, dispatch } = useApp()
    const navigate = useNavigate()

    const [clients, setClients] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [showNewForm, setShowNewForm] = useState(false)
    const [newForm, setNewForm] = useState({ nombre: '', cedula: '' })
    const [creating, setCreating] = useState(false)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const isPartner = state.user?.tenant_type === 'partner_linked'

    // Cargar lista de empresas
    useEffect(() => {
        if (!token) return
        fetch(`${apiUrl}/auth/clients`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.json())
            .then(data => {
                setClients(data.clients || [])
                setLoading(false)
            })
            .catch(() => {
                setError('No se pudieron cargar las empresas')
                setLoading(false)
            })
    }, [])

    // Al seleccionar una empresa — guarda contexto completo para documentos fiscales
    function selectClient(client) {
        dispatch({
            type: 'SET_TENANT',
            payload: {
                tenant_id: client.tenant_id,
                emisor_id: client.emisor_id || null,  // puerta a FE/TE/recibidos
                nombre: client.nombre,
                estado: client.estado || client.status || 'ACTIVO',
                origen: client.origen || 'contabilidad',
                numero: client.numero || null,
            }
        })
        navigate('/')
    }

    // Crear nueva empresa (solo standalone)
    async function createCompany(e) {
        e.preventDefault()
        setCreating(true)
        try {
            const res = await fetch(`${apiUrl}/auth/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({
                    nombre_empresa: newForm.nombre,
                    cedula: newForm.cedula,
                    email: state.user?.email || '',
                    password: 'temp-internal',   // backend no lo usa en este contexto
                    nombre_usuario: state.user?.nombre || 'Admin',
                    tenant_type: 'standalone'
                })
            })
            if (res.ok) {
                const data = await res.json()
                setClients(prev => [...prev, {
                    tenant_id: data.tenant_id,
                    nombre: newForm.nombre,
                    cedula: newForm.cedula,
                    tenant_type: 'standalone',
                    status: 'trial'
                }])
                setShowNewForm(false)
                setNewForm({ nombre: '', cedula: '' })
            } else {
                const err = await res.json()
                setError(err.detail || 'Error al crear la empresa')
            }
        } catch {
            setError('Error de conexión al crear la empresa')
        } finally {
            setCreating(false)
        }
    }

    function logout() {
        dispatch({ type: 'LOGOUT' })
        window.location.href = 'https://app.genomaio.com/partner_login.html'
    }

    return (
        <div style={{
            minHeight: '100vh',
            background: 'var(--bg-primary)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            fontFamily: 'Inter, sans-serif',
            position: 'relative',
            overflow: 'hidden',
        }}>
            {/* Watermark Pacioli — sello de agua, apenas perceptible */}
            <img
                src="/pacioli.png"
                alt=""
                aria-hidden="true"
                style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    height: '90%',
                    width: 'auto',
                    opacity: 0.08,
                    filter: 'grayscale(100%) contrast(0.9)',
                    mixBlendMode: 'luminosity',
                    pointerEvents: 'none',
                    userSelect: 'none',
                    zIndex: 0,
                }}
            />
            {/* Contenido sobre el watermark — z-index 1 */}
            <div style={{ position: 'relative', zIndex: 1, width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                {/* Header */}
                <div style={{ textAlign: 'center', marginBottom: 40 }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🧮</div>
                    <h1 style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                        Sistema de Contabilidad
                    </h1>
                    <p style={{ color: 'var(--text-secondary)', marginTop: 6, fontSize: '0.9rem' }}>
                        {isPartner
                            ? `Hola ${state.user?.nombre} — Seleccioná el cliente con quien vas a trabajar`
                            : `Hola ${state.user?.nombre} — Seleccioná tu empresa o creá una nueva`
                        }
                    </p>
                </div>

                {/* Contenedor principal */}
                <div style={{ width: '100%', maxWidth: 680 }}>

                    {/* Loading */}
                    {loading && (
                        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px 0' }}>
                            ⏳ Cargando empresas...
                        </div>
                    )}

                    {/* Error */}
                    {error && (
                        <div style={{
                            background: 'rgba(239,68,68,0.1)',
                            border: '1px solid rgba(239,68,68,0.3)',
                            borderRadius: 10,
                            padding: '14px 18px',
                            color: '#ef4444',
                            marginBottom: 20,
                            fontSize: '0.9rem'
                        }}>
                            ⚠️ {error}
                        </div>
                    )}

                    {/* Lista de empresas */}
                    {!loading && clients.length > 0 && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
                            {clients.map(c => (
                                <button
                                    key={c.tenant_id}
                                    onClick={() => selectClient(c)}
                                    style={{
                                        background: 'var(--bg-card)',
                                        border: '1px solid var(--border-color)',
                                        borderRadius: 12,
                                        padding: '18px 22px',
                                        cursor: 'pointer',
                                        textAlign: 'left',
                                        color: 'var(--text-primary)',
                                        transition: 'all 0.2s ease',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        width: '100%'
                                    }}
                                    onMouseEnter={e => {
                                        e.currentTarget.style.borderColor = 'rgba(124,58,237,0.5)'
                                        e.currentTarget.style.background = 'rgba(124,58,237,0.08)'
                                    }}
                                    onMouseLeave={e => {
                                        e.currentTarget.style.borderColor = 'var(--border-color)'
                                        e.currentTarget.style.background = 'var(--bg-card)'
                                    }}
                                >
                                    <div>
                                        <div style={{ fontWeight: 600, fontSize: '1rem', marginBottom: 4 }}>
                                            🏢 {c.nombre}
                                        </div>
                                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                            {c.origen === 'facturador'
                                                ? `Cliente #${c.numero || '?'} · Facturador`
                                                : `Cédula: ${c.cedula || '—'} · Independiente`
                                            }
                                        </div>
                                    </div>
                                    <span style={{
                                        fontSize: '0.78rem',
                                        padding: '4px 10px',
                                        borderRadius: 20,
                                        background: (c.estado || c.status) === 'ACTIVO' || (c.estado || c.status) === 'active'
                                            ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                                        color: (c.estado || c.status) === 'ACTIVO' || (c.estado || c.status) === 'active'
                                            ? '#10b981' : '#f59e0b',
                                        fontWeight: 500
                                    }}>
                                        {(c.estado || c.status) === 'ACTIVO' || (c.estado || c.status) === 'active' ? 'Activo' : 'Trial'}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}

                    {/* Estado vacío para partners */}
                    {!loading && clients.length === 0 && isPartner && (
                        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '60px 0' }}>
                            <div style={{ fontSize: '3rem', marginBottom: 16 }}>👥</div>
                            <p>Aún no tenés clientes vinculados al sistema contable.</p>
                            <p style={{ fontSize: '0.85rem', marginTop: 8, opacity: 0.7 }}>
                                Cuando tus clientes activen la contabilidad aparecerán aquí.
                            </p>
                        </div>
                    )}

                    {/* Botón + Agregar empresa (solo standalone) */}
                    {!loading && !isPartner && !showNewForm && (
                        <button
                            onClick={() => setShowNewForm(true)}
                            style={{
                                width: '100%',
                                padding: '16px',
                                background: 'rgba(16,185,129,0.08)',
                                border: '1px dashed rgba(16,185,129,0.4)',
                                borderRadius: 12,
                                color: '#10b981',
                                fontSize: '0.95rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                                transition: 'all 0.2s'
                            }}
                        >
                            + Agregar empresa
                        </button>
                    )}

                    {/* Formulario nueva empresa */}
                    {showNewForm && (
                        <form onSubmit={createCompany} style={{
                            background: 'var(--bg-card)',
                            border: '1px solid rgba(16,185,129,0.3)',
                            borderRadius: 12,
                            padding: '24px'
                        }}>
                            <h3 style={{ margin: '0 0 18px', fontSize: '1rem', color: '#10b981' }}>
                                Nueva empresa
                            </h3>
                            <div style={{ marginBottom: 14 }}>
                                <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 6 }}>
                                    Nombre de la empresa
                                </label>
                                <input
                                    required
                                    value={newForm.nombre}
                                    onChange={e => setNewForm(p => ({ ...p, nombre: e.target.value }))}
                                    placeholder="Ej: Soluciones Tech S.A."
                                    style={{
                                        width: '100%', padding: '10px 14px', borderRadius: 8,
                                        background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-color)',
                                        color: 'var(--text-primary)', fontSize: '0.9rem', boxSizing: 'border-box'
                                    }}
                                />
                            </div>
                            <div style={{ marginBottom: 18 }}>
                                <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 6 }}>
                                    Cédula jurídica / física
                                </label>
                                <input
                                    required
                                    value={newForm.cedula}
                                    onChange={e => setNewForm(p => ({ ...p, cedula: e.target.value }))}
                                    placeholder="Ej: 3101234567"
                                    style={{
                                        width: '100%', padding: '10px 14px', borderRadius: 8,
                                        background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-color)',
                                        color: 'var(--text-primary)', fontSize: '0.9rem', boxSizing: 'border-box'
                                    }}
                                />
                            </div>
                            <div style={{ display: 'flex', gap: 10 }}>
                                <button type="submit" disabled={creating} style={{
                                    flex: 1, padding: '10px', background: '#10b981',
                                    border: 'none', borderRadius: 8, color: 'white',
                                    fontWeight: 600, cursor: creating ? 'not-allowed' : 'pointer', fontSize: '0.9rem'
                                }}>
                                    {creating ? 'Creando...' : 'Crear empresa'}
                                </button>
                                <button type="button" onClick={() => setShowNewForm(false)} style={{
                                    padding: '10px 18px', background: 'transparent',
                                    border: '1px solid var(--border-color)', borderRadius: 8,
                                    color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.9rem'
                                }}>
                                    Cancelar
                                </button>
                            </div>
                        </form>
                    )}

                    {/* Footer */}
                    <div style={{ textAlign: 'center', marginTop: 32 }}>
                        <button onClick={logout} style={{
                            background: 'transparent', border: 'none',
                            color: 'var(--text-secondary)', cursor: 'pointer',
                            fontSize: '0.85rem', textDecoration: 'underline'
                        }}>
                            Cerrar sesión
                        </button>
                    </div>
                </div>
            </div>{/* /wrapper zIndex:1 */}
        </div>
    )
}
