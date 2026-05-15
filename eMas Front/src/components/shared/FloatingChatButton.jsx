import { useState } from 'react'

const FloatingChatButton = ({ onClick }) => {
    const [isHovered, setIsHovered] = useState(false)

    return (
        <button
            onClick={onClick}
            aria-label="Open AI Assistant"
            data-testid="floating-chat-button"
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-md border border-white/40 bg-primary text-on-primary transition-all duration-300 hover:bg-primary-hover focus:outline-none focus:ring-2 focus:ring-primary-focus/50 dark:border-hairline-tertiary group"
            style={{
                padding: isHovered ? '8px 14px' : '8px',
            }}
        >
            <div className="relative flex items-center justify-center">
                <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" }}>
                    smart_toy
                </span>
                <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-semantic-success rounded-full border border-primary animate-pulse"></span>
            </div>
            <span
                className="text-button whitespace-nowrap overflow-hidden transition-all duration-300"
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
