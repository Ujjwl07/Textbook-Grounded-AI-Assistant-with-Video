import React from 'react'
import { SignUp } from '@clerk/react'
import AuthShell, { authFormAppearance } from '../components/AuthShell'

export default function Register() {
  return (
    <AuthShell compact title="Join" accent="TextbookAI" subtitle="Turn any topic into a lesson video 🎬">
      <SignUp routing="path" path="/register" signInUrl="/login" appearance={authFormAppearance} />
    </AuthShell>
  )
}
