import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import { submitQuiz } from '../services/api'

export default function QuizSession() {
  const { videoId } = useParams()
  const [questionId, setQuestionId] = useState('')
  const [selectedOption, setSelectedOption] = useState('A')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    try {
      const res = await submitQuiz({
        question_id: questionId,
        selected_option: selectedOption,
      })
      setResult(res.data)
      setError(null)
    } catch (err) {
      setResult(null)
      setError(err.response?.data?.detail || 'Quiz submit failed')
    }
  }

  return (
    <div>
      <h2>Quiz for {videoId}</h2>
      <form className="card" onSubmit={handleSubmit}>
        <label>Question ID</label>
        <input
          value={questionId}
          onChange={(e) => setQuestionId(e.target.value)}
          placeholder="question_id from backend"
        />

        <label>Selected option</label>
        <select value={selectedOption} onChange={(e) => setSelectedOption(e.target.value)}>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
          <option value="D">D</option>
        </select>

        <button type="submit" disabled={!questionId}>Submit Answer</button>
      </form>
      {error && <div className="error">Error: {error}</div>}
      {result && <div className="card">{JSON.stringify(result)}</div>}
    </div>
  )
}
