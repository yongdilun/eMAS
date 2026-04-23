import { useState } from 'react'

const FloatingChatButton = ({ onClick }) => {
  const [isHovered, setIsHovered] = useState(false)

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="fixed bottom-6 right-6 z-40 flex items-center gap-3 bg-primary hover:bg-primary/90 text-white rounded-full shadow-2xl hover:shadow-primary/50 transition-all duration-300 group"
      style={{
        padding: isHovered ? '0.875rem 1.5rem 0.875rem 0.875rem' : '0.875rem',
      }}
    >
      <div className="relative">
        <span className="material-symbols-outlined text-4xl" style={{ fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 48" }}>
          smart_toy
        </span>
        <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-green-500 rounded-full border-2 border-white animate-pulse"></span>
      </div>
      <span
        className={`font-semibold text-sm whitespace-nowrap overflow-hidden transition-all duration-300`}
        style={{
          width: isHovered ? 'auto' : '0',
          opacity: isHovered ? '1' : '0',
        }}
      >
        AI Assistant
      </span>
    </button>
  )
}

export default FloatingChatButton

