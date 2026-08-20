import React from 'react';

export default function SubjectBadge({ subject, classNum, chapterNum, neetWeight }) {
  const getSubjectColor = () => {
    switch (subject.toLowerCase()) {
      case 'physics': return '#3b82f6';
      case 'biology': return '#10b981';
      case 'chemistry': return '#f59e0b';
      default: return '#6b7280';
    }
  };

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.25rem 0.75rem',
      borderRadius: '9999px',
      color: 'white',
      fontSize: '0.875rem',
      fontWeight: 500,
      background: getSubjectColor(),
      boxShadow: `0 0 10px ${getSubjectColor()}80`
    }}>
      <span>{subject.charAt(0).toUpperCase() + subject.slice(1)}</span>
      <span style={{ opacity: 0.75 }}>|</span>
      <span>Class {classNum}</span>
      {chapterNum && (
        <>
          <span style={{ opacity: 0.75 }}>|</span>
          <span>Ch {chapterNum}</span>
        </>
      )}
      {neetWeight && (
        <div style={{
          marginLeft: '0.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.25rem',
          background: 'rgba(0,0,0,0.2)',
          padding: '0.125rem 0.5rem',
          borderRadius: '9999px',
          fontSize: '0.75rem'
        }}>
          <span>NEET:</span>
          <div style={{
            width: '4rem',
            height: '0.5rem',
            background: 'rgba(255,255,255,0.3)',
            borderRadius: '9999px',
            overflow: 'hidden'
          }}>
            <div style={{
              height: '100%',
              background: '#fde047',
              width: `${neetWeight * 100}%`
            }} />
          </div>
        </div>
      )}
    </div>
  );
}
