import axios from 'axios'
import { getToken } from '@clerk/react'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000/api'

const api = axios.create({ baseURL: API_BASE_URL })

// Attach the Clerk session token to every request. getToken() refreshes it
// as needed (Clerk tokens only live ~60s) and returns null when signed out.
api.interceptors.request.use(async (config) => {
  try {
    const token = await getToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
  } catch (e) {
    // Clerk not loaded / offline: send the request without a token
  }
  return config
})

// A longer-lived token for <video src=...>, which can't send headers and keeps
// making range requests long after a Clerk token would have expired.
export async function getMediaToken() {
  const res = await api.post('/auth/media-token')
  return res.data.token
}

export async function generateVideo(payload) {
  return api.post('/generate', payload)
}

export async function getStatus(jobId) {
  return api.get(`/status/${jobId}`)
}

export async function getVideo(jobId) {
  return api.get(`/video/${jobId}`)
}

export async function listVideos() {
  return api.get('/videos')
}

export async function submitQuiz(attempt) {
  return api.post('/quiz/submit', attempt)
}

export async function generateQuiz(payload) {
  // Quiz generation can take a while (Gemini, then a textbook-only fallback).
  return api.post('/quiz/generate', payload, { timeout: 90000 })
}

export async function getNextQuestion(quizId) {
  return api.get(`/quiz/${quizId}/next`)
}

export async function getQuizHistory(userId) {
  return api.get(`/quiz/history/${userId}`)
}

export async function getDashboard(userId) {
  return api.get(`/users/${userId}/dashboard`)
}

export default api
