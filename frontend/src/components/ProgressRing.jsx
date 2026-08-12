import React from 'react';

export default function ProgressRing({ radius, stroke, progress, stage, message }) {
  const normalizedRadius = radius - stroke * 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const strokeDashoffset = circumference - (progress / 100) * circumference;

  const getColor = () => {
    if (progress < 40) return '#3b82f6'; // Blue (Retrieval)
    if (progress < 60) return '#10b981'; // Green (Script)
    if (progress < 88) return '#f59e0b'; // Orange (Audio/Video)
    return '#8b5cf6'; // Purple (Assembly)
  };

  return (
    <div className="flex flex-col items-center justify-center">
      <div className="relative flex items-center justify-center mb-4">
        <svg
          height={radius * 2}
          width={radius * 2}
          className="transform -rotate-90"
        >
          {/* Background Ring */}
          <circle
            stroke="rgba(0,0,0,0.1)"
            fill="transparent"
            strokeWidth={stroke}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
          />
          {/* Progress Ring */}
          <circle
            stroke={getColor()}
            fill="transparent"
            strokeWidth={stroke}
            strokeDasharray={circumference + ' ' + circumference}
            style={{ strokeDashoffset, transition: 'stroke-dashoffset 0.5s ease 0s, stroke 0.5s ease' }}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute flex flex-col items-center justify-center text-center">
          <span className="text-3xl font-bold" style={{ color: getColor() }}>{progress}%</span>
          <span className="text-sm font-medium uppercase tracking-wider text-gray-500 mt-1">{stage}</span>
        </div>
      </div>
      {message && <p className="text-lg font-medium text-gray-700 animate-pulse">{message}</p>}
    </div>
  );
}
