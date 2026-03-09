import React, { useState, useEffect, useCallback } from 'react'
import { useApp } from '../context/AppContext'

const API = import.meta.env.VITE_API_URL || ''
const MESES_LABEL = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

/* ── Estado del período post-cierre ───────────────────────── */
function getPeriodStatus(period) {
    if (!period || period.length < 6) return 'DESCONOCIDO'
    const year = parseInt(period.slice(0, 4))
    const month = parseInt(period.slice(4, 6))
    if (isNaN(year) || isNaN(month)) return 'DESCONOCIDO'
    const today = new Date(), curY = today.getFullYear(), curM = today.getMonth() + 1, curD = today.getDate()
    if (year > curY || (year === curY && month > curM)) return 'FUTURO'
    if (year === curY && month === curM) return 'ABIERTO'
    const diff = (curY - year) * 12 + (curM - month)
    if (diff === 1 && curD <= 10) return 'RECIENTE'
    return 'CERRADO'
}
const PERIOD_BANNER = {
    FUTURO: { bg: 'rgba(148,163,184,0.12)', border: '#94a3b8', color: '#475569', emoji: '📅', titulo: 'Período futuro', texto: 'Este período aún no ha iniciado.', acciones: [] },
    ABIERTO: { bg: 'rgba(34,197,94,0.08)', border: '#16a34a', color: '#15803d', emoji: '🟢', titulo: 'Período abierto — Ventana óptima', texto: 'Momentáneo ideal. Podés emitir FE, crear asientos correctivos y corregir antes del cierre.', acciones: ['✅ Emitir FE faltantes', '✅ Crear asientos correctivos'] },
    RECIENTE: { bg: 'rgba(251,191,36,0.10)', border: '#d97706', color: '#b45309', emoji: '🟡', titulo: 'Período cerrado — D-270 aún en plazo', texto: 'El mes cerró pero la D-270 se puede presentar antes del día 10.', acciones: ['✅ Score CENTINELA (solo lectura)', '✅ Exportar D-270 a Tribu-CR antes del día 10', '⚠️ FE extemporánea requiere análisis previo', '❌ No se agregan asientos al período cerrado'] },
    CERRADO: { bg: 'rgba(239,68,68,0.08)', border: '#dc2626', color: '#b91c1c', emoji: '🔴', titulo: 'Período cerrado — Revisión preventiva ✔', texto: 'El plazo D-270 venció. Esta revisión es válida para identificar patrones y corregir en el mes actual.', acciones: ['✅ Score como referencia histórica', '✅ Detectar patrones para NO repetir', '⚠️ FE extemporánea posible con multa', '❌ D-270 ordinaria fuera de plazo'] },
    DESCONOCIDO: { bg: 'var(--bg-secondary)', border: 'var(--border)', color: 'var(--text-muted)', emoji: 'ℹ️', titulo: 'Período inválido', texto: 'Escribe el período en formato YYYYMM.', acciones: [] },
}
function PeriodBanner({ period }) {
    const [open, setOpen] = React.useState(true)
    const status = getPeriodStatus(period)
    const cfg = PERIOD_BANNER[status] || PERIOD_BANNER.DESCONOCIDO
    if (status === 'ABIERTO' && !open) return null
    return (
        <div style={{ border: `1px solid ${cfg.border}40`, background: cfg.bg, borderRadius: 10, padding: '12px 16px', marginBottom: 18, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <div style={{ fontSize: '1.3rem', flexShrink: 0 }}>{cfg.emoji}</div>
            <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', color: cfg.color, marginBottom: 3 }}>{cfg.titulo}</div>
                <div style={{ fontSize: '0.78rem', color: cfg.color, opacity: 0.85, marginBottom: cfg.acciones.length ? 8 : 0 }}>{cfg.texto}</div>
                {cfg.acciones.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.75rem', color: cfg.color, opacity: 0.8 }}>
                        {cfg.acciones.map((a, i) => <li key={i} style={{ marginBottom: 2 }}>{a}</li>)}
                    </ul>
                )}
            </div>
            <button onClick={() => setOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: cfg.color, fontSize: '1rem', opacity: 0.5, flexShrink: 0, padding: 0 }}>×</button>
        </div>
    )
}

function authH(t) { return { Authorization: `Bearer ${t}` } }

function authJ(t) { return { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` } }
function formatCRC(n) {
    if (n == null || isNaN(n)) return '₡0'
    return '₡' + Number(n).toLocaleString('es-CR', { minimumFractionDigits: 0 })
}
function currentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}
function periodLabel(p) {
    if (!p || p.length < 6) return p
    const m = parseInt(p.slice(4, 6))
    return `${MESES_LABEL[m]} ${p.slice(0, 4)}`
}

/* ── Score Gauge circular ── */
function ScoreGauge({ score, nivel, emoji }) {
    const radius = 60
    const circ = 2 * Math.PI * radius
    const pct = Math.min(score, 100) / 100
    const offset = circ * (1 - pct)

    const colorMap = {
        VERDE: ['#16a34a', '#22c55e'],
        BAJO: ['#0ea5e9', '#38bdf8'],
        MODERADO: ['#d97706', '#f59e0b'],
        EN_RIESGO: ['#ea580c', '#f97316'],
        CRITICO: ['#dc2626', '#ef4444'],
        SALUDABLE: ['#16a34a', '#22c55e'],
        SIN_DATOS: ['#64748b', '#94a3b8'],
    }
    const [c1, c2] = colorMap[nivel] || colorMap.SIN_DATOS

    return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            <svg width={160} height={160} viewBox="-10 -10 160 160">
                <defs>
                    <linearGradient id="scoreGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor={c1} />
                        <stop offset="100%" stopColor={c2} />
                    </linearGradient>
                </defs>
                {/* Track */}
                <circle cx={70} cy={70} r={radius} fill="none"
                    stroke="var(--bg-secondary)" strokeWidth={14} />
                {/* Progress */}
                <circle cx={70} cy={70} r={radius} fill="none"
                    stroke="url(#scoreGrad)" strokeWidth={14}
                    strokeDasharray={circ}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                    transform={`rotate(-90 70 70)`}
                    style={{ transition: 'stroke-dashoffset 1s ease' }}
                />
                {/* Score center */}
                <text x={70} y={60} textAnchor="middle"
                    style={{ fontSize: 28, fontWeight: 800, fill: c1 }}>
                    {score}
                </text>
                <text x={70} y={82} textAnchor="middle"
                    style={{ fontSize: 11, fill: 'var(--text-muted)' }}>
                    / 100
                </text>
                <text x={70} y={100} textAnchor="middle"
                    style={{ fontSize: 18 }}>
                    {emoji}
                </text>
            </svg>
            <div style={{
                fontWeight: 800, fontSize: '0.9rem',
                color: c1, letterSpacing: '0.04em',
            }}>
                {nivel === 'SIN_DATOS' ? 'Sin datos' : nivel.replace('_', ' ')}
            </div>
        </div>
    )
}

/* ── Tarjeta de fuga ── */
function FugaCard({ fuga, index }) {
    const tipoConfig = {
        A: { label: 'Tipo A — Ingreso sin FE', color: '#dc2626', bg: 'rgba(239,68,68,0.08)', emoji: '🔴' },
        B: { label: 'Tipo B — Gasto sin D-270', color: '#d97706', bg: 'rgba(251,191,36,0.08)', emoji: '🟡' },
        C: { label: 'Tipo C — SINPE código incorrecto', color: '#7c3aed', bg: 'rgba(139,92,246,0.08)', emoji: '🟣' },
    }
    const cfg = tipoConfig[fuga.fuga_tipo] || { label: 'Fuga', color: '#64748b', bg: 'var(--bg-secondary)', emoji: '⚠️' }

    return (
        <div style={{
            background: cfg.bg, border: `1px solid ${cfg.color}30`,
            borderRadius: 10, padding: '12px 16px', marginBottom: 8,
        }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '0.72rem', fontWeight: 700, color: cfg.color, marginBottom: 4 }}>
                        {cfg.emoji} {cfg.label}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)', marginBottom: 4 }}>
                        {fuga.txn_descripcion || fuga.descripcion}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        📅 {fuga.txn_fecha} &nbsp;|&nbsp;
                        🎯 {fuga.accion}
                    </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>IVA en riesgo</div>
                    <div style={{ fontWeight: 800, color: cfg.color, fontSize: '0.95rem' }}>
                        {formatCRC(fuga.iva_riesgo)}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        base {formatCRC(fuga.base_riesgo)}
                    </div>
                </div>
            </div>
            {fuga.d270_codigo && (
                <div style={{
                    marginTop: 8, display: 'inline-flex', alignItems: 'center', gap: 5,
                    background: 'rgba(59,130,246,0.12)', borderRadius: 6, padding: '3px 10px',
                    fontSize: '0.72rem', color: '#3b82f6', fontWeight: 700,
                }}>
                    📋 D-270 código '{fuga.d270_codigo}'
                </div>
            )}
        </div>
    )
}

/* ── Tabla D-270 ── */
function D270Preview({ items, resumen, period, token }) {
    const [exporting, setExporting] = useState(false)

    const codigos = resumen?.codigos || {}
    const totales = resumen?.totales || {}
    const conteos = resumen?.conteos || {}

    async function exportCSV() {
        setExporting(true)
        try {
            const r = await fetch(`${API}/centinela/d270/${period}/export`, { headers: authH(token) })
            const text = await r.text()
            const blob = new Blob([text], { type: 'text/csv' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url; a.download = `D270_${period}.csv`; a.click()
            URL.revokeObjectURL(url)
        } catch (e) { console.error('Export error', e) }
        setExporting(false)
    }

    if (!items?.length) return (
        <div style={{
            textAlign: 'center', padding: '28px', color: 'var(--text-muted)',
            border: '1px dashed var(--border)', borderRadius: 10, fontSize: '0.84rem'
        }}>
            <div style={{ fontSize: '2rem', marginBottom: 8 }}>📋</div>
            No hay registros para D-270 este período.<br />
            <span style={{ fontSize: '0.78rem' }}>Los gastos sin FE aparecerán aquí automáticamente.</span>
        </div>
    )

    return (
        <div>
            {/* Resumen por código */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                {Object.entries(codigos).map(([cod, label]) => (
                    totales[cod] > 0 && (
                        <div key={cod} style={{
                            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                            borderRadius: 8, padding: '8px 14px', textAlign: 'center', minWidth: 100
                        }}>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                                Código <strong>{cod}</strong> ({conteos[cod]} reg.)
                            </div>
                            <div style={{ fontWeight: 800, color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                                {formatCRC(totales[cod])}
                            </div>
                            <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                {label.substring(0, 18)}…
                            </div>
                        </div>
                    )
                ))}
            </div>

            {/* Tabla de registros */}
            <div style={{ overflowX: 'auto', marginBottom: 14 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                        <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                            <th style={{ padding: '6px 10px', textAlign: 'left' }}>Concepto</th>
                            <th style={{ padding: '6px 10px', textAlign: 'center' }}>Código</th>
                            <th style={{ padding: '6px 10px', textAlign: 'right' }}>Monto base</th>
                            <th style={{ padding: '6px 10px', textAlign: 'left' }}>Observación</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.map((it, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                <td style={{ padding: '7px 10px' }}>{it.descripcion}</td>
                                <td style={{ padding: '7px 10px', textAlign: 'center' }}>
                                    <span style={{
                                        background: 'rgba(59,130,246,0.12)', color: '#3b82f6',
                                        borderRadius: 4, padding: '2px 8px', fontSize: '0.72rem', fontWeight: 700
                                    }}>
                                        {it.d270_codigo || it.monto?.d270_codigo}
                                    </span>
                                </td>
                                <td style={{ padding: '7px 10px', textAlign: 'right', fontWeight: 600 }}>
                                    {formatCRC(it.monto)}
                                </td>
                                <td style={{ padding: '7px 10px', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                                    {it.observacion}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button onClick={exportCSV} disabled={exporting} style={{
                    background: 'linear-gradient(135deg,#0ea5e9,#0284c7)', color: '#fff',
                    border: 'none', borderRadius: 8, padding: '8px 18px',
                    fontSize: '0.83rem', fontWeight: 700, cursor: 'pointer',
                }}>
                    {exporting ? '⏳ Generando...' : '⬇️ Exportar CSV para Tribu-CR'}
                </button>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    📅 Presentar antes del día 10 del mes siguiente
                </span>
            </div>
        </div>
    )
}

/* ── Página CENTINELA ─────────────────────────────────────────────── */
export default function Centinela() {
    const { state } = useApp()
    const token = state.token || localStorage.getItem('gc_token')

    const [period, setPeriod] = useState(currentPeriod())
    const [scoreData, setScoreData] = useState(null)
    const [fugas, setFugas] = useState([])
    const [d270, setD270] = useState(null)
    const [sesionTxns, setSesionTxns] = useState([])   // F8: tabla CON_FE/SIN_FE
    const [loading, setLoading] = useState(false)
    const [analyzing, setAnalyzing] = useState(false)
    const [exportingCSV, setExportingCSV] = useState(false)
    const [tab, setTab] = useState('score') // score | tabla | fugas | d270

    /* Export CSV de la sesión (F7) */
    async function exportarResultado(recon_id) {
        if (!recon_id) return
        setExportingCSV(true)
        try {
            const r = await fetch(`${API}/centinela/resultado/${recon_id}/export`, { headers: authH(token) })
            const text = await r.text()
            const blob = new Blob([text], { type: 'text/csv' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url; a.download = `Conciliacion_${period}.csv`; a.click()
            URL.revokeObjectURL(url)
        } catch (e) { console.error('Export error', e) }
        setExportingCSV(false)
    }

    /* Export D-150 (F7) */
    async function exportarD150() {
        try {
            const year = period.slice(0, 4)
            const r = await fetch(`${API}/centinela/d150/${year}/export`, { headers: authH(token) })
            const text = await r.text()
            const blob = new Blob([text], { type: 'text/csv' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url; a.download = `D150_${year}.csv`; a.click()
            URL.revokeObjectURL(url)
        } catch (e) { console.error('D150 export error', e) }
    }

    const loadScore = useCallback(async (p) => {
        setLoading(true)
        try {
            const r = await fetch(`${API}/centinela/score/${p}`, { headers: authH(token) })
            const d = await r.json()
            setScoreData(d)
        } catch { setScoreData(null) }
        setLoading(false)
    }, [token])

    const loadD270 = useCallback(async (p) => {
        try {
            const r = await fetch(`${API}/centinela/d270/${p}`, { headers: authH(token) })
            const d = await r.json()
            setD270(d)
        } catch { setD270(null) }
    }, [token])

    useEffect(() => {
        if (period?.length === 6) {
            loadScore(period)
            loadD270(period)
        }
    }, [period, loadScore, loadD270])

    const exposicionTotal = scoreData?.exposicion_total || 0
    const exposicionIva = scoreData?.exposicion_iva || 0
    const nivelScore = scoreData?.nivel || 'SIN_DATOS'
    const score = scoreData?.score_total ?? 0
    const isV2 = scoreData?.version === 'v2'
    const indicadores = scoreData?.indicadores || {}
    const totalesV2 = scoreData?.totales || {}

    return (
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 20px' }}>

            {/* Header */}
            <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                        🛡️ CENTINELA Fiscal {isV2 && <span style={{ fontSize: '0.7rem', background: 'rgba(34,197,94,0.15)', color: '#16a34a', borderRadius: 6, padding: '2px 8px', marginLeft: 8, fontWeight: 700 }}>Score V2</span>}
                    </h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 5 }}>
                        CON_FE / SIN_FE · 5 indicadores DGT · D-150 automático · Export CSV
                    </p>
                </div>

                {/* Selector de período */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input
                        type="text"
                        placeholder="YYYYMM"
                        value={period}
                        onChange={e => setPeriod(e.target.value)}
                        maxLength={6}
                        style={{ ...inputStyle, width: 110, textAlign: 'center', fontWeight: 700 }}
                    />
                    <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                        {periodLabel(period)}
                    </span>
                </div>
            </div>

            {/* Banner de estado del período */}
            <PeriodBanner period={period} />

            {/* ── Fila superior: Score + Exposición ── */}
            <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 16, marginBottom: 20 }}>

                {/* Gauge */}
                <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
                    {loading ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Cargando...</div>
                    ) : (
                        <ScoreGauge
                            score={score}
                            nivel={nivelScore}
                            emoji={scoreData?.emoji || '📊'}
                        />
                    )}
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
                        Riesgo fiscal · {periodLabel(period)}
                    </div>
                </div>

                {/* Métricas de exposición */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                    {[
                        {
                            label: 'Exposición IVA', value: formatCRC(exposicionIva),
                            sub: 'IVA no declarado estimado', color: '#dc2626',
                            bg: 'rgba(239,68,68,0.06)', emoji: '🔴'
                        },
                        {
                            label: 'Exposición Renta', value: formatCRC(scoreData?.exposicion_renta),
                            sub: 'Renta estimada en riesgo', color: '#d97706',
                            bg: 'rgba(251,191,36,0.06)', emoji: '🟡'
                        },
                        {
                            label: 'Exposición Total', value: formatCRC(exposicionTotal),
                            sub: 'IVA + Renta combinado', color: '#7c3aed',
                            bg: 'rgba(139,92,246,0.06)', emoji: '⚡'
                        },
                        {
                            label: isV2 ? 'CON FE' : 'Fugas detectadas',
                            value: isV2 ? `${totalesV2.con_fe || 0}` : `${(scoreData?.fugas_tipo_a || 0) + (scoreData?.fugas_tipo_b || 0) + (scoreData?.fugas_tipo_c || 0)}`,
                            sub: isV2 ? `${totalesV2.total_txns || 0} txns totales` : `A:${scoreData?.fugas_tipo_a || 0} B:${scoreData?.fugas_tipo_b || 0} C:${scoreData?.fugas_tipo_c || 0}`,
                            color: '#16a34a', bg: 'rgba(34,197,94,0.06)', emoji: '✅'
                        },
                        {
                            label: isV2 ? 'SIN FE (riesgo)' : 'Registros D-270',
                            value: isV2 ? `${totalesV2.sin_fe || 0}` : `${scoreData?.d270_regs || d270?.resumen?.total_registros || 0}`,
                            sub: isV2 ? 'Sin comprobante fiscal' : 'A declarar antes del día 10',
                            color: totalesV2.sin_fe > 0 ? '#dc2626' : '#64748b',
                            bg: totalesV2.sin_fe > 0 ? 'rgba(239,68,68,0.06)' : 'rgba(100,116,139,0.06)', emoji: totalesV2.sin_fe > 0 ? '🔴' : '📋'
                        },
                    ].map(m => (
                        <div key={m.label} style={{
                            ...cardStyle, padding: '14px 16px', background: m.bg,
                            borderColor: `${m.color}30`,
                        }}>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 4 }}>
                                {m.emoji} {m.label}
                            </div>
                            <div style={{ fontSize: '1.35rem', fontWeight: 800, color: m.color }}>
                                {m.value}
                            </div>
                            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 3 }}>
                                {m.sub}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Barra de reglas disparadas */}
            {scoreData?.detalle?.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: 16, padding: '12px 18px' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Reglas de riesgo activadas
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {scoreData.detalle.map((d, i) => (
                            <div key={i} style={{
                                background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                                borderRadius: 8, padding: '6px 12px', fontSize: '0.75rem',
                            }}>
                                <span style={{ fontWeight: 700, color: '#dc2626' }}>{d.regla}</span>
                                <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>+{d.puntos}pts</span>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginTop: 2 }}>
                                    {d.desc?.substring(0, 60)}{d.desc?.length > 60 ? '…' : ''}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* ── Botón Info + Tooltip de normativa fiscal ─────────────────── */}
            {(() => {
                const [showInfo, setShowInfo] = React.useState(false)
                React.useEffect(() => {
                    if (!showInfo) return
                    const close = () => setShowInfo(false)
                    document.addEventListener('click', close)
                    return () => document.removeEventListener('click', close)
                }, [showInfo])
                return (
                    <div style={{ position: 'relative', display: 'inline-block', marginBottom: 16 }}>
                        <button
                            id="btn-centinela-info"
                            onClick={e => { e.stopPropagation(); setShowInfo(p => !p) }}
                            style={{
                                background: 'var(--bg-card)', border: '1px solid var(--border)',
                                borderRadius: 20, padding: '5px 14px', cursor: 'pointer',
                                fontSize: '0.8rem', color: 'var(--text-muted)',
                                display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600,
                                boxShadow: showInfo ? '0 2px 8px rgba(0,0,0,0.18)' : 'none',
                                transition: 'box-shadow 0.15s',
                            }}
                        >
                            💡 Info
                        </button>
                        {showInfo && (
                            <div
                                onClick={e => e.stopPropagation()}
                                style={{
                                    position: 'absolute', top: 'calc(100% + 8px)', left: 0,
                                    zIndex: 1200, width: 320,
                                    background: 'var(--bg-card)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 12, padding: '16px 18px',
                                    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                                }}
                            >
                                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    💡 Normativa fiscal aplicada
                                </div>
                                {[
                                    { icon: '⚖️', label: 'Decreto 44739-H', desc: 'SINPE debe tener FE con código 06' },
                                    { icon: '📋', label: 'D-270', desc: 'Gastos sin FE a declarar antes del día 10' },
                                    { icon: '📊', label: 'IVA', desc: 'monto ÷ 1.13 × 0.13 = IVA incluido' },
                                    { icon: '🏛️', label: 'Renta', desc: 'base estimada × 15% (conservador)' },
                                ].map(row => (
                                    <div key={row.label} style={{
                                        display: 'flex', gap: 10, alignItems: 'flex-start',
                                        padding: '7px 0', borderBottom: '1px solid var(--border)',
                                        fontSize: '0.78rem',
                                    }}>
                                        <span style={{ fontSize: '1rem', flexShrink: 0 }}>{row.icon}</span>
                                        <div>
                                            <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{row.label}</span>
                                            <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>— {row.desc}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )
            })()}

            {/* Tabs: Score / Tabla / Fugas / D-270 */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ display: 'flex', gap: 4, flex: 1, flexWrap: 'wrap' }}>
                    {[
                        { k: 'score', label: '📊 Score V2' },
                        { k: 'tabla', label: '📄 Conciliación' },
                        { k: 'fugas', label: '🔴 Fugas' },
                        { k: 'd270', label: '📋 D-270' },
                    ].map(t => (
                        <button key={t.k} onClick={() => setTab(t.k)} style={{
                            ...btnChoice,
                            background: tab === t.k ? 'var(--accent)' : 'var(--bg-secondary)',
                            color: tab === t.k ? '#fff' : 'var(--text-muted)',
                            borderColor: tab === t.k ? 'var(--accent)' : 'var(--border)',
                        }}>
                            {t.label}
                        </button>
                    ))}
                </div>
                {/* Botones de export rápido */}
                <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={() => exportarResultado(scoreData?.recon_id)} disabled={exportingCSV} style={{
                        ...btnChoice, background: 'rgba(14,165,233,0.1)', color: '#0ea5e9',
                        borderColor: '#0ea5e9', fontSize: '0.75rem',
                    }}>
                        {exportingCSV ? '⏳' : '⬇️ Excel'}
                    </button>
                    <button onClick={exportarD150} style={{
                        ...btnChoice, background: 'rgba(124,58,237,0.1)', color: '#7c3aed',
                        borderColor: '#7c3aed', fontSize: '0.75rem',
                    }}>
                        📑 D-150
                    </button>
                </div>
            </div>

            {/* Contenido de tabs */}
            <div style={cardStyle}>
                {tab === 'score' && (
                    <div style={{ padding: '20px' }}>
                        {!scoreData || nivelScore === 'SIN_DATOS' ? (
                            <div style={{ textAlign: 'center', padding: '28px', color: 'var(--text-muted)' }}>
                                <div style={{ fontSize: '3rem', marginBottom: 12 }}>🛡️</div>
                                <div style={{ fontSize: '0.9rem', marginBottom: 8 }}>No hay análisis CENTINELA para este período aún.</div>
                                <div style={{ fontSize: '0.8rem' }}>Primero realiza la <strong>Conciliación Bancaria</strong> y luego haz clic en "Analizar con CENTINELA".</div>
                            </div>
                        ) : isV2 ? (
                            /* ── Score V2: 5 indicadores DGT ─────────────────────────── */
                            <div>
                                <div style={{ marginBottom: 14, fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 700 }}>
                                    5 indicadores DGT · {periodLabel(period)} · Score inverso (100=sin riesgo)
                                </div>
                                <div style={{ display: 'grid', gap: 10 }}>
                                    {[
                                        { key: 'I1_cobertura_documental', peso: '30%', label: 'Cobertura documental', desc: 'Txns CON_FE ÷ total. 100 = todas tienen FE.' },
                                        { key: 'I2_exposicion_iva', peso: '25%', label: 'Exposición IVA', desc: 'IVA estimado en riesgo ÷ ingresos. 100 = sin IVA expuesto.' },
                                        { key: 'I3_concentracion_sinfe', peso: '20%', label: 'Concentración sin FE', desc: 'Top-3 proveedores sin FE ÷ total débitos. 100 = disperso.' },
                                        { key: 'I4_sin_referencia', peso: '15%', label: 'Sin referencia trazable', desc: 'SINPE/transfer sin FE ÷ total. 100 = todas trazables.' },
                                        { key: 'I5_discrepancia_d101', peso: '10%', label: 'Brecha banco vs FE-D101', desc: 'Diferencia ingresos banco vs FE emitidas. 100 = cuadran.' },
                                    ].map(ind => {
                                        const val = indicadores[ind.key] ?? 0
                                        const color = val >= 90 ? '#16a34a' : val >= 70 ? '#0ea5e9' : val >= 40 ? '#d97706' : '#dc2626'
                                        return (
                                            <div key={ind.key} style={{ padding: '10px 14px', background: `${color}08`, borderRadius: 10, border: `1px solid ${color}20` }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                                                    <div>
                                                        <span style={{ fontWeight: 700, fontSize: '0.82rem', color }}>{ind.label}</span>
                                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 8 }}>({ind.peso})</span>
                                                    </div>
                                                    <span style={{ fontWeight: 800, fontSize: '1.05rem', color }}>{val}</span>
                                                </div>
                                                {/* Barra de progreso del indicador */}
                                                <div style={{ height: 6, background: 'var(--bg-secondary)', borderRadius: 4, overflow: 'hidden', marginBottom: 4 }}>
                                                    <div style={{ height: '100%', width: `${val}%`, background: color, borderRadius: 4, transition: 'width 0.8s ease' }} />
                                                </div>
                                                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{ind.desc}</div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        ) : (
                            /* ── Score V1 legado ──── */
                            <div>
                                <div style={{ marginBottom: 12, fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 700 }}>Interpretación del score para {periodLabel(period)}</div>
                                <div style={{ display: 'grid', gap: 8 }}>
                                    {[
                                        { rango: '81–100', nivel: 'CRÍTICO', desc: 'Alta probabilidad de reparo por Hacienda. Acción inmediata.', color: '#dc2626' },
                                        { rango: '61–80', nivel: 'EN RIESGO', desc: 'Exposición relevante. Corrección urgente antes del día 10.', color: '#ea580c' },
                                        { rango: '31–60', nivel: 'MODERADO', desc: 'Hay observaciones. Se recomienda corregir antes del cierre.', color: '#d97706' },
                                        { rango: '0–30', nivel: 'SALUDABLE', desc: 'Situación bajo control. Riesgo mínimo.', color: '#16a34a' },
                                    ].map(row => (
                                        <div key={row.nivel} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '10px 14px', borderRadius: 8 }}>
                                            <span style={{ fontSize: '0.75rem', fontWeight: 800, color: row.color, minWidth: 44 }}>{row.rango}</span>
                                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: row.color, minWidth: 90 }}>{row.nivel}</span>
                                            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{row.desc}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {tab === 'tabla' && (
                    /* ── Tabla CON_FE / SIN_FE por sesión ────────────────────── */
                    <div style={{ padding: '20px' }}>
                        <div style={{ marginBottom: 12, font: '0.82rem/1.4 inherit', color: 'var(--text-muted)' }}>
                            Resultado de conciliación: cada transacción del PDF con su estado fiscal.
                            <strong style={{ color: '#16a34a' }}> CON_FE</strong> = comprobante verificado ·
                            <strong style={{ color: '#dc2626' }}> SIN_FE</strong> = riesgo fiscal
                        </div>
                        {sesionTxns.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '28px', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
                                <div style={{ fontSize: '2rem', marginBottom: 8 }}>📄</div>
                                Corra CENTINELA desde la conciliación bancaria para ver los resultados aquí.
                            </div>
                        ) : (
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                                    <thead>
                                        <tr style={{ background: 'var(--bg-secondary)', fontSize: '0.7rem' }}>
                                            <th style={{ padding: '6px 10px', textAlign: 'left' }}>Fecha</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'left' }}>Descripción</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'right' }}>Monto</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'center' }}>FE</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'center' }}>Tarifa</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'right' }}>IVA est.</th>
                                            <th style={{ padding: '6px 10px', textAlign: 'center' }}>Estado</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {sesionTxns.map((t, i) => {
                                            const conFE = t.match_estado === 'CON_FE'
                                            return (
                                                <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)05' }}>
                                                    <td style={{ padding: '6px 10px', color: 'var(--text-muted)' }}>{String(t.fecha || '').slice(0, 10)}</td>
                                                    <td style={{ padding: '6px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.descripcion}>{t.descripcion}</td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 600 }}>{formatCRC(t.monto)}</td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                                        <span style={{ fontSize: '0.7rem', fontWeight: 700, padding: '2px 7px', borderRadius: 5, background: conFE ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.12)', color: conFE ? '#16a34a' : '#dc2626' }}>
                                                            {conFE ? 'SI' : 'NO'}
                                                        </span>
                                                    </td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>{t.tarifa_iva ?? '—'}%</td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'right', color: t.iva_estimado > 0 ? '#dc2626' : 'var(--text-muted)' }}>{t.iva_estimado > 0 ? formatCRC(t.iva_estimado) : '—'}</td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                                        <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: 5, background: conFE ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.1)', color: conFE ? '#16a34a' : '#dc2626' }}>
                                                            {t.match_estado}
                                                        </span>
                                                    </td>
                                                </tr>
                                            )
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {tab === 'fugas' && (
                    <div style={{ padding: '20px' }}>
                        {fugas.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '28px', color: 'var(--text-muted)' }}>
                                <div style={{ fontSize: '2rem', marginBottom: 8 }}>✅</div>
                                <div>Sin fugas detectadas en este período.</div>
                                <div style={{ fontSize: '0.78rem', marginTop: 6 }}>
                                    Los resultados aparecen después de correr el análisis CENTINELA.
                                </div>
                            </div>
                        ) : (
                            <>
                                <div style={{ marginBottom: 12, display: 'flex', gap: 12 }}>
                                    {[
                                        { tipo: 'A', label: 'Tipo A — Sin FE', count: fugas.filter(f => f.fuga_tipo === 'A').length, color: '#dc2626' },
                                        { tipo: 'B', label: 'Tipo B — Sin D-270', count: fugas.filter(f => f.fuga_tipo === 'B').length, color: '#d97706' },
                                        { tipo: 'C', label: 'Tipo C — SINPE cod.', count: fugas.filter(f => f.fuga_tipo === 'C').length, color: '#7c3aed' },
                                    ].map(it => (
                                        <div key={it.tipo} style={{
                                            fontSize: '0.75rem', fontWeight: 700, color: it.color,
                                            padding: '4px 10px', borderRadius: 6, background: `${it.color}15`,
                                        }}>
                                            {it.label}: {it.count}
                                        </div>
                                    ))}
                                </div>
                                {fugas.map((f, i) => <FugaCard key={i} fuga={f} index={i} />)}
                            </>
                        )}
                    </div>
                )}

                {tab === 'd270' && (
                    <div style={{ padding: '20px' }}>
                        <div style={{ marginBottom: 14, color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                            Registros pre-llenados automáticamente para presentar en la <strong>Declaración Informativa D-270</strong>.
                            Estos son los gastos del período sin comprobante electrónico.
                        </div>
                        <D270Preview
                            items={d270?.items || []}
                            resumen={d270?.resumen}
                            period={period}
                            token={token}
                        />
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Estilos ── */
const inputStyle = {
    background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 7,
    padding: '7px 10px', color: 'var(--text-primary)', fontSize: '0.85rem',
    outline: 'none', width: '100%', boxSizing: 'border-box',
}
const btnChoice = {
    border: '1px solid var(--border)', borderRadius: 8, padding: '7px 14px',
    fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
}
const cardStyle = {
    background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 14, overflow: 'hidden',
}
