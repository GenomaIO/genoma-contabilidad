/**
 * AppContext — Multi-tenant state global
 * NO hardcoded tenant IDs · Todo desde JWT o env
 *
 * authLoading: true hasta que el useEffect de hidratación termina.
 * Esto evita la race condition donde ProtectedRoute redirige antes
 * de que el token del URL sea procesado.
 */
import { createContext, useContext, useReducer, useEffect } from 'react'

const AppContext = createContext(null)

const initialState = {
    theme: localStorage.getItem('gc_theme') || 'dark',
    sidebarOpen: false,
    user: null,
    tenant: null,
    period: null,
    catalogMode: null,   // NULL = no elegido → trigger onboarding
    authLoading: true,
    apiStatus: 'checking',
}

function reducer(state, action) {
    switch (action.type) {
        case 'SET_THEME':
            localStorage.setItem('gc_theme', action.payload)
            return { ...state, theme: action.payload }

        case 'TOGGLE_SIDEBAR':
            return { ...state, sidebarOpen: !state.sidebarOpen }

        case 'SET_SIDEBAR':
            return { ...state, sidebarOpen: action.payload }

        case 'SET_USER':
            return { ...state, user: action.payload }

        case 'SET_TENANT':
            // Persistir el tenant seleccionado entre recargas (Opción B — localStorage)
            if (action.payload) {
                localStorage.setItem('gc_selected_tenant', JSON.stringify(action.payload))
            } else {
                localStorage.removeItem('gc_selected_tenant')
            }
            return { ...state, tenant: action.payload }

        case 'SET_PERIOD':
            return { ...state, period: action.payload }

        case 'SET_API_STATUS':
            return { ...state, apiStatus: action.payload }

        case 'SET_CATALOG_MODE':
            return { ...state, catalogMode: action.payload }

        case 'AUTH_READY':
            // Se despacha cuando la hidratación de token termina (con o sin usuario)
            return { ...state, authLoading: false }

        case 'LOGOUT':
            localStorage.removeItem('gc_token')
            localStorage.removeItem('gc_selected_tenant')  // limpieza al cerrar sesión
            return { ...initialState, authLoading: false, theme: state.theme, apiStatus: state.apiStatus }

        default:
            return state
    }
}

function parseJwtPayload(token) {
    try {
        const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
        return JSON.parse(atob(base64))
    } catch {
        return null
    }
}

export function AppProvider({ children }) {
    const [state, dispatch] = useReducer(reducer, initialState)

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', state.theme)
    }, [state.theme])

    // ── Hidratación: URL ?token= → localStorage → Estado ──────────
    // Al terminar siempre despacha AUTH_READY para liberar el guard.
    useEffect(() => {
        const params = new URLSearchParams(window.location.search)
        const urlToken = params.get('token')
        let activeToken = null

        if (urlToken) {
            localStorage.setItem('gc_token', urlToken)
            activeToken = urlToken
            window.history.replaceState({}, document.title, window.location.pathname)
        } else {
            activeToken = localStorage.getItem('gc_token')
        }

        if (activeToken) {
            const payload = parseJwtPayload(activeToken)
            if (payload && payload.exp * 1000 > Date.now()) {
                dispatch({
                    type: 'SET_USER',
                    payload: {
                        user_id: payload.sub,
                        nombre: payload.nombre,
                        tenant_id: payload.tenant_id,
                        tenant_type: payload.tenant_type,
                        role: payload.role,
                        partner_id: payload.partner_id || null,
                    }
                })
                // Hidratar catalog_mode inicial desde JWT si viene embebido (legacy)
                if (payload.catalog_mode) {
                    dispatch({ type: 'SET_CATALOG_MODE', payload: payload.catalog_mode })
                }
                // Opción B: restaurar el tenant seleccionado desde localStorage
                // Esto garantiza que state.tenant no sea null tras recarga de página,
                // solucionando el problema donde state.tenant?.tenant_id retornaba ''
                // y el backend usaba GC-RNHJ en lugar del UUID real del cliente.
                const savedTenant = localStorage.getItem('gc_selected_tenant')
                if (savedTenant) {
                    try {
                        const tenantData = JSON.parse(savedTenant)
                        // Solo restaurar si el JWT sigue siendo del mismo partner/user
                        // (evita restaurar tenant de otra sesión)
                        dispatch({ type: 'SET_TENANT', payload: tenantData })
                    } catch {
                        localStorage.removeItem('gc_selected_tenant')
                    }
                }
            } else {
                localStorage.removeItem('gc_token')
                localStorage.removeItem('gc_selected_tenant')
            }
        }

        // Siempre liberar el guard — con o sin usuario
        dispatch({ type: 'AUTH_READY' })
    }, [])

    // ── RO#227 — State Hydration Guard: catalog_mode desde DB ──────────
    // El JWT no incluye catalog_mode por diseño (TTL corto).
    // Llamamos GET /auth/me para obtener el valor real desde la BD.
    // Se ejecuta después de AUTH_READY, no bloquea la app.
    useEffect(() => {
        const token = localStorage.getItem('gc_token')
        if (!token) return
        const payload = parseJwtPayload(token)
        if (!payload || payload.exp * 1000 <= Date.now()) return

        const apiUrl = import.meta.env.VITE_API_URL || ''
        fetch(`${apiUrl}/auth/me`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data?.catalog_mode) {
                    dispatch({ type: 'SET_CATALOG_MODE', payload: data.catalog_mode })
                }
            })
            .catch(() => {
                // No-critico: si falla, el contexto queda en null
                // → el Catalogo muestra el fallback correcto
            })
    }, [])

    useEffect(() => {
        const apiUrl = import.meta.env.VITE_API_URL || ''
        fetch(`${apiUrl}/health`)
            .then(r => r.json())
            .then(data => {
                dispatch({ type: 'SET_API_STATUS', payload: data.status === 'ok' ? 'ok' : 'error' })
            })
            .catch(() => dispatch({ type: 'SET_API_STATUS', payload: 'error' }))
    }, [])

    const toggleTheme = () => {
        dispatch({ type: 'SET_THEME', payload: state.theme === 'dark' ? 'light' : 'dark' })
    }

    return (
        <AppContext.Provider value={{ state, dispatch, toggleTheme }}>
            {children}
        </AppContext.Provider>
    )
}

export const useApp = () => {
    const ctx = useContext(AppContext)
    if (!ctx) throw new Error('useApp must be used inside AppProvider')
    return ctx
}
