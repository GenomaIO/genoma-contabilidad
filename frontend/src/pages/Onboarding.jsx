/**
 * Onboarding — Elección de modo de catálogo de cuentas
 *
 * Se muestra cuando catalog_mode === null (tenant nuevo).
 * El contador elige su modo y puede migrarlo después.
 *
 * Modos:
 *   NONE     → categorías genéricas, sin partida doble formal
 *   STANDARD → ~70 cuentas NIIF CR precargadas
 *   CUSTOM   → el contador construye su propio catálogo
 */
import { useState } from 'react'
import { useApp } from '../context/AppContext'

const MODES = [
    {
        id: 'NONE',
        icon: '🗂️',
        title: 'Sin Catálogo',
        subtitle: 'Categorías simples',
        description: 'El sistema organiza tus documentos por categorías (Ingresos, Gastos, IVA). No necesitás saber de partida doble.',
        badge: 'Más sencillo',
        badgeColor: '#10b981',
        forWho: 'Ideal para contadores que solo quieren ver sus documentos organizados.'
    },
    {
        id: 'STANDARD',
        icon: '📋',
        title: 'Catálogo Estándar',
        subtitle: '~70 cuentas NIIF CR',
        description: 'Plan de cuentas precargado para Costa Rica (1xxx–5xxx). Podés editar nombres y agregar sub-cuentas.',
        badge: 'Recomendado',
        badgeColor: '#7c3aed',
        forWho: 'Para la mayoría de PYMES y despachos contables.'
    },
    {
        id: 'CUSTOM',
        icon: '📂',
        title: 'Catálogo Propio',
        subtitle: 'Cuentas ilimitadas',
        description: 'Construís tu propio catálogo desde cero o importás un archivo CSV. Profundidad y códigos libres.',
        badge: 'Control total',
        badgeColor: '#f59e0b',
        forWho: 'Para despachos grandes con clientes corporativos o multi-divisa.'
    }
]

export default function Onboarding() {
    const { dispatch } = useApp()
    const [selected, setSelected] = useState(null)
    const [saving, setSaving] = useState(false)
    const [step, setStep] = useState('idle')  // idle | saving-mode | seeding | done
    const [error, setError] = useState(null)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    async function confirm() {
        if (!selected) return
        setSaving(true)
        setStep('saving-mode')
        setError(null)
        try {
            // Paso 1: Guardar el modo elegido
            const res = await fetch(`${apiUrl}/auth/catalog-mode`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ mode: selected })
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || 'Error guardando el modo')
            }

            // Paso 2: Auto-seed del catalogo (solo NONE y STANDARD, no CUSTOM)
            if (selected !== 'CUSTOM') {
                setStep('seeding')
                try {
                    await fetch(`${apiUrl}/catalog/seed`, {
                        method: 'POST',
                        headers: { Authorization: `Bearer ${token}` }
                    })
                    // El seed es idempotente, no critico si falla
                } catch (_) {
                    // Seed fallo pero el modo quedo guardado — no bloquear al usuario
                    console.warn('Seed autocatalogo fallo, el usuario puede reintentarlo desde el catalogo')
                }
            }

            // Paso 3: Actualizar contexto y redirigir al dashboard
            setStep('done')
            setTimeout(() => {
                dispatch({ type: 'SET_CATALOG_MODE', payload: selected })
            }, 700)

        } catch (e) {
            setError(e.message)
            setSaving(false)
            setStep('idle')
        }
    }

    const stepLabel = {
        idle: 'Confirmar →',
        'saving-mode': '⏳ Guardando modo...',
        seeding: '⏳ Cargando catálogo...',
        done: '✅ ¡Listo!',
    }

    return (
        <div style={{
            minHeight: '100vh',
            background: 'var(--bg-primary)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '32px 24px',
            fontFamily: 'Inter, sans-serif'
        }}>

            {/* Header */}
            <div style={{ textAlign: 'center', marginBottom: 48, maxWidth: 560 }}>
                <div style={{ fontSize: '3rem', marginBottom: 16 }}>🧮</div>
                <h1 style={{ fontSize: '1.7rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 10px' }}>
                    ¿Cómo querés trabajar?
                </h1>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: 1.6, margin: 0 }}>
                    Elegí el modo de catálogo de cuentas para esta empresa.
                    Podés cambiarlo después desde Configuración.
                </p>
            </div>

            {/* Cards de modos */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 16,
                width: '100%',
                maxWidth: 760,
                marginBottom: 32
            }}>
                {MODES.map(m => (
                    <button
                        key={m.id}
                        onClick={() => setSelected(m.id)}
                        style={{
                            background: selected === m.id
                                ? 'rgba(124,58,237,0.12)'
                                : 'var(--bg-card)',
                            border: selected === m.id
                                ? '2px solid rgba(124,58,237,0.7)'
                                : '2px solid var(--border-color)',
                            borderRadius: 14,
                            padding: '24px 20px',
                            cursor: 'pointer',
                            textAlign: 'left',
                            transition: 'all 0.2s ease',
                            position: 'relative'
                        }}
                    >
                        {/* Badge */}
                        <span style={{
                            position: 'absolute',
                            top: 12, right: 12,
                            fontSize: '0.72rem',
                            fontWeight: 600,
                            padding: '3px 9px',
                            borderRadius: 20,
                            background: m.badgeColor + '22',
                            color: m.badgeColor,
                        }}>
                            {m.badge}
                        </span>

                        <div style={{ fontSize: '2rem', marginBottom: 10 }}>{m.icon}</div>
                        <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)', marginBottom: 4 }}>
                            {m.title}
                        </div>
                        <div style={{ fontSize: '0.8rem', color: m.badgeColor, fontWeight: 500, marginBottom: 10 }}>
                            {m.subtitle}
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, margin: 0 }}>
                            {m.description}
                        </p>
                        <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 10, fontStyle: 'italic' }}>
                            {m.forWho}
                        </p>

                        {/* Check de selección */}
                        {selected === m.id && (
                            <div style={{
                                position: 'absolute',
                                bottom: 12, right: 14,
                                fontSize: '1.2rem'
                            }}>✅</div>
                        )}
                    </button>
                ))}
            </div>

            {/* Error */}
            {error && (
                <div style={{
                    color: '#ef4444',
                    background: 'rgba(239,68,68,0.1)',
                    border: '1px solid rgba(239,68,68,0.3)',
                    borderRadius: 8,
                    padding: '10px 16px',
                    marginBottom: 16,
                    fontSize: '0.88rem'
                }}>
                    ⚠️ {error}
                </div>
            )}

            {/* Botón confirmar */}
            <button
                onClick={confirm}
                disabled={!selected || saving}
                style={{
                    padding: '14px 40px',
                    background: selected ? '#7c3aed' : 'rgba(124,58,237,0.3)',
                    border: 'none',
                    borderRadius: 10,
                    color: 'white',
                    fontSize: '1rem',
                    fontWeight: 700,
                    cursor: selected && !saving ? 'pointer' : 'not-allowed',
                    transition: 'all 0.2s ease',
                    opacity: selected ? 1 : 0.5
                }}
            >
                {saving ? stepLabel[step] || '...' : 'Confirmar →'}
            </button>

            <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: 20 }}>
                Podés cambiar este modo más adelante desde ⚙️ Configuración
            </p>
        </div>
    )
}
