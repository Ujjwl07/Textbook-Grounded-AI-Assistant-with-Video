import React from 'react'

// Gradients and science icons for the sign-in / sign-up background belt.
// Rendered once (hidden) and referenced with <use href="#au-...">.
export default function AuthIcons() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true" focusable="false">
      <defs>
    <radialGradient id="au-gNuc" cx="35%" cy="30%" r="75%"><stop offset="0%" stopColor="#ddd6fe"/><stop offset="55%" stopColor="#8b5cf6"/><stop offset="100%" stopColor="#5b21b6"/></radialGradient>
    <radialGradient id="au-gMem" cx="35%" cy="28%" r="80%"><stop offset="0%" stopColor="#eaf6ff"/><stop offset="50%" stopColor="#9ecdf0"/><stop offset="100%" stopColor="#4f9fd4"/></radialGradient>
    <linearGradient id="au-gGlass" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#f4faff"/><stop offset="100%" stopColor="#bcd7f7"/></linearGradient>
    <linearGradient id="au-gLiq" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6ee7a0"/><stop offset="100%" stopColor="#15a34a"/></linearGradient>
    <linearGradient id="au-gMetal" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#6b7280"/><stop offset="50%" stopColor="#1f2937"/><stop offset="100%" stopColor="#404a5a"/></linearGradient>
    <linearGradient id="au-gRed" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#ff5d73"/><stop offset="100%" stopColor="#c81e35"/></linearGradient>
    <linearGradient id="au-gBlue" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#7cb6fb"/><stop offset="100%" stopColor="#2563eb"/></linearGradient>
    <linearGradient id="au-gGreen" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#5eead4"/><stop offset="100%" stopColor="#15803d"/></linearGradient>
    <linearGradient id="au-gGold" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#fde68a"/><stop offset="100%" stopColor="#d97706"/></linearGradient>
    <linearGradient id="au-gInk" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#475569"/><stop offset="100%" stopColor="#0f172a"/></linearGradient>
    <linearGradient id="au-gPink" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#fb7faa"/><stop offset="100%" stopColor="#be1e52"/></linearGradient>
    <symbol id="au-ic-cell" viewBox="0 0 48 48">
      <circle cx="24" cy="24" r="21" fill="url(#au-gMem)" stroke="#4f9fd4" strokeWidth="1.5"/>
      <ellipse cx="17" cy="15" rx="7" ry="4" fill="#fff" opacity=".35"/>
      <circle cx="22" cy="23" r="10" fill="url(#au-gPink)"/><circle cx="22" cy="23" r="5.5" fill="#a21446"/><circle cx="22" cy="23" r="2.4" fill="#312e81"/><circle cx="20.5" cy="21.5" r="1" fill="#fff" opacity=".7"/>
      <ellipse cx="33" cy="16" rx="4" ry="2.5" fill="url(#au-gPink)" transform="rotate(-25 33 16)"/>
      <circle cx="34" cy="30" r="3.4" fill="url(#au-gGreen)"/><circle cx="14" cy="32" r="2" fill="url(#au-gGold)"/><circle cx="31" cy="34" r="1.6" fill="url(#au-gGold)"/>
      <rect x="13" y="18" width="7" height="3" rx="1.5" fill="url(#au-gGold)" transform="rotate(-20 16 19)"/>
    </symbol>
    <symbol id="au-ic-micro" viewBox="0 0 48 48">
      <rect x="9" y="40" width="30" height="4.5" rx="2.2" fill="url(#au-gInk)"/>
      <path d="M22 40c-6-2-9-8-8-15l4 1c-1 5 1 9 6 11z" fill="url(#au-gMetal)"/>
      <rect x="25" y="9" width="6" height="15" rx="2.5" transform="rotate(20 28 16)" fill="url(#au-gInk)"/>
      <circle cx="21" cy="12" r="3.6" fill="#0b0b0f"/><circle cx="20" cy="11" r="1" fill="#fff" opacity=".5"/>
      <rect x="18" y="24" width="14" height="4" rx="1.5" fill="#8b93a1"/>
      <rect x="26" y="28" width="4" height="9" fill="url(#au-gMetal)"/>
      <circle cx="33" cy="33" r="4.8" fill="#aeb6c2" stroke="#5b6472" strokeWidth="1.4"/><circle cx="33" cy="33" r="1.8" fill="#333"/>
    </symbol>
    <symbol id="au-ic-dna" viewBox="0 0 48 48">
      <path d="M17 7c0 9 14 9 14 17s-14 8-14 17" stroke="url(#au-gRed)" strokeWidth="2.8" fill="none" strokeLinecap="round"/>
      <path d="M31 7c0 9-14 9-14 17s14 8 14 17" stroke="url(#au-gBlue)" strokeWidth="2.8" fill="none" strokeLinecap="round"/>
      <path d="M18 14h12M19 20h10M19 28h10M18 34h12" stroke="#5aa6d6" strokeWidth="2" strokeLinecap="round"/>
    </symbol>
    <symbol id="au-ic-force" viewBox="0 0 48 48">
      <path d="M6 34h36" stroke="#475569" strokeWidth="2"/>
      <path d="M8 34l-3 4M14 34l-3 4M20 34l-3 4M26 34l-3 4M32 34l-3 4M38 34l-3 4" stroke="#94a3b8" strokeWidth="1.4"/>
      <rect x="18" y="22" width="13" height="12" rx="1" fill="url(#au-gGold)" stroke="#b7851f" strokeWidth="1.2"/>
      <path d="M24.5 22V8" stroke="#c81e35" strokeWidth="2.4"/><path d="M24.5 6l-3 5h6z" fill="#c81e35"/>
      <path d="M24.5 34v9" stroke="#2563eb" strokeWidth="2.4"/><path d="M24.5 45l-3-5h6z" fill="#2563eb"/>
    </symbol>
    <symbol id="au-ic-flask" viewBox="0 0 48 48">
      <path d="M20 8h8v11l7 15a4 4 0 0 1-3.7 5.6H16.7A4 4 0 0 1 13 34l7-15V8z" fill="url(#au-gGlass)" stroke="#2563eb" strokeWidth="1.8"/>
      <path d="M15.5 28h17l2.3 5A4 4 0 0 1 31 39H17a4 4 0 0 1-3.8-6z" fill="url(#au-gLiq)"/>
      <path d="M22 11v16" stroke="#fff" strokeWidth="1.6" opacity=".55" strokeLinecap="round"/>
      <rect x="18" y="6" width="12" height="3" rx="1.5" fill="#2563eb"/>
    </symbol>
    <symbol id="au-ic-atom" viewBox="0 0 48 48">
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#a78bfa" strokeWidth="2" fill="none"/>
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#8b5cf6" strokeWidth="2" fill="none" transform="rotate(60 24 24)"/>
      <ellipse cx="24" cy="24" rx="17" ry="7" stroke="#c4b5fd" strokeWidth="2" fill="none" transform="rotate(120 24 24)"/>
      <circle cx="24" cy="24" r="5" fill="url(#au-gNuc)"/><circle cx="22.4" cy="22.4" r="1.5" fill="#fff" opacity=".65"/>
    </symbol>
    <symbol id="au-ic-book" viewBox="0 0 48 48">
      <rect x="9" y="30" width="30" height="7" rx="2" fill="url(#au-gRed)"/><rect x="11" y="31" width="26" height="1.4" fill="#fff" opacity=".45"/>
      <rect x="11" y="23" width="28" height="7" rx="2" fill="url(#au-gBlue)"/><rect x="13" y="24" width="24" height="1.4" fill="#fff" opacity=".45"/>
      <rect x="8" y="16" width="27" height="7" rx="2" fill="url(#au-gGreen)"/><rect x="10" y="17" width="23" height="1.4" fill="#fff" opacity=".45"/>
    </symbol>
    <symbol id="au-ic-play" viewBox="0 0 48 48">
      <circle cx="24" cy="24" r="16" fill="url(#au-gMetal)"/><circle cx="24" cy="24" r="4" fill="url(#au-gRed)"/>
      <circle cx="24" cy="12" r="2.4" fill="#0b0b0f"/><circle cx="24" cy="36" r="2.4" fill="#0b0b0f"/><circle cx="12" cy="24" r="2.4" fill="#0b0b0f"/><circle cx="36" cy="24" r="2.4" fill="#0b0b0f"/>
      <ellipse cx="18" cy="17" rx="5" ry="2.4" fill="#fff" opacity=".12"/>
    </symbol>
    <symbol id="au-el-h" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#b3b0ef" stroke="#6f6bd6" strokeWidth="1.6"/><text x="24" y="31" fontSize="19" fontWeight="800" textAnchor="middle" fill="#2a2a4a" fontFamily="Arial">H</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#4a4a6a" fontFamily="Arial">1</text></symbol>
    <symbol id="au-el-c" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#b3b0ef" stroke="#6f6bd6" strokeWidth="1.6"/><text x="24" y="31" fontSize="19" fontWeight="800" textAnchor="middle" fill="#2a2a4a" fontFamily="Arial">C</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#4a4a6a" fontFamily="Arial">6</text></symbol>
    <symbol id="au-el-o" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#b3b0ef" stroke="#6f6bd6" strokeWidth="1.6"/><text x="24" y="31" fontSize="19" fontWeight="800" textAnchor="middle" fill="#2a2a4a" fontFamily="Arial">O</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#4a4a6a" fontFamily="Arial">8</text></symbol>
    <symbol id="au-el-fe" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#eef08a" stroke="#b9bb55" strokeWidth="1.6"/><text x="24" y="31" fontSize="17" fontWeight="800" textAnchor="middle" fill="#3a3a22" fontFamily="Arial">Fe</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#5a5a3a" fontFamily="Arial">26</text></symbol>
    <symbol id="au-el-na" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#f0c89a" stroke="#c99a5a" strokeWidth="1.6"/><text x="24" y="31" fontSize="17" fontWeight="800" textAnchor="middle" fill="#4a3522" fontFamily="Arial">Na</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#6a4f3a" fontFamily="Arial">11</text></symbol>
    <symbol id="au-el-ca" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="7" fill="#f0c89a" stroke="#c99a5a" strokeWidth="1.6"/><text x="24" y="31" fontSize="17" fontWeight="800" textAnchor="middle" fill="#4a3522" fontFamily="Arial">Ca</text><text x="39" y="15" fontSize="9" textAnchor="end" fill="#6a4f3a" fontFamily="Arial">20</text></symbol>
  </defs>
    </svg>
  )
}
