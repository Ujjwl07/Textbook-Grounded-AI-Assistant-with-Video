import React, { useState } from 'react';

export default function AdminPanel() {
  const [selectedSubject, setSelectedSubject] = useState('physics');
  const [classNum, setClassNum] = useState('11');
  
  return (
    <div className="container">
      <h1 className="hero-title" style={{ fontSize: '2.5rem', marginBottom: '2rem' }}>Admin Dashboard</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '2rem' }}>
        {/* PDF Ingestion Section */}
        <div className="glass-panel">
          <h2 style={{ fontSize: '1.5rem', marginBottom: '1.5rem' }}>Upload NCERT PDF</h2>
          
          <div className="flex-col gap-4">
            <div>
              <label className="input-label">Subject</label>
              <select 
                value={selectedSubject} 
                onChange={(e) => setSelectedSubject(e.target.value)}
                className="input-field"
              >
                <option value="physics">Physics</option>
                <option value="biology">Biology</option>
                <option value="chemistry">Chemistry</option>
              </select>
            </div>
            
            <div>
              <label className="input-label">Class</label>
              <select 
                value={classNum} 
                onChange={(e) => setClassNum(e.target.value)}
                className="input-field"
              >
                <option value="11">Class 11</option>
                <option value="12">Class 12</option>
              </select>
            </div>

            <div style={{
              border: '2px dashed var(--glass-border)',
              borderRadius: '12px',
              padding: '2rem',
              textAlign: 'center',
              marginTop: '1rem',
              background: 'rgba(0,0,0,0.2)'
            }}>
              <input type="file" id="pdf-upload" style={{ display: 'none' }} accept=".pdf" />
              <label htmlFor="pdf-upload" style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <svg style={{ height: '3rem', width: '3rem', color: 'var(--accent-primary)', marginBottom: '1rem' }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <span style={{ color: 'var(--accent-primary)', fontWeight: '600' }}>Click to upload</span> 
                <span style={{ color: 'var(--text-secondary)' }}>or drag and drop</span>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>NCERT PDF Format Only</p>
              </label>
            </div>
            
            <button className="btn-primary mt-4" style={{ width: '100%' }}>
              Process & Index Document
            </button>
          </div>
        </div>

        {/* Index Monitor Section */}
        <div className="glass-panel">
          <h2 style={{ fontSize: '1.5rem', marginBottom: '1.5rem' }}>Vector Index Status</h2>
          
          <div className="flex-col gap-4">
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem', background: 'rgba(0,0,0,0.3)', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Total Chunks Indexed</span>
              <span style={{ fontWeight: 600, color: 'white' }}>15,243</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem', background: 'rgba(0,0,0,0.3)', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Physics Chunks</span>
              <span style={{ fontWeight: 600, color: '#3b82f6' }}>4,120</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem', background: 'rgba(0,0,0,0.3)', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Biology Chunks</span>
              <span style={{ fontWeight: 600, color: '#10b981' }}>6,532</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem', background: 'rgba(0,0,0,0.3)', borderRadius: '8px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Chemistry Chunks</span>
              <span style={{ fontWeight: 600, color: '#f59e0b' }}>4,591</span>
            </div>
          </div>
          
          <div className="mt-8">
            <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem' }}>Recent Ingestion Jobs</h3>
            <div className="flex-col gap-4">
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.8rem', borderLeft: '4px solid #10b981', background: 'rgba(16,185,129,0.1)', borderRadius: '4px' }}>
                <span>Physics_Class11_Ch3.pdf</span>
                <span style={{ color: '#10b981', fontWeight: 600, fontSize: '0.9rem' }}>Completed</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.8rem', borderLeft: '4px solid #f59e0b', background: 'rgba(245,158,11,0.1)', borderRadius: '4px', marginTop: '0.5rem' }}>
                <span>Biology_Class12_Ch5.pdf</span>
                <span style={{ color: '#f59e0b', fontWeight: 600, fontSize: '0.9rem' }}>Processing (45%)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
