import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, useNavigate } from 'react-router-dom'
import { ClerkProvider } from '@clerk/react'
import App from './App'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import './styles.css'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

// Clerk's sign-in/sign-up cards styled to match styles.css in each theme.
const CLERK_COLORS = {
  light: { primary: '#f5003c', bg: '#ffffff', fg: '#0e0e0e', muted: 'rgba(14, 14, 14, 0.6)', border: '#0e0e0e', logo: 'icon-dark.svg' },
  dark: { primary: '#ff4d64', bg: '#0e0f12', fg: '#f4f4f5', muted: 'rgba(244, 244, 245, 0.66)', border: 'rgba(244, 244, 245, 0.25)', logo: 'icon-crimson.svg' },
}

function clerkAppearance(theme) {
  const c = CLERK_COLORS[theme] || CLERK_COLORS.light
  return {
    options: { logoImageUrl: `${window.location.origin}/brand/${c.logo}`, logoLinkUrl: '/', unsafe_disableDevelopmentModeWarnings: true },
    variables: {
      colorPrimary: c.primary,
      colorBackground: c.bg,
      colorForeground: c.fg,
      colorMutedForeground: c.muted,
      colorMuted: c.bg,
      colorInput: c.bg,
      colorInputForeground: c.fg,
      colorNeutral: c.fg,
      colorBorder: c.border,
      borderRadius: '0px',
      fontFamily: "'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif",
    },
    elements: {
      card: { boxShadow: 'none', border: `1px solid ${c.border}` },
      cardBox: { boxShadow: 'none', border: 'none', borderRadius: 0 },
      headerTitle: { fontWeight: 900, fontSize: '30px' },
      formButtonPrimary: { boxShadow: 'none', fontWeight: 700, textTransform: 'none' },
      socialButtonsBlockButton: { boxShadow: 'none' },
      // Show Google before GitHub (Clerk lists providers alphabetically).
      socialButtonsBlockButton__google: { order: -1 },
      socialButtonsIconButton__google: { order: -1 },
      formFieldInput: { boxShadow: 'none' },
      footer: { background: c.bg },
      logoBox: { height: '48px', justifyContent: 'center' },
      logoImage: { height: '48px', width: '48px' },
    },
  }
}

// Full-width social buttons read "Continue with Google" rather than just "Google".
const CLERK_TEXT = { socialButtonsBlockButtonManyInView: 'Continue with {{provider|titleize}}' }

// ClerkProvider sits inside the router so Clerk's own redirects (after sign-in,
// sign-out, etc.) use client-side navigation instead of full page reloads.
function ClerkWithRouter({ children }) {
  const navigate = useNavigate()
  const { theme } = useTheme()
  return (
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
      signInUrl="/login"
      signUpUrl="/register"
      signInFallbackRedirectUrl="/search"
      signUpFallbackRedirectUrl="/search"
      afterSignOutUrl="/"
      appearance={clerkAppearance(theme)}
      localization={CLERK_TEXT}
    >
      {children}
    </ClerkProvider>
  )
}

function MissingClerkKey() {
  return (
    <div style={{ maxWidth: 560, margin: '4rem auto', padding: '0 16px', fontFamily: "'Inter', Helvetica, Arial, sans-serif", color: '#0e0e0e' }}>
      <h2>Clerk isn't configured</h2>
      <p>
        Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in <code>frontend/.env</code> (from the Clerk dashboard →
        API keys) and restart the dev server.
      </p>
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {PUBLISHABLE_KEY ? (
      <ThemeProvider>
        <BrowserRouter>
          <ClerkWithRouter>
            <AuthProvider>
              <App />
            </AuthProvider>
          </ClerkWithRouter>
        </BrowserRouter>
      </ThemeProvider>
    ) : (
      <MissingClerkKey />
    )}
  </React.StrictMode>
)
