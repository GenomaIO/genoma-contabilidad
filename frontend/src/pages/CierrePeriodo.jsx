/**
 * CierrePeriodo.jsx — Cierre Contable de Período
 *
 * Genera un asiento DRAFT que transfiere saldos de Ingresos/Gastos
 * a la cuenta de Utilidad (3303) o Pérdida (3302) del ejercicio.
 *
 * Flujo:
 * 1. El contador elige el período a cerrar
 * 2. El sistema verifica que no haya asientos DRAFT pendientes
 * 3. Si está OK, genera el asiento de cierre en DRAFT (requiere aprobación)
 * 4. El contador aprueba el asiento desde el Libro Diario (/diario)
 *
 * Solo admin/contador pueden ejecutar el cierre.
 */
import { useState, useEffect } from 'react'
import { useApp } from '../context/AppContext'

const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function getPreviousPeriod() {
    const d = new Date()
    // El cierre es del período anterior al actual
    d.setMonth(d.getMonth() - 1)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function CierrePeriodo() {
    const { state } = useApp()
    const [period, setPeriod] = useState(getPreviousPeriod())
    const [checking, setChecking] = useState(false)
    const [closing, setClosing] = useState(false)
    const [draftCount, setDraftCount] = useState(null)  // null=sin verificar
    const [result, setResult] = useState(null)
    const [error, setError] = useState(null)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const canClose = role === 'admin' || role === 'contador'

    // Verificar DRAFTs pendientes cada vez que cambia el período
    useEffect(() => {
        checkDrafts()
        setResult(null)
    }, [period])

    async function checkDrafts() {
        setChecking(true); setError(null); setDraftCount(null)
        try {
            const res = await fetch(`${apiUrl}/ledger/entries?period=${period}&status=DRAFT`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) throw new Error('Error al verificar asientos pendientes')
            const entries = await res.json()
            setDraftCount(entries.length)
        } catch (e) { setError(e.message) }
        finally { setChecking(false) }
    }

    async function handleClose() {
        if (!canClose) return
        if (draftCount > 0) {
            alert(`❌ No se puede cerrar: hay ${draftCount} asiento(s) DRAFT pendiente(s). Apróbalos o anúlalos primero.`)
            return
        }
        setClosing(true); setError(null); setResult(null)
        try {
            const res = await fetch(`${apiUrl}/ledger/close-period`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ period })
            })
            const data = await res.json()
            if (!res.ok) throw new Error(data.detail || 'Error al generar el cierre')
            setResult(data)
        } catch (e) { setError(e.message) }
        finally { setClosing(false) }
    }

    // Opciones de período (24 meses)
    const periodOptions = []
    const base = new Date()
    for (let i = 1; i < 25; i++) {
        const d = new Date(base.getFullYear(), base.getMonth() - i, 1)
        const val = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        periodOptions.push({ val, label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}` })
    }

    const hasDrafts = draftCount !== null && draftCount > 0
    const readyToClose = draftCount === 0 && !checking

    return (
        <div style={{ padding: '24px', maxWidth: 700, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>
            {/* Header */}
            <div style={{ marginBottom: 28 }}>
                <h1 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    🔒 Cierre de Período
                </h1>
                <p style={{ margin: '6px 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    Genera un asiento de cierre DRAFT que transfiere los saldos de Ingresos y Gastos
                    a la cuenta de <strong>Utilidad del Ejercicio (3303)</strong> o <strong>Pérdida (3302)</strong>.
                    El asiento queda en borrador — el contador debe aprobarlo desde el Libro Diario.
                </p>
            </div>

            {/* Selector de período */}
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 10, padding: 20, marginBottom: 20 }}>
                <label style={{ display: 'block', fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 8, fontWeight: 600 }}>
                    Período a cerrar
                </label>
                <select
                    id="cierre-period-select"
                    value={period}
                    onChange={e => setPeriod(e.target.value)}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.9rem' }}
                >
                    {periodOptions.map(o => <option key={o.val} value={o.val}>{o.label} ({o.val})</option>)}
                </select>
            </div>

            {/* Estado de verificación */}
            <div style={{ background: 'var(--bg-card)', border: `1px solid ${hasDrafts ? 'rgba(239,68,68,0.4)' : readyToClose ? 'rgba(16,185,129,0.4)' : 'var(--border-color)'}`, borderRadius: 10, padding: 18, marginBottom: 20 }}>
                <div style={{ fontSize: '0.88rem', fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>
                    Estado del período {period}
                </div>
                {checking && <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>⏳ Verificando asientos pendientes...</p>}
                {!checking && draftCount !== null && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ fontSize: '1.3rem' }}>{hasDrafts ? '❌' : '✅'}</span>
                        <span style={{ fontSize: '0.85rem', color: hasDrafts ? '#ef4444' : '#10b981', fontWeight: 600 }}>
                            {hasDrafts
                                ? `${draftCount} asiento(s) DRAFT pendiente(s) — debe(n) aprobarse o anularse antes del cierre`
                                : 'Sin asientos pendientes — listo para cerrar'}
                        </span>
                    </div>
                )}
                {hasDrafts && (
                    <a href="/diario" style={{ display: 'inline-block', marginTop: 10, fontSize: '0.82rem', color: '#7c3aed', textDecoration: 'underline' }}>
                        → Ir al Libro Diario para gestionarlos
                    </a>
                )}
            </div>

            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {/* Resultado exitoso */}
            {result && (
                <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: 10, padding: 20, marginBottom: 20 }}>
                    <div style={{ fontWeight: 700, color: '#10b981', marginBottom: 8 }}>✅ Asiento de cierre generado</div>
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                        <div>ID: <code style={{ background: 'rgba(0,0,0,0.2)', padding: '1px 6px', borderRadius: 4 }}>{result.entry_id?.slice(0, 12)}...</code></div>
                        <div>Estado: <strong>DRAFT</strong> — requiere aprobación del contador</div>
                        <div style={{ marginTop: 8, color: '#10b981', fontWeight: 600 }}>{result.next_action}</div>
                    </div>
                    <a
                        href="/diario"
                        style={{ display: 'inline-block', marginTop: 12, padding: '8px 18px', background: '#7c3aed', borderRadius: 7, color: 'white', fontSize: '0.85rem', fontWeight: 700, textDecoration: 'none' }}
                    >
                        → Ir al Libro Diario para aprobarlo
                    </a>
                </div>
            )}

            {/* Botón de cierre */}
            {canClose && !result && (
                <button
                    id="btn-generar-cierre"
                    onClick={handleClose}
                    disabled={!readyToClose || closing}
                    style={{
                        width: '100%',
                        padding: '14px',
                        background: readyToClose && !closing ? '#7c3aed' : 'rgba(124,58,237,0.3)',
                        border: 'none', borderRadius: 10,
                        color: 'white', fontSize: '1rem', fontWeight: 700,
                        cursor: readyToClose && !closing ? 'pointer' : 'not-allowed',
                        transition: 'all 0.2s'
                    }}
                >
                    {closing ? '⏳ Generando cierre...' : '🔒 Generar asiento de cierre DRAFT'}
                </button>
            )}

            {!canClose && (
                <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                    🔒 Solo el contador o administrador puede ejecutar el cierre de período.
                </div>
            )}

            {/* Nota legal */}
            <div style={{ marginTop: 24, padding: '12px 16px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 8, fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                <strong style={{ color: '#f59e0b' }}>📌 NIIF PYMES — Sección 22</strong><br />
                El cierre de período transfiere el saldo neto de cuentas de Ingresos (4xxx) y Gastos (5xxx)
                a la cuenta de Utilidades Retenidas (3303) o Pérdida del Ejercicio (3302).
                El asiento generado queda en <strong>DRAFT</strong> y requiere aprobación formal del contador.
            </div>
        </div>
    )
}
