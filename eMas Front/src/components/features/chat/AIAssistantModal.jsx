import { useState, useRef, useCallback, useEffect } from 'react'
import FactoryAgentChatPanel from './factory-agent/FactoryAgentChatPanel'

const MIN_WIDTH = 400
const MIN_HEIGHT = 300
const DEFAULT_WIDTH = 900
const DEFAULT_HEIGHT = 600

const AIAssistantModal = ({ isOpen, onClose }) => {
    const containerRef = useRef(null)
    const [position, setPosition] = useState({ x: 0, y: 0 })
    const [size, setSize] = useState({ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT })
    const [isDragging, setIsDragging] = useState(false)
    const [isResizing, setIsResizing] = useState(false)
    const dragStart = useRef({ x: 0, y: 0, left: 0, top: 0 })
    const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0, edge: '' })

    const fitToViewport = useCallback(() => {
        const w = Math.min(DEFAULT_WIDTH, window.innerWidth - 32)
        const h = Math.min(DEFAULT_HEIGHT, window.innerHeight - 48)
        setSize({ width: w, height: h })
        setPosition({
            x: Math.max(0, (window.innerWidth - w) / 2),
            y: Math.max(0, (window.innerHeight - h) / 2),
        })
    }, [])

    useEffect(() => {
        if (!isOpen) return
        fitToViewport()
    }, [fitToViewport, isOpen])

    useEffect(() => {
        if (!isOpen || isDragging || isResizing) return undefined
        window.addEventListener('resize', fitToViewport)
        return () => window.removeEventListener('resize', fitToViewport)
    }, [fitToViewport, isDragging, isOpen, isResizing])

    const handleMouseDown = useCallback((e) => {
        if (!e.target.closest('[data-drag-handle]')) return
        e.preventDefault()
        setIsDragging(true)
        dragStart.current = {
            x: e.clientX,
            y: e.clientY,
            left: position.x,
            top: position.y,
        }
    }, [position])

    const handleResizeMouseDown = useCallback((e, edge) => {
        e.preventDefault()
        e.stopPropagation()
        setIsResizing(true)
        resizeStart.current = {
            x: e.clientX,
            y: e.clientY,
            w: size.width,
            h: size.height,
            left: position.x,
            top: position.y,
            edge,
        }
    }, [size, position])

    useEffect(() => {
        if (!isDragging) return
        const onMove = (e) => {
            const dx = e.clientX - dragStart.current.x
            const dy = e.clientY - dragStart.current.y
            setPosition({
                x: Math.max(0, dragStart.current.left + dx),
                y: Math.max(0, dragStart.current.top + dy),
            })
        }
        const onUp = () => setIsDragging(false)
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
        return () => {
            document.removeEventListener('mousemove', onMove)
            document.removeEventListener('mouseup', onUp)
        }
    }, [isDragging])

    useEffect(() => {
        if (!isResizing) return
        const onMove = (e) => {
            const { edge, x, y, w, h, left, top } = resizeStart.current
            const dx = e.clientX - x
            const dy = e.clientY - y
            let newW = w
            let newH = h
            let newX = left
            let newY = top
            if (edge.includes('e')) newW = Math.max(MIN_WIDTH, w + dx)
            if (edge.includes('w')) {
                newW = Math.max(MIN_WIDTH, w - dx)
                newX = left + (w - newW)
            }
            if (edge.includes('s')) newH = Math.max(MIN_HEIGHT, h + dy)
            if (edge.includes('n')) {
                newH = Math.max(MIN_HEIGHT, h - dy)
                newY = top + (h - newH)
            }
            setSize({ width: newW, height: newH })
            setPosition({ x: Math.max(0, newX), y: Math.max(0, newY) })
        }
        const onUp = () => setIsResizing(false)
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
        return () => {
            document.removeEventListener('mousemove', onMove)
            document.removeEventListener('mouseup', onUp)
        }
    }, [isResizing])

    if (!isOpen) return null

    return (
        <div
            className="fixed inset-0 z-50 pointer-events-none"
            role="dialog"
            aria-modal="true"
            aria-label="AI Assistant"
        >
            <div
                ref={containerRef}
                className="pointer-events-auto absolute flex flex-col overflow-hidden rounded-xl border-2 border-hairline-strong bg-surface-1 dark:border-hairline-tertiary resize-container"
                style={{
                    left: position.x,
                    top: position.y,
                    width: size.width,
                    height: size.height,
                    cursor: isDragging ? 'grabbing' : undefined,
                }}
                data-ai-assistant-modal-window=""
            >
                <FactoryAgentChatPanel onClose={onClose} onHeaderMouseDown={handleMouseDown} />
                {/* Resize handles - 4 edges + 4 corners */}
                <div
                    data-resize="n"
                    className="absolute left-0 right-0 top-0 h-1 cursor-ns-resize hover:bg-primary/20 transition-colors z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'n')}
                />
                <div
                    data-resize="s"
                    className="absolute left-0 right-0 bottom-0 h-1 cursor-ns-resize hover:bg-primary/20 transition-colors z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 's')}
                />
                <div
                    data-resize="e"
                    className="absolute right-0 top-0 bottom-0 w-1 cursor-ew-resize hover:bg-primary/20 transition-colors z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'e')}
                />
                <div
                    data-resize="w"
                    className="absolute left-0 top-0 bottom-0 w-1 cursor-ew-resize hover:bg-primary/20 transition-colors z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'w')}
                />
                <div
                    data-resize="nw"
                    className="absolute left-0 top-0 w-3 h-3 cursor-nw-resize hover:bg-primary/15 rounded-br z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'nw')}
                />
                <div
                    data-resize="ne"
                    className="absolute right-0 top-0 w-3 h-3 cursor-ne-resize hover:bg-primary/15 rounded-bl z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'ne')}
                />
                <div
                    data-resize="sw"
                    className="absolute left-0 bottom-0 w-3 h-3 cursor-sw-resize hover:bg-primary/15 rounded-tr z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'sw')}
                />
                <div
                    data-resize="se"
                    className="absolute right-0 bottom-0 w-3 h-3 cursor-se-resize hover:bg-primary/15 rounded-tl z-10"
                    onMouseDown={(e) => handleResizeMouseDown(e, 'se')}
                />
            </div>
        </div>
    )
}

export default AIAssistantModal
