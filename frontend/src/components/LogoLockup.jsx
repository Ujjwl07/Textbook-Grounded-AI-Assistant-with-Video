import React from 'react'

// Full TextbookAI lockup (icon + wordmark + hand-drawn underline), from public/brand/logo-lockup.svg.
// Inlined so the wordmark renders in the page's Inter font. viewBox is cropped to the artwork.
export default function LogoLockup({ className = '' }) {
  return (
    <svg
      className={className}
      viewBox="36 56 960 250"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="TextbookAI"
    >
      <g className="lockup-icon" transform="translate(40,60) scale(0.468)">
        <rect className="lockup-tile" width="512" height="512" rx="116" fill="#111315" />
        <path className="lockup-page-l" d="M256 188 C210 166 150 160 104 174 L104 322 C150 308 210 314 256 336 Z" fill="#FFFFFF" />
        <path className="lockup-page-r" d="M256 188 C302 166 362 160 408 174 L408 322 C362 308 302 314 256 336 Z" fill="#F1F2F4" />
        <g className="lockup-lines">
          <path d="M134 208 C168 200 204 200 232 210" stroke="#C7CBD1" strokeWidth="7" strokeLinecap="round" fill="none" />
          <path d="M134 240 C168 232 204 232 232 242" stroke="#C7CBD1" strokeWidth="7" strokeLinecap="round" fill="none" />
          <path d="M280 210 C308 200 344 200 378 208" stroke="#C7CBD1" strokeWidth="7" strokeLinecap="round" fill="none" />
          <path d="M280 242 C308 232 344 232 378 240" stroke="#C7CBD1" strokeWidth="7" strokeLinecap="round" fill="none" />
        </g>
        <circle className="lockup-badge" cx="256" cy="268" r="70" fill="#E11D2E" stroke="#111315" strokeWidth="10" />
        <path d="M238 238 L238 298 L290 268 Z" fill="#FFFFFF" />
      </g>
      <text
        x="316" y="236"
        fontFamily="Inter, 'Helvetica Neue', Arial, sans-serif"
        fontWeight="800" fontSize="150" letterSpacing="-6"
      >
        <tspan className="lockup-word" fill="#111315">Textbook</tspan>
        <tspan className="lockup-ai" fill="#E11D2E">AI</tspan>
      </text>
      <g className="lockup-underline" fill="none" stroke="#E11D2E" strokeLinecap="round">
        <path pathLength="1" d="M322 272 C520 256 760 256 980 266" strokeWidth="12" />
        <path pathLength="1" d="M332 286 C540 300 770 300 968 288" strokeWidth="9" opacity="0.85" />
      </g>
    </svg>
  )
}
