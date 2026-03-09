import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useApp } from '../context/AppContext'
import * as pdfjsLib from 'pdfjs-dist'

// Worker de pdf.js — debe apuntar al archivo del paquete instalado
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url
).href

const API = import.meta.env.VITE_API_URL || ''
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

/* ── Estado del período post-cierre ───────────────────────────────── */
function getPeriodStatus(period) {
    if (!period || period.length < 6) return 'DESCONOCIDO'
    const year = parseInt(period.slice(0, 4))
    const month = parseInt(period.slice(4, 6))
    if (isNaN(year) || isNaN(month)) return 'DESCONOCIDO'
    const today = new Date()
    const curY = today.getFullYear()
    const curM = today.getMonth() + 1
    const curD = today.getDate()
    if (year > curY || (year === curY && month > curM)) return 'FUTURO'
    if (year === curY && month === curM) return 'ABIERTO'
    const diff = (curY - year) * 12 + (curM - month)
    if (diff === 1 && curD <= 10) return 'RECIENTE'  // D-270 aún en plazo
    return 'CERRADO'
}

const PERIOD_BANNER = {
    FUTURO: {
        bg: 'rgba(148,163,184,0.12)', border: '#94a3b8', color: '#475569',
        emoji: '📅',
        titulo: 'Período futuro',
        texto: 'Este período aún no ha iniciado. Puedes preparar la conciliación con anticipación.',
        acciones: [],
    },
    ABIERTO: {
        bg: 'rgba(34,197,94,0.08)', border: '#16a34a', color: '#15803d',
        emoji: '🟢',
        titulo: 'Período abierto — Ventana óptima',
        texto: 'Estás en el momento ideal. Podés emitir FE faltantes, crear asientos y corregir todo antes del cierre.',
        acciones: ['✅ Emitir FE faltantes (aún en período corriente)', '✅ Crear asientos correctivos', '✅ Configurar Bank Rules para el futuro'],
    },
    RECIENTE: {
        bg: 'rgba(251,191,36,0.10)', border: '#d97706', color: '#b45309',
        emoji: '🟡',
        titulo: 'Período cerrado — D-270 aún en plazo',
        texto: 'El mes ya cerró pero el plazo para presentar la D-270 no ha vencido (día 10 del mes siguiente).',
        acciones: ['✅ Ver score CENTINELA (solo lectura)', '✅ Exportar D-270 → subir a Tribu-CR ANTES del día 10', '⚠️ Emitir FE extemporánea previo análisis con tu contador', '❌ No se pueden agregar asientos al período cerrado'],
    },
    CERRADO: {
        bg: 'rgba(239,68,68,0.08)', border: '#dc2626', color: '#b91c1c',
        emoji: '🔴',
        titulo: 'Período cerrado — Revisión preventiva',
        texto: 'El período está cerrado y el plazo D-270 venció. Esta revisión es preventiva para identificar patrones y corregir en el período actual.',
        acciones: ['✅ Score CENTINELA como referencia histórica', '✅ Identificar patrones para NO repetir', '⚠️ FE extemporánea posible con multa (consultar norma)', '❌ D-270 fuera de plazo ordinario — aplica D-270 extemporánea'],
    },
    DESCONOCIDO: {
        bg: 'var(--bg-secondary)', border: 'var(--border)', color: 'var(--text-muted)',
        emoji: 'ℹ️', titulo: 'Ingresa un período válido', texto: 'Escribe el período en formato YYYYMM (ej: 202601 = enero 2026).', acciones: [],
    },
}

function PeriodBanner({ period }) {
    const [open, setOpen] = React.useState(true)
    const status = getPeriodStatus(period)
    const cfg = PERIOD_BANNER[status] || PERIOD_BANNER.DESCONOCIDO
    if (status === 'ABIERTO' && !open) return null
    return (
        <div style={{
            border: `1px solid ${cfg.border}40`,
            background: cfg.bg, borderRadius: 10,
            padding: '12px 16px', marginBottom: 18,
            display: 'flex', gap: 12, alignItems: 'flex-start',
        }}>
            <div style={{ fontSize: '1.3rem', flexShrink: 0 }}>{cfg.emoji}</div>
            <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', color: cfg.color, marginBottom: 3 }}>
                    {cfg.titulo}
                </div>
                <div style={{ fontSize: '0.78rem', color: cfg.color, opacity: 0.85, marginBottom: cfg.acciones.length ? 8 : 0 }}>
                    {cfg.texto}
                </div>
                {cfg.acciones.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.75rem', color: cfg.color, opacity: 0.8 }}>
                        {cfg.acciones.map((a, i) => <li key={i} style={{ marginBottom: 2 }}>{a}</li>)}
                    </ul>
                )}
            </div>
            <button onClick={() => setOpen(false)} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: cfg.color, fontSize: '1rem', opacity: 0.5, flexShrink: 0, padding: 0,
            }}>✕</button>
        </div>
    )
}

function authH(token) {
    return { Authorization: `Bearer ${token}` }
}
function authJ(token) {
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
}
function formatCRC(n) {
    if (n == null || isNaN(n)) return '₡0'
    return '₡' + Number(n).toLocaleString('es-CR', { minimumFractionDigits: 0 })
}
function currentPeriod() {
    const d = new Date()
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}

/* ── Semáforo de estado ──────────────────────────────────────────────── */
const ESTADO_COLOR = {
    // V2 (actuales)
    CON_FE: { bg: 'rgba(34,197,94,0.12)', color: '#16a34a', label: '✅ CON FE' },
    SIN_FE: { bg: 'rgba(239,68,68,0.12)', color: '#dc2626', label: '🔴 SIN FE' },
    PROBABLE: { bg: 'rgba(251,191,36,0.15)', color: '#d97706', label: '🟡 Probable' },
    SOLO_LIBROS: { bg: 'rgba(139,92,246,0.12)', color: '#7c3aed', label: '📚 Solo libros' },
    PENDIENTE: { bg: 'rgba(148,163,184,0.15)', color: '#64748b', label: '⏳ Pendiente' },
    // V1 (sesiones antiguas)
    CONCILIADO: { bg: 'rgba(34,197,94,0.12)', color: '#16a34a', label: '✅ Conciliado' },
    SIN_ASIENTO: { bg: 'rgba(239,68,68,0.12)', color: '#dc2626', label: '🔴 Sin asiento' },
    SIN_MATCH: { bg: 'rgba(148,163,184,0.15)', color: '#64748b', label: '⏳ Sin match' },
}
function Badge({ estado }) {
    const cfg = ESTADO_COLOR[estado] || ESTADO_COLOR.PENDIENTE
    return (
        <span style={{
            fontSize: '0.72rem', fontWeight: 700, padding: '3px 8px',
            borderRadius: 20, background: cfg.bg, color: cfg.color,
            whiteSpace: 'nowrap',
        }}>
            {cfg.label}
        </span>
    )
}

/* ── Tabla de transacciones ──────────────────────────────────────────── */
function TxnTable({ txns, onApprove }) {
    const [filter, setFilter] = useState('TODOS')

    const filtered = filter === 'TODOS' ? txns
        : txns.filter(t => t.match_estado === filter || (!t.match_estado && filter === 'PENDIENTE'))

    const tabs = [
        { k: 'TODOS', label: 'Todos', color: 'var(--text-secondary)' },
        { k: 'CON_FE', label: '✅ CON FE', color: '#16a34a' },
        { k: 'SIN_FE', label: '🔴 SIN FE', color: '#dc2626' },
        { k: 'PROBABLE', label: '🟡 Probable', color: '#d97706' },
        // V1 compat
        { k: 'CONCILIADO', label: '✅ Conciliados (v1)', color: '#16a34a' },
        { k: 'SIN_ASIENTO', label: '🔴 Sin asiento (v1)', color: '#dc2626' },
    ].filter(t => t.k === 'TODOS' || txns.some(tx => tx.match_estado === t.k))

    return (
        <div>
            {/* Pestañas */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                {tabs.map(t => (
                    <button key={t.k} onClick={() => setFilter(t.k)} style={{
                        ...btnChoice,
                        background: filter === t.k ? 'var(--bg-3)' : 'transparent',
                        color: filter === t.k ? t.color : 'var(--text-muted)',
                        borderColor: filter === t.k ? t.color : 'transparent',
                        fontSize: '0.78rem',
                    }}>
                        {t.label}
                        <span style={{ marginLeft: 5, opacity: 0.7 }}>
                            ({txns.filter(tx => t.k === 'TODOS' || tx.match_estado === t.k).length})
                        </span>
                    </button>
                ))}
            </div>

            {/* Tabla */}
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                    <thead>
                        <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                            <th style={th}>Fecha</th>
                            <th style={th}>Descripción</th>
                            <th style={{ ...th, textAlign: 'right' }}>Monto</th>
                            <th style={th}>Moneda</th>
                            <th style={th}>Tel.</th>
                            <th style={th}>Estado</th>
                            <th style={th}>Conf.</th>
                            <th style={th}>Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.length === 0 ? (
                            <tr>
                                <td colSpan={8} style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)' }}>
                                    Sin transacciones en esta categoría
                                </td>
                            </tr>
                        ) : filtered.map((t, i) => (
                            <tr key={t.id || i} style={{
                                borderBottom: '1px solid var(--border)',
                                background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)',
                            }}>
                                <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                                    {t.fecha}
                                </td>
                                <td style={{ ...td, maxWidth: 280 }}>
                                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {t.descripcion}
                                    </div>
                                    {t.fuga_tipo && (
                                        <div style={{ fontSize: '0.7rem', color: '#dc2626', marginTop: 2 }}>
                                            ⚠️ Fuga tipo {t.fuga_tipo}
                                        </div>
                                    )}
                                </td>
                                <td style={{ ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                                    <span style={{ color: t.tipo === 'CR' ? '#16a34a' : '#dc2626' }}>
                                        {t.tipo === 'CR' ? '+' : '-'}{formatCRC(t.monto_crc || t.monto)}
                                    </span>
                                    {t.monto_orig_usd && (
                                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                            ${t.monto_orig_usd} @{t.tc_bccr}
                                        </div>
                                    )}
                                </td>
                                <td style={{ ...td, textAlign: 'center' }}>
                                    <span style={{
                                        fontSize: '0.72rem', padding: '2px 6px', borderRadius: 4,
                                        background: t.moneda === 'USD' ? 'rgba(59,130,246,0.15)' : 'transparent',
                                        color: t.moneda === 'USD' ? '#3b82f6' : 'var(--text-muted)',
                                    }}>
                                        {t.moneda || 'CRC'}
                                    </span>
                                </td>
                                <td style={{ ...td, color: '#7c3aed', fontSize: '0.75rem' }}>
                                    {t.telefono && `📞 ${t.telefono}`}
                                </td>
                                <td style={td}>
                                    <Badge estado={t.match_estado || 'PENDIENTE'} />
                                </td>
                                <td style={{ ...td, textAlign: 'center' }}>
                                    {t.match_confianza > 0 && (
                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                            {t.match_confianza}%
                                        </span>
                                    )}
                                </td>
                                <td style={td}>
                                    {(t.match_estado === 'SIN_FE' || t.match_estado === 'SIN_ASIENTO') && (
                                        <button
                                            onClick={() => onApprove(t)}
                                            style={{ ...btnPrimary, fontSize: '0.72rem', padding: '3px 8px' }}
                                        >
                                            + Asiento
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

/* ── Estadísticas de la conciliación ────────────────────────────────── */
function StatsBar({ stats, saldoDiff, txns = [] }) {
    if (!stats) return null

    const [open, setOpen] = useState(null) // key del popoever abierto

    // Mapa de qué transacciones muestra cada card
    const TXN_FILTER = {
        'Total banco': () => txns,
        '✅ CON FE': t => t.match_estado === 'CON_FE' || t.match_estado === 'CONCILIADO',
        '🔴 SIN FE': t => t.match_estado === 'SIN_FE' || t.match_estado === 'SIN_ASIENTO',
        '🟡 Probable': t => t.match_estado === 'PROBABLE',
        '📚 Solo libros': () => [], // vienen del backend, no están en txns
    }

    const items = [
        { label: 'Total banco', value: stats.total_banco, color: 'var(--text-primary)' },
        { label: '✅ CON FE', value: stats.con_fe ?? stats.conciliados ?? 0, color: '#16a34a' },
        { label: '🔴 SIN FE', value: stats.sin_fe ?? stats.sin_asiento ?? 0, color: '#dc2626' },
        { label: '🟡 Probable', value: stats.probable ?? stats.probables ?? 0, color: '#d97706' },
        { label: '📚 Solo libros', value: stats.solo_libros ?? 0, color: '#7c3aed' },
    ]

    function toggleCard(label) {
        setOpen(p => p === label ? null : label)
    }

    // Cerrar al clicar fuera
    useEffect(() => {
        if (!open) return
        const close = () => setOpen(null)
        document.addEventListener('click', close)
        return () => document.removeEventListener('click', close)
    }, [open])

    return (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            {items.map(it => {
                const filterFn = TXN_FILTER[it.label]
                const rows = typeof filterFn === 'function'
                    ? (it.label === 'Total banco' ? txns : txns.filter(filterFn))
                    : []
                const isOpen = open === it.label

                return (
                    <div key={it.label} style={{ flex: 1, minWidth: 100, position: 'relative' }}>
                        {/* Card clicable */}
                        <div
                            onClick={e => { e.stopPropagation(); toggleCard(it.label) }}
                            style={{
                                background: isOpen ? 'var(--bg-3)' : 'var(--bg-card)',
                                border: `1px solid ${isOpen ? it.color : 'var(--border)'}`,
                                borderRadius: 10, padding: '12px 16px', textAlign: 'center',
                                cursor: rows.length > 0 ? 'pointer' : 'default',
                                transition: 'all 0.15s',
                                userSelect: 'none',
                            }}
                        >
                            <div style={{ fontSize: '1.6rem', fontWeight: 800, color: it.color }}>
                                {it.value}
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                {it.label}
                            </div>
                            {rows.length > 0 && (
                                <div style={{ fontSize: '0.6rem', color: it.color, marginTop: 3, opacity: 0.75 }}>
                                    {isOpen ? '▲ cerrar' : '▼ ver detalle'}
                                </div>
                            )}
                        </div>

                        {/* Popover */}
                        {isOpen && rows.length > 0 && (
                            <div
                                onClick={e => e.stopPropagation()}
                                style={{
                                    position: 'absolute', top: 'calc(100% + 8px)', left: '50%',
                                    transform: 'translateX(-50%)',
                                    zIndex: 1000, minWidth: 320, maxWidth: 420,
                                    background: 'var(--bg-card)',
                                    border: `1px solid ${it.color}44`,
                                    borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
                                    overflow: 'hidden',
                                }}
                            >
                                {/* Header del popover */}
                                <div style={{
                                    padding: '8px 14px', background: `${it.color}15`,
                                    borderBottom: `1px solid ${it.color}33`,
                                    fontSize: '0.75rem', fontWeight: 700, color: it.color,
                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                }}>
                                    <span>{it.label} — {rows.length} transacciones</span>
                                    <button onClick={() => setOpen(null)} style={{
                                        background: 'none', border: 'none', color: it.color,
                                        cursor: 'pointer', fontSize: '0.9rem', padding: '0 4px',
                                    }}>✕</button>
                                </div>
                                {/* Lista de transacciones */}
                                <div style={{ maxHeight: 280, overflowY: 'auto' }}>
                                    {rows.slice(0, 20).map((t, i) => (
                                        <div key={t.id || i} style={{
                                            padding: '7px 14px',
                                            borderBottom: '1px solid var(--border)',
                                            display: 'flex', justifyContent: 'space-between',
                                            alignItems: 'center', gap: 8, fontSize: '0.75rem',
                                        }}>
                                            <div style={{ flex: 1, overflow: 'hidden' }}>
                                                <div style={{
                                                    color: 'var(--text-primary)',
                                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                }}>{t.descripcion}</div>
                                                <div style={{ color: 'var(--text-muted)', fontSize: '0.68rem', marginTop: 1 }}>
                                                    {t.fecha}
                                                    {t.fe_numero && <span style={{ marginLeft: 6, color: '#16a34a' }}>FE: {String(t.fe_numero).slice(0, 20)}</span>}
                                                    {t.fuga_tipo && <span style={{ marginLeft: 6, color: '#dc2626' }}>Tipo {t.fuga_tipo}</span>}
                                                </div>
                                            </div>
                                            <div style={{
                                                fontWeight: 700, whiteSpace: 'nowrap',
                                                color: t.tipo === 'CR' ? '#16a34a' : '#dc2626',
                                                fontSize: '0.78rem',
                                            }}>
                                                {t.tipo === 'CR' ? '+' : '-'}{formatCRC(t.monto_crc || t.monto)}
                                            </div>
                                        </div>
                                    ))}
                                    {rows.length > 20 && (
                                        <div style={{ padding: '7px 14px', fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                                            … y {rows.length - 20} más. Usa la tabla de abajo para ver todas.
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                )
            })}

            {saldoDiff && (
                <div style={{
                    flex: 2, minWidth: 200, background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px',
                }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                        Diferencia saldo
                        <div style={{ position: 'relative', display: 'inline-flex' }}
                            onMouseEnter={e => e.currentTarget.querySelector('.diff-tip').style.display = 'block'}
                            onMouseLeave={e => e.currentTarget.querySelector('.diff-tip').style.display = 'none'}
                        >
                            <span style={{ cursor: 'help', opacity: 0.65, fontSize: '0.85rem', lineHeight: 1 }}>💡</span>
                            <div className="diff-tip" style={{
                                display: 'none', position: 'absolute', bottom: '130%', left: '50%',
                                transform: 'translateX(-50%)', zIndex: 999,
                                background: '#1e293b', border: '1px solid rgba(148,163,184,0.2)',
                                borderRadius: 8, padding: '10px 13px', width: 270,
                                boxShadow: '0 8px 24px rgba(0,0,0,0.5)', fontSize: '0.72rem',
                                color: '#cbd5e1', lineHeight: 1.55, whiteSpace: 'normal',
                                pointerEvents: 'none',
                            }}>
                                <div style={{ fontWeight: 700, marginBottom: 6, color: '#e2e8f0' }}>¿Cómo se calcula?</div>
                                <div style={{ fontFamily: 'monospace', background: 'rgba(255,255,255,0.06)', borderRadius: 5, padding: '6px 8px', marginBottom: 7, fontSize: '0.7rem' }}>
                                    Diferencia = Banco − Libros
                                </div>
                                <div style={{ marginBottom: 4 }}>
                                    <span style={{ color: '#7dd3fc' }}>Banco:</span> saldo final reportado en el PDF del estado de cuenta.
                                </div>
                                <div style={{ marginBottom: 4 }}>
                                    <span style={{ color: '#86efac' }}>Libros:</span> SUM(créditos) − SUM(débitos) de los asientos contabilizados en la cuenta del período.
                                </div>
                                <div style={{ color: '#fca5a5', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 6, marginTop: 4, fontSize: '0.68rem' }}>
                                    Una diferencia distinta de ₡0 puede indicar: transacciones no registradas, errores de captura, o cheques pendientes de cobro (Solo Libros).
                                </div>
                            </div>
                        </div>
                    </div>
                    <div style={{ fontWeight: 700, color: saldoDiff.estado === 'CUADRADO' ? '#16a34a' : '#dc2626' }}>
                        {saldoDiff.observacion}
                    </div>
                </div>
            )}
        </div>
    )
}


/* ── Upload de archivo ───────────────────────────────────────────────── */
function FileUploader({ token, onTransacciones, onPeriodChange }) {
    const [banco, setBanco] = useState('')
    const [period, setPeriod] = useState(currentPeriod())
    const [entidades, setEntidades] = useState([])
    const [files, setFiles] = useState([])          // ← array multi-archivo
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState(null)
    const fileRef = useRef()

    useEffect(() => {
        fetch(`${API}/conciliacion/entidades`, { headers: authH(token) })
            .then(r => r.json())
            .then(d => {
                setEntidades(d.entidades || [])
                if (d.entidades?.length > 0) setBanco(d.entidades[0].clave)
            })
            .catch(() => { })
    }, [token])

    function handleFile(e) {
        const f = Array.from(e.target.files || [])
        if (!f.length) return
        setFiles(f)
        setMsg(null)
    }

    // Procesa UN archivo y retorna su resultado estándar
    async function parsearArchivo(file, idx, total) {
        const fname = file.name.toLowerCase()
        if (total > 1) {
            setMsg({ ok: true, text: `⏳ Procesando ${idx + 1}/${total}: ${file.name}` })
        }

        if (fname.endsWith('.csv') || fname.endsWith('.txt')) {
            const text = await file.text()
            const r = await fetch(`${API}/conciliacion/parse`, {
                method: 'POST',
                headers: authJ(token),
                body: JSON.stringify({ text, banco }),
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error CSV: ${file.name}`)
            return d
        }

        if (fname.endsWith('.pdf')) {
            // PDF → pdfplumber en el backend (tablas BN correctamente)
            // pdf.js client-side desordena columnas de tablas → 0 txns
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/parse-file`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error PDF: ${file.name}`)
            return d
        }

        if (fname.endsWith('.xlsx') || fname.endsWith('.xls')) {
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/parse-file`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error Excel: ${file.name}`)
            return d
        }

        if (fname.match(/\.(jpg|jpeg|png|webp)$/)) {
            const form = new FormData()
            form.append('file', file)
            form.append('banco', banco)
            const r = await fetch(`${API}/conciliacion/ocr-image`, {
                method: 'POST', headers: authH(token), body: form,
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail || `Error OCR: ${file.name}`)
            return d
        }

        throw new Error(`Formato no soportado: ${file.name}`)
    }

    async function parsear() {
        if (!files.length || !banco) {
            setMsg({ ok: false, text: 'Selecciona banco y al menos un archivo' })
            return
        }
        setLoading(true); setMsg(null)
        try {
            // Procesar todos los archivos secuencialmente
            let todosLasTxns = []
            let todosPeriodos = new Set()
            let saldoInicial = 0, saldoFinal = 0
            let usaGemini = false
            const errores = []

            for (let i = 0; i < files.length; i++) {
                try {
                    const d = await parsearArchivo(files[i], i, files.length)
                    todosLasTxns = todosLasTxns.concat(d.transacciones || [])
                        ; (d.periodos_detectados || []).forEach(p => todosPeriodos.add(p))
                    if (i === 0) saldoInicial = d.saldo_inicial || 0
                    saldoFinal = d.saldo_final || saldoFinal
                    if (d.fuente === 'gemini-vision') usaGemini = true
                } catch (err) {
                    errores.push(`${files[i].name}: ${err.message}`)
                }
            }

            // Deduplicar: misma fecha + mismo monto + misma descripción = duplicado
            const seen = new Set()
            const txnsFusionadas = todosLasTxns.filter(t => {
                const key = `${t.fecha}|${t.monto}|${t.descripcion?.slice(0, 60)}`
                if (seen.has(key)) return false
                seen.add(key)
                return true
            })

            // ── FIX 1: Filtrar SOLO el período seleccionado ──────────────────
            // El archivo del banco puede contener dic/ene/feb; solo pasan las del mes activo.
            const py = period.slice(0, 4)
            const pm = period.slice(4, 6)
            const periodPrefix = `${py}-${pm}`
            const txnsFiltradas = txnsFusionadas.filter(t =>
                (t.fecha || '').startsWith(periodPrefix)
            )
            const excluidas = txnsFusionadas.length - txnsFiltradas.length

            // Ordenar por fecha cronológicamente
            txnsFiltradas.sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''))

            const MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
            const mesLabel = (MESES_CORTOS[parseInt(pm) - 1] || pm) + ' ' + py
            const fuenteStr = usaGemini ? ' (OCR Gemini ✨)' : ''
            const errorStr = errores.length ? ` | ⚠️ ${errores.length} error(es)` : ''
            const exclStr = excluidas > 0 ? ` | ℹ️ ${excluidas} txn(s) de otros períodos excluidas` : ''

            if (txnsFiltradas.length === 0) {
                // 0 txns para el período: no avanzar al Paso 2
                const errMsg = errores.length
                    ? `Error procesando archivos: ${errores.join('; ')}`
                    : txnsFusionadas.length > 0
                        ? `⚠️ El archivo tiene ${txnsFusionadas.length} transacciones, pero ninguna es de ${mesLabel}. ` +
                        `Verifica el período seleccionado.`
                        : `⚠️ Se procesaron ${files.length} archivo(s) pero no se encontraron transacciones. ` +
                        `Verifica que el banco seleccionado (${banco}) coincide con el archivo cargado.`
                setMsg({ ok: false, text: errMsg })
            } else {
                setMsg({
                    ok: true,
                    text: `✅ ${txnsFiltradas.length} transacciones de ${mesLabel} | ${files.length} archivo(s)${fuenteStr}${exclStr}${errorStr}`,
                })
                onTransacciones(txnsFiltradas, banco, period, saldoInicial, saldoFinal)
            }


        } catch (e) {
            setMsg({ ok: false, text: String(e.message || e) })
        }
        setLoading(false)
    }

    const tipoEntidad = banco
        ? (entidades.find(e => e.clave === banco)?.tipo || '')
        : ''

    return (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            {/* Banco */}
            <div>
                <label style={labelStyle}>Entidad bancaria</label>
                <select value={banco} onChange={e => setBanco(e.target.value)} style={inputStyle}>
                    <optgroup label="── Estatales">
                        {entidades.filter(e => e.tipo === 'Estatal').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Privados">
                        {entidades.filter(e => e.tipo === 'Privado').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Cooperativas">
                        {entidades.filter(e => e.tipo === 'Cooperativa').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                    <optgroup label="── Financieras">
                        {entidades.filter(e => e.tipo === 'Financiera').map(e => (
                            <option key={e.clave} value={e.clave}>{e.nombre}</option>
                        ))}
                    </optgroup>
                </select>
                {tipoEntidad && (
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                        {tipoEntidad}
                    </div>
                )}
            </div>

            {/* Período */}
            <div>
                <label style={labelStyle}>Período (YYYYMM)</label>
                <input
                    type="text"
                    placeholder="202601"
                    value={period}
                    onChange={e => {
                        const v = e.target.value
                        setPeriod(v)
                        if (onPeriodChange && v.length === 6) onPeriodChange(v)
                    }}
                    maxLength={6}
                    style={inputStyle}
                />
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {period?.length === 6
                        ? `${MESES[parseInt(period.slice(4, 6)) - 1]} ${period.slice(0, 4)}`
                        : 'Ej: 202601 = enero 2026'
                    }
                </div>
            </div>

            {/* Archivo — drop zone multi-select */}
            <div>
                <label style={labelStyle}>Estado de cuenta</label>
                <div style={{
                    border: '2px dashed var(--border)', borderRadius: 10,
                    padding: '18px', textAlign: 'center', cursor: 'pointer',
                    background: files.length ? 'rgba(34,197,94,0.05)' : 'var(--bg-secondary)',
                    transition: 'all 0.2s',
                }} onClick={() => fileRef.current?.click()}>
                    <div style={{ fontSize: '1.5rem', marginBottom: 4 }}>
                        {files.length ? '📂' : '📂'}
                    </div>
                    {files.length === 0 ? (
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                            CSV, XLSX, PDF o imagen<br />
                            <span style={{ fontSize: '0.7rem', opacity: 0.7 }}>
                                Podés seleccionar varios a la vez
                            </span>
                        </div>
                    ) : (
                        <div style={{ textAlign: 'left', fontSize: '0.75rem' }}>
                            {files.map((f, i) => (
                                <div key={i} style={{ color: '#16a34a', marginBottom: 2 }}>
                                    📄 {f.name}
                                    <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
                                        ({(f.size / 1024).toFixed(0)} KB)
                                    </span>
                                </div>
                            ))}
                            <div style={{ marginTop: 6, fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                Clic para cambiar / agregar más
                            </div>
                        </div>
                    )}
                </div>
                <input ref={fileRef} type="file" multiple
                    accept=".csv,.txt,.xlsx,.xls,.pdf,.jpg,.jpeg,.png,.webp"
                    style={{ display: 'none' }}
                    onChange={handleFile} />
            </div>

            {/* Botón + mensaje */}
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: 8 }}>
                <button onClick={parsear} disabled={loading || !files.length || !banco} style={btnPrimary}>
                    {loading ? '⏳ Procesando...' : `🏦 Parsear${files.length > 1 ? ` ${files.length} archivos` : ' estado de cuenta'}`}
                </button>
                {msg && (
                    <div style={{
                        fontSize: '0.8rem', padding: '6px 10px', borderRadius: 7,
                        background: msg.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                        color: msg.ok ? '#16a34a' : '#dc2626',
                    }}>
                        {msg.text}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Página principal ────────────────────────────────────────────────── */
export default function Conciliacion() {
    const { state } = useApp()
    const token = state.token || localStorage.getItem('gc_token')

    // Datos de la sesión actual
    const [txns, setTxns] = useState([])
    const [bancoActual, setBancoActual] = useState('')
    const [saldoSesion, setSaldoSesion] = useState({ ini: 0, fin: 0 })
    const [reconId, setReconId] = useState(null)
    const [stats, setStats] = useState(null)
    const [saldoDiff, setSaldoDiff] = useState(null)
    const [centinelaScore, setCentinelaScore] = useState(null)
    const [centinelaConsolMsg, setCentinelaConsolMsg] = useState(null)
    const [centinelaLoading, setCentinelaLoading] = useState(false)
    const [matching, setMatching] = useState(false)
    const [matchMsg, setMatchMsg] = useState(null)
    const [step, setStep] = useState('upload') // upload | review | done
    const [period, setPeriodPage] = useState(currentPeriod())

    // Historial de sesiones pasadas
    const [historial, setHistorial] = useState([])
    const [historialExpanded, setHistorialExpanded] = useState(false)
    const [activeReconId, setActiveReconId] = useState(null)

    // Guardar sesión — selector de cuenta contable bancaria
    const [accountCode, setAccountCode] = useState('')
    const [cuentasBanco, setCuentasBanco] = useState([])
    const [saving, setSaving] = useState(false)
    const [saveMsg, setSaveMsg] = useState(null)

    // Cargar cuentas tipo ACTIVO al montar
    useEffect(() => {
        if (!token) return
        fetch(`${API}/ledger/accounts?account_type=ACTIVO`, { headers: authH(token) })
            .then(r => r.ok ? r.json() : [])
            .then(d => {
                const cuentas = Array.isArray(d) ? d : (d.accounts || d.items || [])
                setCuentasBanco(cuentas)
                const caja = cuentas.find(c => String(c.code || c.account_code || '').startsWith('1'))
                if (caja) setAccountCode(caja.code || caja.account_code || '')
            })
            .catch(() => setCuentasBanco([]))
    }, [token]) // eslint-disable-line

    // Cargar historial de sesiones pasadas al montar
    useEffect(() => {
        if (!token) return
        fetch(`${API}/conciliacion/sesiones`, { headers: authH(token) })
            .then(r => r.ok ? r.json() : { sesiones: [] })
            .then(d => {
                // Una pill por (period + account_code) — soporta multi-cuenta
                const vistas = new Set()
                const unicas = (d.sesiones || []).filter(s => {
                    const key = `${s.period}|${s.account_code || ''}`
                    if (!s.period || vistas.has(key)) return false
                    vistas.add(key)
                    return true
                })
                setHistorial(unicas)
            })
            .catch(() => { })
    }, [token]) // eslint-disable-line

    // Cargar una sesión pasada sin subir PDF
    async function loadSesion(recon_id) {
        try {
            const r = await fetch(`${API}/conciliacion/sesion/${recon_id}/detalle`, { headers: authH(token) })
            if (!r.ok) return
            const d = await r.json()
            const ses = d.sesion || {}
            setTxns(d.transacciones || [])
            setPeriodPage(ses.period ? `${ses.period.slice(0, 4)}${ses.period.slice(5, 7)}` : period)
            setBancoActual(ses.banco || '')
            setSaldoSesion({ ini: ses.saldo_inicial || 0, fin: ses.saldo_final || 0 })
            setReconId(recon_id)
            setActiveReconId(recon_id)
            setStats(null); setSaldoDiff(null); setCentinelaScore(null)
            setStep('done')
        } catch (_) { }
    }


    function handleTransacciones(data, banco, per, saldoIni, saldoFin) {
        setTxns(data.map((t, i) => ({ ...t, id: t.id || `tmp_${i}`, match_estado: 'PENDIENTE' })))
        if (per) setPeriodPage(per)
        setBancoActual(banco || '')
        setSaldoSesion({ ini: saldoIni || 0, fin: saldoFin || 0 })
        setStep('review')
        setReconId(null)
        setStats(null)
        setSaldoDiff(null)
        setCentinelaScore(null)
        setSaveMsg(null)
    }

    // ── FIX 3: Guardar sesión y transacciones ─────────────────────
    async function saveSesion() {
        if (!accountCode) {
            setSaveMsg({ ok: false, text: 'Selecciona la cuenta contable bancaria primero' })
            return
        }
        setSaving(true); setSaveMsg(null)
        try {
            // 1. Crear sesión
            const r1 = await fetch(`${API}/conciliacion/sesion`, {
                method: 'POST',
                headers: authJ(token),
                body: JSON.stringify({
                    banco: bancoActual,
                    period: period,
                    account_code: accountCode,
                    saldo_inicial: saldoSesion.ini,
                    saldo_final: saldoSesion.fin,
                }),
            })
            const d1 = await r1.json()
            if (!r1.ok) throw new Error(d1.detail || 'Error creando sesión')
            const rId = d1.recon_id

            // 2. Insertar transacciones en bulk
            const r2 = await fetch(`${API}/conciliacion/sesion/${rId}/transactions`, {
                method: 'POST',
                headers: authJ(token),
                body: JSON.stringify({
                    transactions: txns.map(t => ({
                        fecha: t.fecha,
                        descripcion: t.descripcion,
                        monto: t.monto,
                        tipo: t.tipo,
                        moneda: t.moneda || 'CRC',
                        telefono: t.telefono || null,
                        monto_orig_usd: t.monto_orig_usd || null,
                        tc_bccr: t.tc_bccr || null,
                    })),
                }),
            })
            const d2 = await r2.json()
            if (!r2.ok) throw new Error(d2.detail || 'Error guardando transacciones')

            setReconId(rId)
            setSaveMsg({ ok: true, text: `✅ ${d2.total_insertadas} transacciones guardadas. Listo para conciliar.` })
        } catch (e) {
            setSaveMsg({ ok: false, text: String(e.message || e) })
        }
        setSaving(false)
    }

    // ── FIX 4: Matching + auto-CENTINELA ─────────────────────────
    async function runMatch() {
        if (!reconId) {
            setMatchMsg({ ok: false, text: '💾 Guarda las transacciones primero (botón arriba)' })
            return
        }
        setMatching(true); setMatchMsg(null)
        try {
            // Match vs Libro Diario
            const r = await fetch(`${API}/conciliacion/match/${reconId}`, {
                method: 'POST', headers: authH(token)
            })
            const d = await r.json()
            if (r.ok) {
                setStats(d.stats)
                setSaldoDiff(d.saldo_diff)
                setStep('done')

                // ── Recargar transacciones para actualizar Estado/Conf./Acción ──
                // El backend actualizó match_estado en la DB — traemos el estado real
                try {
                    const rd = await fetch(`${API}/conciliacion/sesion/${reconId}/detalle`, {
                        headers: authH(token)
                    })
                    if (rd.ok) {
                        const dd = await rd.json()
                        if (Array.isArray(dd.transacciones) && dd.transacciones.length > 0) {
                            setTxns(dd.transacciones)
                        }
                    }
                } catch (_) { /* si falla la recarga, las txns siguen siendo las anteriores */ }

                // stats V2: con_fe, sin_fe, probable, total_banco
                const conFE = d.stats?.con_fe ?? d.stats?.conciliados ?? 0
                const sinFE = d.stats?.sin_fe ?? 0
                const total = d.stats?.total_banco ?? 0
                setMatchMsg({ ok: true, text: `✅ Conciliación completada — ${conFE} CON FE · ${sinFE} SIN FE · ${total} total` })

                // CENTINELA se corre manualmente por período completo (ver botón abajo)
                // Esto permite consolidar todas las cuentas antes del análisis fiscal
            } else {
                setMatchMsg({ ok: false, text: d.detail || `Error ${r.status} en matching` })
            }
        } catch (e) {
            setMatchMsg({ ok: false, text: `Error de conexión: ${String(e)}. ¿El servidor está corriendo?` })
        }
        setMatching(false)
    }

    // ── CENTINELA consolidado por período (todas las cuentas juntas) ──────────
    async function runCentinelaConsolidado() {
        if (!period) return
        setCentinelaLoading(true); setCentinelaConsolMsg(null)
        try {
            const r = await fetch(`${API}/centinela/analyze-period/${period}`, {
                method: 'POST', headers: authH(token)
            })
            const d = await r.json()
            if (r.ok) {
                setCentinelaScore(d.score)
                const cuentas = d.cuentas_analizadas || []
                const total = d.total_sin_fe ?? 0
                const score = d.score?.score_total ?? 0
                setCentinelaConsolMsg({
                    ok: true,
                    text: `🔬 Análisis completado — ${cuentas.length} cuenta(s) · ${total} SIN FE · Score ${score}/100`
                })
                // Recargar txns para que aparezca fuga_tipo e iva_estimado
                if (reconId) {
                    try {
                        const rd = await fetch(`${API}/conciliacion/sesion/${reconId}/detalle`, { headers: authH(token) })
                        if (rd.ok) {
                            const dd = await rd.json()
                            if (Array.isArray(dd.transacciones) && dd.transacciones.length > 0) {
                                setTxns(dd.transacciones)
                            }
                        }
                    } catch (_) { /* recarga silenciosa */ }
                }
            } else {
                setCentinelaConsolMsg({ ok: false, text: d.detail || `Error ${r.status}` })
            }
        } catch (e) {
            setCentinelaConsolMsg({ ok: false, text: `Error de conexión: ${String(e)}` })
        }
        setCentinelaLoading(false)
    }

    function handleApprove(txn) {
        alert(`Crear asiento para: ${txn.descripcion}\nMonto: ${formatCRC(txn.monto)}`)
    }

    const porcentajeConciliado = stats
        ? Math.round(((stats.con_fe ?? stats.conciliados ?? 0) / Math.max(stats.total_banco, 1)) * 100)
        : 0

    return (
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 20px' }}>

            {/* Header */}
            <div style={{ marginBottom: 24, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                        🏦 Conciliación Bancaria
                    </h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 5 }}>
                        Carga tu estado de cuenta (CSV, Excel o PDF) y compáralo automáticamente con el Libro Diario.
                    </p>
                </div>

                {/* Botones del header — igual patrón que Catálogo */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {step !== 'upload' && (
                        <button onClick={() => { setStep('upload'); setTxns([]); setStats(null) }} style={btnSecondary}>
                            ↩ Nueva conciliación
                        </button>
                    )}

                    {/* 💡 Tooltip Info — onMouseEnter/Leave, sin estado, igual al Catálogo */}
                    <div style={{ position: 'relative', display: 'inline-block' }}
                        onMouseEnter={e => e.currentTarget.querySelector('.recon-guide').style.display = 'block'}
                        onMouseLeave={e => e.currentTarget.querySelector('.recon-guide').style.display = 'none'}
                    >
                        <button style={{
                            background: 'transparent', border: '1px solid var(--border-color)',
                            borderRadius: 20, padding: '5px 10px', cursor: 'pointer',
                            color: 'var(--text-secondary)', fontSize: '0.82rem',
                            display: 'flex', alignItems: 'center', gap: 5,
                        }}>💡 Info</button>

                        <div className="recon-guide" style={{
                            display: 'none', position: 'absolute', right: 0, top: '110%', zIndex: 999,
                            background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                            borderRadius: 10, padding: '14px 16px', width: 340,
                            boxShadow: '0 8px 24px rgba(0,0,0,0.35)', fontSize: '0.78rem',
                        }}>
                            <p style={{ margin: '0 0 8px', fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                                💡 Guía de Conciliación
                            </p>

                            {/* Flujo de 3 pasos */}
                            <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-secondary)' }}>Flujo de 3 pasos:</p>
                            {[
                                ['📂', '1.', 'Carga el PDF, CSV o Excel del banco'],
                                ['🔗', '2.', 'Selecciona la cuenta contable del banco'],
                                ['✅', '3.', 'Guardar sesión → luego Conciliar'],
                            ].map(([ico, n, txt]) => (
                                <div key={n} style={{ display: 'flex', gap: 6, marginBottom: 4, alignItems: 'flex-start' }}>
                                    <span style={{ opacity: 0.6, minWidth: 18, fontSize: '0.72rem', paddingTop: 1 }}>{n}</span>
                                    <span style={{ fontSize: '0.9rem', flexShrink: 0 }}>{ico}</span>
                                    <span style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{txt}</span>
                                </div>
                            ))}

                            <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '10px 0' }} />

                            {/* Formatos */}
                            <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-secondary)' }}>Formatos aceptados:</p>
                            <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 10 }}>
                                <tbody>
                                    {[
                                        ['PDF', 'BNCR, BCR'],
                                        ['CSV', 'BAC, cooperativas'],
                                        ['Excel', 'BN Virtual'],
                                    ].map(([fmt, bancos]) => (
                                        <tr key={fmt} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                            <td style={{ padding: '3px 6px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '0.72rem' }}>{fmt}</td>
                                            <td style={{ padding: '3px 6px', color: 'var(--text-muted)' }}>{bancos}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>

                            <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '0 0 10px' }} />

                            {/* Estados */}
                            <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-secondary)' }}>Estados del resultado:</p>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                                {[
                                    ['CON_FE', '#16a34a', 'rgba(34,197,94,0.15)'],
                                    ['SIN_FE', '#dc2626', 'rgba(239,68,68,0.15)'],
                                    ['PENDIENTE', '#64748b', 'rgba(148,163,184,0.15)'],
                                ].map(([lbl, color, bg]) => (
                                    <span key={lbl} style={{
                                        fontSize: '0.7rem', fontWeight: 700, padding: '2px 8px',
                                        borderRadius: 5, background: bg, color,
                                    }}>{lbl}</span>
                                ))}
                            </div>

                            <p style={{ margin: 0, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                ⚡ CENTINELA se activa automáticamente al conciliar
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* ── Barra de historial de sesiones ───────────────────────── */}
            {historial.length > 0 && (
                <div style={{
                    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                    padding: '10px 14px', marginBottom: 16,
                    background: 'var(--bg-card)', borderRadius: 10,
                    border: '1px solid var(--border)',
                }}>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>
                        📚 Historial:
                    </span>

                    {(historialExpanded ? historial : historial.slice(0, 4)).map(ses => {
                        const isActive = ses.id === activeReconId
                        const pLabel = ses.period
                            ? `${['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Set', 'Oct', 'Nov', 'Dic'][parseInt(ses.period.slice(5, 7)) - 1]} ${ses.period.slice(0, 4)}`
                            : ses.id.slice(0, 6)
                        const scoreColor = !ses.score_riesgo ? '#64748b'
                            : ses.score_riesgo >= 80 ? '#16a34a'
                                : ses.score_riesgo >= 50 ? '#d97706'
                                    : '#dc2626'
                        return (
                            <button key={ses.id} onClick={() => loadSesion(ses.id)} style={{
                                padding: '4px 12px', borderRadius: 20, fontSize: '0.75rem',
                                fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
                                border: `1px solid ${isActive ? scoreColor : 'var(--border)'}`,
                                background: isActive ? `${scoreColor}22` : 'transparent',
                                color: isActive ? scoreColor : 'var(--text-secondary)',
                                transition: 'all 0.15s',
                            }}>
                                {pLabel}
                                {ses.n_con_fe != null && (
                                    <span style={{ marginLeft: 5, opacity: 0.75 }}>
                                        {ses.n_con_fe > 0 ? '✅' : '⚠️'}
                                    </span>
                                )}
                            </button>
                        )
                    })}

                    {historial.length > 4 && (
                        <button onClick={() => setHistorialExpanded(p => !p)} style={{
                            padding: '4px 10px', borderRadius: 20, fontSize: '0.72rem',
                            border: '1px solid var(--border)', background: 'transparent',
                            color: 'var(--text-muted)', cursor: 'pointer',
                        }}>
                            {historialExpanded ? 'Ver menos' : `+ ${historial.length - 4} más`}
                        </button>
                    )}
                </div>
            )}

            {/* Banner de estado del período */}
            <PeriodBanner period={period} />

            {/* Steps indicator */}
            <div style={{ display: 'flex', gap: 0, marginBottom: 24, background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {[
                    { k: 'upload', n: 1, icon: '📂', label: 'Cargar archivo', sub: 'Estado de cuenta bancario' },
                    { k: 'review', n: 2, icon: '🔗', label: 'Vincular & revisar', sub: 'Asignar cuenta contable' },
                    { k: 'done', n: 3, icon: '⚖️', label: 'Resultado conciliación', sub: 'Diferencias vs Libro Diario' },
                ].map((s, i, arr) => (
                    <div key={s.k} style={{
                        flex: 1, padding: '10px 16px', textAlign: 'center',
                        background: step === s.k ? 'var(--accent)' : 'transparent',
                        color: step === s.k ? '#fff' : 'var(--text-muted)',
                        borderRight: i < arr.length - 1 ? '1px solid var(--border)' : 'none',
                        transition: 'all 0.2s',
                    }}>
                        <div style={{ fontSize: '1rem', marginBottom: 2 }}>{s.icon}</div>
                        <div style={{ fontSize: '0.78rem', fontWeight: step === s.k ? 700 : 500 }}>
                            <span style={{ opacity: 0.6, marginRight: 4 }}>{s.n}.</span>{s.label}
                        </div>
                        <div style={{ fontSize: '0.68rem', opacity: 0.65, marginTop: 1 }}>{s.sub}</div>
                    </div>
                ))}
            </div>

            {/* PASO 1: Cargar */}
            {step === 'upload' && (
                <div style={cardStyle}>
                    <div style={cardHeader}>📂 Paso 1 — Cargar estado de cuenta</div>
                    <div style={{ padding: '20px 24px' }}>
                        <FileUploader token={token} onTransacciones={handleTransacciones} onPeriodChange={setPeriodPage} />
                        <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--bg-secondary)', borderRadius: 10, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            💡 <strong>Formatos aceptados:</strong> CSV (BAC, BCR, cooperativas) · Excel XLSX (BN Virtual) · PDF — El sistema detecta el banco automáticamente por el formato del archivo.
                        </div>
                    </div>
                </div>
            )}

            {/* PASO 2: Vincular & Conciliar */}
            {step === 'review' && (
                <div style={cardStyle}>
                    <div style={cardHeader}>
                        📋 Paso 2 — {txns.length} transacciones del banco listas para conciliar
                    </div>

                    {/* ── Sub-pasos A y B ───────────────────────────────────────── */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: reconId ? '1fr' : 'auto 1fr auto',
                        gap: 0,
                        borderBottom: '1px solid var(--border-color)',
                        background: reconId ? 'rgba(16,185,129,0.06)' : 'var(--bg-secondary)',
                    }}>

                        {/* ── A: Seleccionar cuenta contable ─────────────────────── */}
                        {!reconId && (
                            <div style={{
                                padding: '14px 20px',
                                borderRight: '1px solid var(--border-color)',
                                display: 'flex', flexDirection: 'column', gap: 6, minWidth: 280,
                            }}>
                                <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                    A  ·  ¿Cuál cuenta del Libro registra este banco?
                                </div>
                                <select
                                    value={accountCode}
                                    onChange={e => setAccountCode(e.target.value)}
                                    style={{ ...inputStyle }}
                                >
                                    {cuentasBanco.length === 0 && (
                                        <option value=''>Cargando cuentas...</option>
                                    )}
                                    {cuentasBanco.map(c => (
                                        <option key={c.code || c.account_code} value={c.code || c.account_code}>
                                            {c.code || c.account_code} — {c.name}
                                        </option>
                                    ))}
                                </select>
                                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                    Ej: 1101.01 Caja General · 1101.02 BAC Colones
                                </div>
                                {saveMsg && saveMsg.ok === false && (
                                    <div style={{ fontSize: '0.75rem', color: '#dc2626', marginTop: 2 }}>
                                        {saveMsg.text}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── Flecha central (solo cuando aún no hay sesión) ──────── */}
                        {!reconId && (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 12px', color: 'var(--text-muted)', fontSize: '1.2rem' }}>
                                →
                            </div>
                        )}

                        {/* ── B: Botones de acción ────────────────────────────────── */}
                        <div style={{
                            padding: '14px 20px',
                            display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'center',
                            flex: 1,
                        }}>
                            {reconId ? (
                                /* Sesión ya creada: mostrar resumen y botón conciliar */
                                <>
                                    <div style={{ fontSize: '0.82rem', color: '#16a34a', fontWeight: 700 }}>
                                        ✅ Sesión de conciliación registrada
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                        {txns.length} transacciones del banco · Cuenta: <strong>{accountCode}</strong>
                                    </div>
                                    <div>
                                        <button
                                            onClick={runMatch}
                                            disabled={matching}
                                            style={{ ...btnPrimary, marginTop: 4 }}
                                        >
                                            {matching ? '⏳ Analizando...' : '⚖️ Conciliar vs Libro Diario'}
                                        </button>
                                        {matchMsg && (
                                            <span style={{ marginLeft: 12, fontSize: '0.78rem', color: matchMsg.ok ? '#16a34a' : '#dc2626' }}>
                                                {matchMsg.text}
                                            </span>
                                        )}
                                    </div>
                                </>
                            ) : (
                                /* Aún no hay sesión: mostrar botón de guardar */
                                <>
                                    <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                        B  ·  Registrar & comparar contra el Libro
                                    </div>
                                    <button
                                        onClick={saveSesion}
                                        disabled={saving || !accountCode}
                                        style={{ ...btnPrimary, background: '#2563eb', alignSelf: 'flex-start' }}
                                    >
                                        {saving ? '⏳ Guardando...' : '🔗 Registrar sesión de conciliación'}
                                    </button>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                        Guarda las {txns.length} transacciones bancarias vinculadas a la cuenta {accountCode || '—'} para compararlas con el Libro Diario.
                                        <br />⚠️ <em>No crea asientos contables</em> — solo registra el estado de cuenta para el cruce.
                                    </div>
                                    <div style={{ marginTop: 4 }}>
                                        <button
                                            disabled
                                            style={{ ...btnPrimary, opacity: 0.35, cursor: 'not-allowed' }}
                                            title="Primero debes registrar la sesión (paso B)"
                                        >
                                            ⚖️ Conciliar vs Libro Diario
                                        </button>
                                        <span style={{ marginLeft: 8, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                            Se habilita después del paso B
                                        </span>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>

                    <div style={{ padding: '16px 20px' }}>
                        <TxnTable txns={txns} onApprove={handleApprove} />
                    </div>
                </div>
            )}

            {/* PASO 3: Resultado */}
            {step === 'done' && (
                <>
                    {/* Barra de progreso */}
                    <div style={{ ...cardStyle, marginBottom: 16, padding: '16px 20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 700 }}>Resultado de conciliación</span>
                            <span style={{ fontSize: '0.85rem', color: porcentajeConciliado >= 80 ? '#16a34a' : '#d97706', fontWeight: 700 }}>
                                {porcentajeConciliado}% conciliado
                            </span>
                        </div>
                        <div style={{ height: 10, background: 'var(--bg-secondary)', borderRadius: 20, overflow: 'hidden' }}>
                            <div style={{
                                height: '100%', width: `${porcentajeConciliado}%`,
                                background: porcentajeConciliado >= 80 ? 'linear-gradient(90deg,#16a34a,#22c55e)' : 'linear-gradient(90deg,#d97706,#f59e0b)',
                                borderRadius: 20, transition: 'width 0.8s ease',
                            }} />
                        </div>
                    </div>

                    <StatsBar stats={stats} saldoDiff={saldoDiff} txns={txns} />

                    {/* ── Botón CENTINELA consolidado por período ─────────── */}
                    <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                        <button
                            id="btn-centinela-period"
                            onClick={runCentinelaConsolidado}
                            disabled={centinelaLoading}
                            style={{
                                padding: '9px 20px', borderRadius: 10, fontWeight: 700,
                                fontSize: '0.875rem', cursor: centinelaLoading ? 'wait' : 'pointer',
                                background: centinelaLoading ? 'var(--bg-secondary)' : 'linear-gradient(135deg,#7c3aed,#6d28d9)',
                                color: '#fff', border: 'none',
                                boxShadow: '0 2px 8px rgba(124,58,237,0.25)',
                                display: 'flex', alignItems: 'center', gap: 7,
                            }}
                        >
                            {centinelaLoading ? '⏳ Analizando...' : '🔬 Analizar período completo'}
                        </button>
                        {centinelaConsolMsg && (
                            <span style={{
                                fontSize: '0.82rem', fontWeight: 600,
                                color: centinelaConsolMsg.ok ? '#16a34a' : '#dc2626',
                            }}>
                                {centinelaConsolMsg.text}
                            </span>
                        )}
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Consolida todas las cuentas del período {period}
                        </span>
                    </div>

                    {/* Score CENTINELA */}
                    {centinelaScore && (
                        <div style={{
                            ...cardStyle, marginBottom: 16, padding: '14px 20px',
                            background: centinelaScore.score_total >= 80 ? 'rgba(239,68,68,0.08)' : 'rgba(16,185,129,0.07)',
                            borderColor: centinelaScore.score_total >= 80 ? '#dc2626' : '#10b981',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                                <span style={{ fontWeight: 700, fontSize: '0.88rem' }}>🛡️ CENTINELA Fiscal</span>
                                <span style={{
                                    fontSize: '1.2rem', fontWeight: 800,
                                    color: centinelaScore.score_total >= 80 ? '#dc2626' : '#10b981',
                                }}>
                                    Score: {centinelaScore.score_total} / 100
                                </span>
                                {[['A', centinelaScore.fugas_tipo_a], ['B', centinelaScore.fugas_tipo_b], ['C', centinelaScore.fugas_tipo_c]].map(([tipo, n]) => n > 0 && (
                                    <span key={tipo} style={{ fontSize: '0.78rem', color: '#dc2626' }}>
                                        Fuga {tipo}: {n}
                                    </span>
                                ))}
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                                    Exposición IVA: ₡{Math.round(centinelaScore.exposicion_iva || 0).toLocaleString()}
                                </span>
                            </div>
                        </div>
                    )}

                    <div style={cardStyle}>
                        <div style={{ ...cardHeader, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span>📋 Detalle de transacciones</span>
                        </div>
                        <div style={{ padding: '16px 20px' }}>
                            <TxnTable txns={txns} onApprove={handleApprove} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

/* ── Estilos ─────── */
const inputStyle = {
    background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 7,
    padding: '7px 10px', color: 'var(--text-primary)', fontSize: '0.85rem',
    outline: 'none', width: '100%', boxSizing: 'border-box',
}
const labelStyle = {
    display: 'block', fontSize: '0.75rem', fontWeight: 600,
    color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em',
}
const btnPrimary = {
    background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 8,
    padding: '8px 18px', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer',
}
const btnSecondary = {
    background: 'var(--bg-3)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
    borderRadius: 8, padding: '7px 14px', fontSize: '0.83rem', fontWeight: 600, cursor: 'pointer',
}
const btnAccent = {
    background: 'linear-gradient(135deg,#f59e0b,#d97706)', color: '#fff', border: 'none',
    borderRadius: 8, padding: '7px 16px', fontSize: '0.83rem', fontWeight: 700, cursor: 'pointer',
}
const btnChoice = {
    border: '1px solid transparent', borderRadius: 8, padding: '5px 12px',
    fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
}
const cardStyle = {
    background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 14, overflow: 'hidden',
}
const cardHeader = {
    padding: '12px 20px', borderBottom: '1px solid var(--border-color)',
    fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-secondary)',
    background: 'var(--bg-secondary)',
}
const th = { padding: '8px 10px', textAlign: 'left', fontWeight: 600 }
const td = { padding: '8px 10px', color: 'var(--text-primary)' }
