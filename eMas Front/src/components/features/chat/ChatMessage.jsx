/**
 * Chat message with avatar, timestamp, content, and optional embedded blocks.
 */
const ChatMessage = ({
  message,
  isUser = false,
  timestamp,
  renderBlocks,
}) => {
  return (
    <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'} mb-4`}>
      <div
        className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          isUser
            ? 'bg-primary/20 text-primary'
            : 'bg-gray-200 dark:bg-[#283539] text-gray-600 dark:text-gray-400'
        }`}
      >
        <span
          className="material-symbols-outlined text-lg"
          style={!isUser ? { fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24" } : {}}
        >
          {isUser ? 'person' : 'smart_toy'}
        </span>
      </div>
      <div
        className={`flex flex-col max-w-[80%] ${isUser ? 'items-end' : 'items-start'}`}
      >
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
            {isUser ? 'You' : 'eMAS AI'}
          </span>
          {timestamp && (
            <span className="text-[10px] text-gray-400 dark:text-gray-500">
              {timestamp}
            </span>
          )}
        </div>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
            isUser
              ? 'bg-primary text-white rounded-br-sm'
              : 'bg-white dark:bg-gray-800/90 text-gray-900 dark:text-gray-100 rounded-bl-sm border border-gray-200/80 dark:border-gray-700/80'
          }`}
        >
          <div className="whitespace-pre-wrap break-words">{message}</div>
          {renderBlocks?.()}
        </div>
      </div>
    </div>
  )
}

export default ChatMessage
