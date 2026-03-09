import React, { useState, useEffect, useCallback } from 'react'
import { useApp } from '../context/AppContext'
import { useNavigate } from 'react-router-dom'

const API = import.meta.env.VITE_API_URL || ''
const MESES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function currentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
function periodLabel(p) {
    if (!p || p.length < 7) return p
    const [y, m] = p.split('-')
    return `${MESES[parseInt(m)] || m} ${y}`
}
function fmtCRC(n) {
    if (n == null || n === 0) return null
    return '₡' + Number(n).toLocaleString('es-CR', { minimumFractionDigits: 2 })
}

/* ── Badges de tipo de cuenta ─────────────────────────────────── */
const TIPO_CFG = {
    ACTIVO: { color: '#06b6d4', bg: 'rgba(6,182,212,0.12)', label: 'ACTIVO' },
    PASIVO: { color: '#f97316', bg: 'rgba(249,115,22,0.12)', label: 'PASIVO' },
    PATRIMONIO: { color: '#a855f7', bg: 'rgba(168,85,247,0.12)', label: 'PATRIMONIO' },
    INGRESO: { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'INGRESO' },
    GASTO: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'GASTO' },
    '': { color: '#64748b', bg: 'rgba(100,116,139,0.12)', label: '---' },
}
function TipoBadge({ tipo }) {
    const cfg = TIPO_CFG[tipo] || TIPO_CFG['']
    return (
        <span style={{
            fontSize: '0.68rem', fontWeight: 700, padding: '2px 8px',
            borderRadius: 12, background: cfg.bg, color: cfg.color,
            whiteSpace: 'nowrap', letterSpacing: '0.04em',
        }}>
            {cfg.label}
        </span>
    )
}

/* ── Celda de monto (DEBE o HABER) ───────────────────────────── */
function MontoCell({ valor, alarma, col }) {
    if (!valor) return <td style={tdR}><span style={{ color: 'var(--text-muted)', opacity: 0.4 }}>—</span></td>
    const color = alarma
        ? '#f59e0b'                                // saldo contra natura → ámbar
        : col === 'debe' ? 'var(--text-primary)' : '#93c5fd'
    return (
        <td style={{ ...tdR, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
            <span style={{ color }}>{fmtCRC(valor)}</span>
            {alarma && <span title="Saldo contra natura" style={{ marginLeft: 4, fontSize: '0.7rem' }}>⚠️</span>}
        </td>
    )
}

/* ── Componente principal ────────────────────────────────────── */
export default function BalanzaComprobacion() {
    const { state } = useApp()
    const token = state.token || localStorage.getItem('gc_token')
    const navigate = useNavigate()

    const [period, setPeriod] = useState(currentPeriod())
    const [mode, setMode] = useState('ytd')    // ytd (Acumulado) | period (Mes)
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const load = useCallback(async (p, m) => {
        setLoading(true); setError(null)
        try {
            const r = await fetch(
                `${API}/ledger/trial-balance?period=${p}&mode=${m}`,
                { headers: { Authorization: `Bearer ${token}` } }
            )
            if (!r.ok) throw new Error(`HTTP ${r.status}`)
            setData(await r.json())
        } catch (e) { setError(e.message) }
        setLoading(false)
    }, [token])

    useEffect(() => { if (period?.length >= 7) load(period, mode) }, [period, mode, load])

    /* Exportar CSV */
    function exportCSV() {
        if (!data?.lines?.length) return
        const rows = [
            ['Código', 'Nombre', 'Tipo', 'Debe (Saldo Deudor)', 'Haber (Saldo Acreedor)'],
            ...data.lines.map(l => [
                l.account_code, l.account_name, l.account_type,
                l.saldo_debe || '',
                l.saldo_haber || '',
            ]),
            ['', '', 'TOTAL', data.total_saldo_debe, data.total_saldo_haber],
        ]
        const csv = rows.map(r => r.join(',')).join('\n')
        const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `Balanza_${period}_${mode}.csv`; a.click()
        URL.revokeObjectURL(url)
    }

    const lines = data?.lines || []
    const balanced = data?.balanced_saldos ?? data?.balanced

    return (
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 20px' }}>

            {/* Header */}
            <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                        ⚖️ Balanza de Comprobación
                    </h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 4 }}>
                        Saldo neto por cuenta según naturaleza contable · NIIF PYMES Sec. 2.36
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={exportCSV} disabled={!data} style={btnSecondary}>
                        📊 Excel / CSV
                    </button>
                </div>
            </div>

            {/* Controles: período + toggle Mes/Acumulado */}
            <div style={{ ...cardStyle, padding: '14px 20px', marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <label style={labelStyle}>Período</label>
                    <input
                        type="month"
                        value={period}
                        onChange={e => setPeriod(e.target.value)}
                        style={{ ...inputStyle, width: 160, textAlign: 'center', fontWeight: 700 }}
                    />
                </div>

                <div style={{ display: 'flex', gap: 0, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    {[
                        { k: 'period', label: 'Mes', sub: 'Solo el período' },
                        { k: 'ytd', label: 'Acumulado', sub: 'Desde enero' },
                    ].map(t => (
                        <button key={t.k} onClick={() => setMode(t.k)} style={{
                            padding: '7px 18px', border: 'none', cursor: 'pointer',
                            background: mode === t.k ? 'var(--accent)' : 'var(--bg-secondary)',
                            color: mode === t.k ? '#fff' : 'var(--text-muted)',
                            fontSize: '0.82rem', fontWeight: mode === t.k ? 700 : 400,
                            transition: 'all 0.15s',
                        }}>
                            {t.label}
                        </button>
                    ))}
                </div>

                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {mode === 'ytd'
                        ? `Ene ${period?.slice(0, 4)} → ${periodLabel(period)}`
                        : `Solo ${periodLabel(period)}`
                    }
                </div>
            </div>

            {/* Cuadratura del saldo */}
            {data && (
                <div style={{
                    ...cardStyle, padding: '10px 18px', marginBottom: 16,
                    background: balanced ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)',
                    borderColor: balanced ? '#16a34a40' : '#dc262640',
                    display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap',
                }}>
                    <span style={{ fontWeight: 700, fontSize: '0.85rem', color: balanced ? '#16a34a' : '#dc2626' }}>
                        {balanced ? '✅ Balanza cuadra' : '❌ Balanza no cuadra'}
                    </span>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        Σ DEBE: <strong style={{ color: 'var(--text-primary)' }}>{fmtCRC(data.total_saldo_debe)}</strong>
                    </span>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        Σ HABER: <strong style={{ color: '#93c5fd' }}>{fmtCRC(data.total_saldo_haber)}</strong>
                    </span>
                    {!balanced && (
                        <span style={{ fontSize: '0.75rem', color: '#dc2626' }}>
                            Diferencia: {fmtCRC(data.diff_saldos)}
                        </span>
                    )}
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                        {data.lines?.length} cuenta(s) · {mode === 'ytd' ? `Acum. Ene–${periodLabel(period)}` : `Solo ${periodLabel(period)}`}
                    </span>
                </div>
            )}

            {/* Tabla */}
            <div style={cardStyle}>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                        <thead>
                            <tr style={{ background: 'var(--bg-secondary)', fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                <th style={{ ...th, width: 90 }}>Código</th>
                                <th style={th}>Nombre de la cuenta</th>
                                <th style={{ ...th, width: 110, textAlign: 'center' }}>Tipo</th>
                                <th style={{ ...thR, width: 180, color: '#e2e8f0' }}>
                                    DEBE<br />
                                    <span style={{ fontSize: '0.65rem', fontWeight: 400, opacity: 0.7 }}>Saldo Deudor</span>
                                </th>
                                <th style={{ ...thR, width: 180, color: '#93c5fd' }}>
                                    HABER<br />
                                    <span style={{ fontSize: '0.65rem', fontWeight: 400, opacity: 0.7 }}>Saldo Acreedor</span>
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading && (
                                <tr><td colSpan={5} style={{ padding: 28, textAlign: 'center', color: 'var(--text-muted)' }}>⏳ Cargando...</td></tr>
                            )}
                            {error && (
                                <tr><td colSpan={5} style={{ padding: 28, textAlign: 'center', color: '#dc2626' }}>❌ {error}</td></tr>
                            )}
                            {!loading && !error && lines.length === 0 && (
                                <tr><td colSpan={5} style={{ padding: 28, textAlign: 'center', color: 'var(--text-muted)' }}>Sin movimientos POSTED en este período</td></tr>
                            )}
                            {lines.map((l, i) => (
                                <tr
                                    key={l.account_code}
                                    style={{
                                        borderBottom: '1px solid var(--border)',
                                        background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)',
                                        cursor: 'pointer',
                                    }}
                                    onClick={() => navigate(`/mayor?code=${l.account_code}`)}
                                    title="Ir al Libro Mayor de esta cuenta"
                                >
                                    <td style={{ ...td, fontFamily: 'monospace', color: 'var(--accent)', fontWeight: 700 }}>
                                        {l.account_code}
                                    </td>
                                    <td style={td}>
                                        {l.account_name}
                                        {l.alarma_naturaleza && (
                                            <span title="Saldo con naturaleza invertida (anómalo)" style={{ marginLeft: 6, fontSize: '0.7rem', color: '#f59e0b' }}>⚠️ contra natura</span>
                                        )}
                                    </td>
                                    <td style={{ ...td, textAlign: 'center' }}>
                                        <TipoBadge tipo={l.account_type} />
                                    </td>
                                    <MontoCell valor={l.saldo_debe} alarma={l.alarma_naturaleza && l.saldo_debe} col="debe" />
                                    <MontoCell valor={l.saldo_haber} alarma={l.alarma_naturaleza && l.saldo_haber} col="haber" />
                                </tr>
                            ))}
                        </tbody>
                        {data && lines.length > 0 && (
                            <tfoot>
                                <tr style={{ background: 'var(--bg-card)', borderTop: '2px solid var(--border)' }}>
                                    <td colSpan={3} style={{ padding: '12px 14px', fontWeight: 800, fontSize: '0.85rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                        TOTAL — {lines.length} cuenta(s)
                                    </td>
                                    <td style={{ ...tdR, fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.9rem' }}>
                                        {fmtCRC(data.total_saldo_debe)}
                                    </td>
                                    <td style={{ ...tdR, fontWeight: 800, color: '#93c5fd', fontSize: '0.9rem' }}>
                                        {fmtCRC(data.total_saldo_haber)}
                                    </td>
                                </tr>
                                <tr style={{ background: balanced ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)' }}>
                                    <td colSpan={5} style={{ padding: '6px 14px', textAlign: 'center', fontSize: '0.72rem', color: balanced ? '#16a34a' : '#dc2626' }}>
                                        {balanced
                                            ? `✅ La balanza cuadra · Diferencia: ${fmtCRC(data.diff_saldos) || '₡0.00'}`
                                            : `❌ Diferencia de cuadratura: ${fmtCRC(data.diff_saldos)} — revisar asientos`
                                        }
                                    </td>
                                </tr>
                            </tfoot>
                        )}
                    </table>
                </div>
            </div>

            {/* Legenda de natureza */}
            <div style={{ marginTop: 14, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                <span>⚖️ <strong>DEBE</strong>: Activos · Gastos (naturaleza deudora)</span>
                <span>⚖️ <strong>HABER</strong>: Pasivos · Patrimonio · Ingresos (naturaleza acreedora)</span>
                <span>⚠️ <strong>Contra natura</strong>: saldo invertido — revisar asientos</span>
                <span>🖱️ Clic en cuenta → Libro Mayor</span>
            </div>
        </div>
    )
}

/* ── Estilos ──────────────────────────────────────────────────── */
const inputStyle = {
    background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 7,
    padding: '7px 10px', color: 'var(--text-primary)', fontSize: '0.85rem',
    outline: 'none', boxSizing: 'border-box',
}
const labelStyle = {
    fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '0.05em',
}
const btnSecondary = {
    background: 'var(--bg-3)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '7px 14px', fontSize: '0.83rem', fontWeight: 600, cursor: 'pointer',
}
const cardStyle = {
    background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 14, overflow: 'hidden',
}
const th = { padding: '10px 14px', textAlign: 'left', fontWeight: 700 }
const thR = { padding: '10px 14px', textAlign: 'right', fontWeight: 700 }
const td = { padding: '9px 14px', textAlign: 'left', color: 'var(--text-primary)' }
const tdR = { padding: '9px 14px', textAlign: 'right', color: 'var(--text-primary)' }
