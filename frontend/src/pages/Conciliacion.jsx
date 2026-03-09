import { useState, useEffect, useCallback, useRef } from 'react'
import { useApp } from '../context/AppContext'

const API = import.meta.env.VITE_API_URL || ''
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

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
    CONCILIADO: { bg: 'rgba(34,197,94,0.12)', color: '#16a34a', label: '✅ Conciliado' },
    PROBABLE: { bg: 'rgba(251,191,36,0.15)', color: '#d97706', label: '🟡 Probable' },
    SIN_ASIENTO: { bg: 'rgba(239,68,68,0.12)', color: '#dc2626', label: '🔴 Sin asiento' },
    SOLO_LIBROS: { bg: 'rgba(139,92,246,0.12)', color: '#7c3aed', label: '🟣 Solo libros' },
    PENDIENTE: { bg: 'rgba(148,163,184,0.15)', color: '#64748b', label: '⏳ Pendiente' },
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
        { k: 'CONCILIADO', label: '✅ Conciliados', color: '#16a34a' },
        { k: 'PROBABLE', label: '🟡 Probables', color: '#d97706' },
        { k: 'SIN_ASIENTO', label: '🔴 Sin asiento', color: '#dc2626' },
    ]

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
                                    {t.match_estado === 'SIN_ASIENTO' && (
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
function StatsBar({ stats, saldoDiff }) {
    if (!stats) return null
    const items = [
        { label: 'Total banco', value: stats.total_banco, color: 'var(--text-primary)' },
        { label: 'Conciliados', value: stats.conciliados, color: '#16a34a' },
        { label: 'Probables', value: stats.probables, color: '#d97706' },
        { label: 'Sin asiento', value: stats.sin_asiento, color: '#dc2626' },
        { label: 'Solo libros', value: stats.solo_libros, color: '#7c3aed' },
    ]
    return (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            {items.map(it => (
                <div key={it.label} style={{
                    flex: 1, minWidth: 100, background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px', textAlign: 'center',
                }}>
                    <div style={{ fontSize: '1.6rem', fontWeight: 800, color: it.color }}>{it.value}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>{it.label}</div>
                </div>
            ))}
            {saldoDiff && (
                <div style={{
                    flex: 2, minWidth: 200, background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 10, padding: '12px 16px',
                }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>Diferencia saldo</div>
                    <div style={{ fontWeight: 700, color: saldoDiff.estado === 'CUADRADO' ? '#16a34a' : '#dc2626' }}>
                        {saldoDiff.observacion}
                    </div>
                </div>
            )}
        </div>
    )
}

/* ── Upload de archivo ───────────────────────────────────────────────── */
function FileUploader({ token, onTransacciones }) {
    const [banco, setBanco] = useState('')
    const [period, setPeriod] = useState(currentPeriod())
    const [entidades, setEntidades] = useState([])
    const [file, setFile] = useState(null)
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
        const f = e.target.files?.[0]
        if (!f) return
        setFile(f)
        setMsg(null)
    }

    async function parsear() {
        if (!file || !banco) {
            setMsg({ ok: false, text: 'Selecciona banco y archivo' })
            return
        }
        setLoading(true); setMsg(null)
        try {
            if (file.name.endsWith('.csv') || file.name.endsWith('.txt')) {
                const text = await file.text()
                const r = await fetch(`${API}/conciliacion/parse`, {
                    method: 'POST',
                    headers: authJ(token),
                    body: JSON.stringify({ text, banco }),
                })
                const d = await r.json()
                if (r.ok) {
                    setMsg({ ok: true, text: `${d.total_transacciones} transacciones parseadas de ${banco}` })
                    onTransacciones(d.transacciones, banco, period, d.saldo_inicial, d.saldo_final)
                } else {
                    setMsg({ ok: false, text: d.detail || 'Error al parsear' })
                }
            } else {
                // Excel o PDF — enviar como FormData (implementación futura directa)
                setMsg({ ok: true, text: `Archivo ${file.name} cargado — procesando...` })
            }
        } catch (e) { setMsg({ ok: false, text: String(e) }) }
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
                    onChange={e => setPeriod(e.target.value)}
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

            {/* Archivo */}
            <div>
                <label style={labelStyle}>Estado de cuenta</label>
                <div style={{
                    border: '2px dashed var(--border)', borderRadius: 10,
                    padding: '18px', textAlign: 'center', cursor: 'pointer',
                    background: file ? 'rgba(34,197,94,0.05)' : 'var(--bg-secondary)',
                    transition: 'all 0.2s',
                }} onClick={() => fileRef.current?.click()}>
                    <div style={{ fontSize: '1.5rem', marginBottom: 4 }}>
                        {file ? '📄' : '📂'}
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        {file ? file.name : 'CSV, XLSX o PDF'}
                    </div>
                    {file && (
                        <div style={{ fontSize: '0.7rem', color: '#16a34a', marginTop: 2 }}>
                            {(file.size / 1024).toFixed(1)} KB
                        </div>
                    )}
                </div>
                <input ref={fileRef} type="file" accept=".csv,.txt,.xlsx,.xls,.pdf" style={{ display: 'none' }}
                    onChange={handleFile} />
            </div>

            {/* Botón + mensaje */}
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: 8 }}>
                <button onClick={parsear} disabled={loading || !file || !banco} style={btnPrimary}>
                    {loading ? '⏳ Procesando...' : '🏦 Parsear estado de cuenta'}
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

    const [txns, setTxns] = useState([])
    const [reconId, setReconId] = useState(null)
    const [stats, setStats] = useState(null)
    const [saldoDiff, setSaldoDiff] = useState(null)
    const [matching, setMatching] = useState(false)
    const [matchMsg, setMatchMsg] = useState(null)
    const [step, setStep] = useState('upload') // upload | review | done

    function handleTransacciones(data, banco, period, saldoIni, saldoFin) {
        setTxns(data.map((t, i) => ({ ...t, id: t.id || `tmp_${i}`, match_estado: 'PENDIENTE' })))
        setStep('review')
        setReconId(null)
        setStats(null)
        setSaldoDiff(null)
    }

    async function runMatch() {
        if (!reconId) {
            setMatchMsg({ ok: false, text: 'Guarda las transacciones primero' })
            return
        }
        setMatching(true); setMatchMsg(null)
        try {
            const r = await fetch(`${API}/conciliacion/match/${reconId}`, {
                method: 'POST', headers: authH(token)
            })
            const d = await r.json()
            if (r.ok) {
                setStats(d.stats)
                setSaldoDiff(d.saldo_diff)
                setStep('done')
                setMatchMsg({ ok: true, text: `Matching completado — ${d.stats.conciliados} conciliados` })
            } else {
                setMatchMsg({ ok: false, text: d.detail || 'Error en matching' })
            }
        } catch (e) { setMatchMsg({ ok: false, text: String(e) }) }
        setMatching(false)
    }

    function handleApprove(txn) {
        // Abre modal de asiento — fase siguiente
        alert(`Crear asiento para: ${txn.descripcion}\nMonto: ${formatCRC(txn.monto)}`)
    }

    const porcentajeConciliado = stats
        ? Math.round((stats.conciliados / Math.max(stats.total_banco, 1)) * 100)
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
                {step !== 'upload' && (
                    <button onClick={() => { setStep('upload'); setTxns([]); setStats(null) }} style={btnSecondary}>
                        ↩ Nueva conciliación
                    </button>
                )}
            </div>

            {/* Steps indicator */}
            <div style={{ display: 'flex', gap: 0, marginBottom: 24, background: 'var(--bg-card)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {[
                    { k: 'upload', n: 1, label: 'Cargar archivo' },
                    { k: 'review', n: 2, label: 'Revisar transacciones' },
                    { k: 'done', n: 3, label: 'Resultado conciliación' },
                ].map((s, i, arr) => (
                    <div key={s.k} style={{
                        flex: 1, padding: '10px 16px', textAlign: 'center',
                        background: step === s.k ? 'var(--accent)' : 'transparent',
                        color: step === s.k ? '#fff' : 'var(--text-muted)',
                        fontSize: '0.8rem', fontWeight: step === s.k ? 700 : 400,
                        borderRight: i < arr.length - 1 ? '1px solid var(--border)' : 'none',
                        transition: 'all 0.2s',
                    }}>
                        <span style={{ opacity: 0.7, marginRight: 6 }}>{s.n}.</span>{s.label}
                    </div>
                ))}
            </div>

            {/* PASO 1: Cargar */}
            {step === 'upload' && (
                <div style={cardStyle}>
                    <div style={cardHeader}>📂 Paso 1 — Cargar estado de cuenta</div>
                    <div style={{ padding: '20px 24px' }}>
                        <FileUploader token={token} onTransacciones={handleTransacciones} />
                        <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--bg-secondary)', borderRadius: 10, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                            💡 <strong>Formatos aceptados:</strong> CSV (BAC, BCR, cooperativas) · Excel XLSX (BN Virtual) · PDF — El sistema detecta el banco automáticamente por el formato del archivo.
                        </div>
                    </div>
                </div>
            )}

            {/* PASO 2: Revisar */}
            {step === 'review' && (
                <div style={cardStyle}>
                    <div style={{ ...cardHeader, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span>📋 Paso 2 — Revisar {txns.length} transacciones</span>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            {matchMsg && (
                                <span style={{ fontSize: '0.78rem', color: matchMsg.ok ? '#16a34a' : '#dc2626' }}>
                                    {matchMsg.text}
                                </span>
                            )}
                            <button onClick={runMatch} disabled={matching} style={btnPrimary}>
                                {matching ? '⏳ Analizando...' : '⚖️ Conciliar vs Libro Diario'}
                            </button>
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

                    <StatsBar stats={stats} saldoDiff={saldoDiff} />

                    <div style={cardStyle}>
                        <div style={{ ...cardHeader, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span>📋 Detalle de transacciones</span>
                            <a
                                href={reconId ? `${API}/centinela/analyze/${reconId}` : '#'}
                                style={{ ...btnAccent, textDecoration: 'none', fontSize: '0.8rem', padding: '5px 14px' }}
                            >
                                🛡️ Analizar con CENTINELA
                            </a>
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
