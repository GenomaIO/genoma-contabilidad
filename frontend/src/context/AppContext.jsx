/**
 * AppContext — Multi-tenant state global
 * NO hardcoded tenant IDs · Todo desde JWT o env
 */
import { createContext, useContext, useReducer, useEffect } from 'react'

const AppContext = createContext(null)

const initialState = {
    theme: localStorage.getItem('gc_theme') || 'dark',
    sidebarOpen: false,
    user: null,
    tenant: null,
    period: null,        // { year, month } periodo contable activo
    apiStatus: 'checking', // 'ok' | 'error' | 'checking'
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
            return { ...state, tenant: action.payload }

        case 'SET_PERIOD':
            return { ...state, period: action.payload }

        case 'SET_API_STATUS':
            return { ...state, apiStatus: action.payload }

        case 'LOGOUT':
            localStorage.removeItem('gc_token')
            return { ...initialState, theme: state.theme, apiStatus: state.apiStatus }

        default:
            return state
    }
}

/**
 * Parsea el payload de un JWT sin verificar firma (solo para leer claims en el frontend).
 * La verificación real ocurre siempre en el backend.
 */
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

    // Aplicar tema al html element
    useEffect(() => {
        document.documentElement.setAttribute('data-theme', state.theme)
    }, [state.theme])

    // ── Hidratación: URL ?token= → localStorage → Estado ──────────
    useEffect(() => {
        const params = new URLSearchParams(window.location.search)
        const urlToken = params.get('token')
        let activeToken = null

        if (urlToken) {
            // Llegamos desde partner_dashboard con ?token=JWT
            localStorage.setItem('gc_token', urlToken)
            activeToken = urlToken
            // Limpiar token de la URL sin recargar la página
            window.history.replaceState({}, document.title, window.location.pathname)
        } else {
            // Sesión persistida en localStorage
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
            } else {
                // Token expirado — limpiar
                localStorage.removeItem('gc_token')
            }
        }
    }, [])

    // Verificar health del backend al iniciar
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
