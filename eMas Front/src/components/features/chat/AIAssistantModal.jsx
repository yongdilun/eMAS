import { useState, useRef, useCallback, useEffect } from 'react'
import FactoryAgentChatPanel from './factory-agent/FactoryAgentChatPanel'

const MIN_WIDTH = 400
const MIN_HEIGHT = 300
const DEFAULT_WIDTH = 900
const DEFAULT_HEIGHT = 600
const VIEWPORT_GAP = 8

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max)
}

function viewportRect() {
    const width = typeof window === 'undefined' ? DEFAULT_WIDTH : window.innerWidth
    const height = typeof window === 'undefined' ? DEFAULT_HEIGHT : window.innerHeight
    return { width, height }
}

function boundedModalRect(rect) {
    const viewport = viewportRect()
    const maxWidth = Math.max(160, viewport.width - VIEWPORT_GAP * 2)
    const maxHeight = Math.max(160, viewport.height - VIEWPORT_GAP * 2)
    const minWidth = Math.min(MIN_WIDTH, maxWidth)
    const minHeight = Math.min(MIN_HEIGHT, maxHeight)
    const width = clamp(rect.width, minWidth, maxWidth)
    const height = clamp(rect.height, minHeight, maxHeight)
    const maxX = Math.max(VIEWPORT_GAP, viewport.width - width - VIEWPORT_GAP)
    const maxY = Math.max(VIEWPORT_GAP, viewport.height - height - VIEWPORT_GAP)
    return {
        x: clamp(rect.x, VIEWPORT_GAP, maxX),
        y: clamp(rect.y, VIEWPORT_GAP, maxY),
        width,
        height,
    }
}

const AIAssistantModal = ({ isOpen, onClose }) => {
    const containerRef = useRef(null)
    const [position, setPosition] = useState({ x: 0, y: 0 })
    const [size, setSize] = useState({ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT })
    const [isDragging, setIsDragging] = useState(false)
    const [isResizing, setIsResizing] = useState(false)
    const [isFullscreen, setIsFullscreen] = useState(false)
    const dragStart = useRef({ x: 0, y: 0, left: 0, top: 0 })
    const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0, edge: '' })
    const windowedBounds = useRef({ position: { x: 0, y: 0 }, size: { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT } })

    const fitToViewport = useCallback(() => {
        const viewport = viewportRect()
        const w = Math.min(DEFAULT_WIDTH, viewport.width - VIEWPORT_GAP * 2)
        const h = Math.min(DEFAULT_HEIGHT, viewport.height - VIEWPORT_GAP * 2)
        const next = boundedModalRect({
            x: (viewport.width - w) / 2,
            y: (viewport.height - h) / 2,
            width: w,
            height: h,
        })
        setSize({ width: next.width, height: next.height })
        setPosition({ x: next.x, y: next.y })
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
        if (isFullscreen) return
        if (!e.target.closest('[data-drag-handle]')) return
        e.preventDefault()
        setIsDragging(true)
        dragStart.current = {
            x: e.clientX,
            y: e.clientY,
            left: position.x,
            top: position.y,
        }
    }, [isFullscreen, position])

    const handleResizeMouseDown = useCallback((e, edge) => {
        if (isFullscreen) return
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
    }, [isFullscreen, size, position])

    const toggleFullscreen = useCallback(() => {
        if (isFullscreen) {
            const restored = windowedBounds.current
            const next = boundedModalRect({
                x: restored.position.x,
                y: restored.position.y,
                width: restored.size.width,
                height: restored.size.height,
            })
            setSize({ width: next.width, height: next.height })
            setPosition({ x: next.x, y: next.y })
            setIsFullscreen(false)
            return
        }
        windowedBounds.current = { position, size }
        setIsDragging(false)
        setIsResizing(false)
        setIsFullscreen(true)
    }, [isFullscreen, position, size])

    useEffect(() => {
        if (!isDragging) return
        const onMove = (e) => {
            const dx = e.clientX - dragStart.current.x
            const dy = e.clientY - dragStart.current.y
            const next = boundedModalRect({
                x: dragStart.current.left + dx,
                y: dragStart.current.top + dy,
                width: size.width,
                height: size.height,
            })
            setPosition({ x: next.x, y: next.y })
        }
        const onUp = () => setIsDragging(false)
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
        return () => {
            document.removeEventListener('mousemove', onMove)
            document.removeEventListener('mouseup', onUp)
        }
    }, [isDragging, size])

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
            const next = boundedModalRect({ x: newX, y: newY, width: newW, height: newH })
            setSize({ width: next.width, height: next.height })
            setPosition({ x: next.x, y: next.y })
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
                className={`pointer-events-auto absolute flex flex-col overflow-hidden bg-surface-1 dark:border-hairline-tertiary resize-container ${
                    isFullscreen ? 'rounded-none border-0' : 'rounded-xl border-2 border-hairline-strong'
                }`}
                style={{
                    left: isFullscreen ? 0 : position.x,
                    top: isFullscreen ? 0 : position.y,
                    width: isFullscreen ? '100vw' : size.width,
                    height: isFullscreen ? '100dvh' : size.height,
                    maxWidth: '100vw',
                    maxHeight: '100dvh',
                    cursor: isDragging ? 'grabbing' : undefined,
                }}
                data-ai-assistant-modal-window=""
                data-ai-assistant-fullscreen={isFullscreen ? 'true' : 'false'}
            >
                <FactoryAgentChatPanel
                    onClose={onClose}
                    onHeaderMouseDown={handleMouseDown}
                    isFullscreen={isFullscreen}
                    onToggleFullscreen={toggleFullscreen}
                />
                {/* Resize handles - 4 edges + 4 corners */}
                {!isFullscreen ? (
                    <>
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
                    </>
                ) : null}
            </div>
        </div>
    )
}

export default AIAssistantModal
