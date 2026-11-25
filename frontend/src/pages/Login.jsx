import React from 'react'
import { SignIn } from '@clerk/react'
import AuthShell, { authFormAppearance } from '../components/AuthShell'

export default function Login() {
  return (
    <AuthShell title="Sign in to" accent="TextbookAI" subtitle="Welcome back! Turn any topic into a lesson video 🎬">
      <SignIn routing="path" path="/login" signUpUrl="/register" appearance={authFormAppearance} />
    </AuthShell>
  )
}
