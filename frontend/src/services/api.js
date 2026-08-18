import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
export const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000/api'

const api = axios.create({ baseURL: API_BASE_URL })

// Attach token from localStorage to every request if present
api.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem('access_token')
    if (token) config.headers = { ...config.headers, Authorization: `Bearer ${token}` }
  } catch (e) {
    // ignore
  }
  return config
})

export async function register(name, email, password) {
  return api.post('/auth/register', { name, email, password })
}

export async function login(email, password) {
  return api.post('/auth/login', { email, password })
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

export async function getQuizHistory(userId) {
  return api.get(`/quiz/history/${userId}`)
}

export async function getDashboard(userId) {
  return api.get(`/users/${userId}/dashboard`)
}

export default api
