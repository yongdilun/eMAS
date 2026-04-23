const ChatSidebar = ({ conversations = [], activeChatId, onSelectChat, onNewConversation, loading }) => {
  const formatDate = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      const now = new Date()
      const diff = now - d
      if (diff < 86400000) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      if (diff < 604800000) return d.toLocaleDateString([], { weekday: 'short' })
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    } catch {
      return ''
    }
  }

  return (
    <aside className="w-52 shrink-0 flex flex-col bg-gray-50 dark:bg-[#0f1619] border-r border-gray-200/80 dark:border-gray-800/80 p-4 overflow-y-auto">
      <div className="flex flex-col gap-4">
        <button
          type="button"
          onClick={onNewConversation}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-white text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-lg">add</span>
          New Conversation
        </button>

        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
            Recent Chats
          </h3>
          {loading && conversations.length === 0 ? (
            <div className="px-3 py-4 text-center text-sm text-gray-500 dark:text-gray-400">
              Loading…
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center text-center py-6">
              <div className="w-16 h-16 rounded-full bg-gray-200 dark:bg-[#283539] flex items-center justify-center mb-3">
                <span className="material-symbols-outlined text-3xl text-gray-500 dark:text-gray-400">
                  forum
                </span>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">No conversations yet</p>
              <button
                type="button"
                onClick={onNewConversation}
                disabled={loading}
                className="px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60"
              >
                Start your first chat
              </button>
            </div>
          ) : (
            <ul className="space-y-1">
              {conversations.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => onSelectChat(c.id)}
                    className={`w-full text-left px-3 py-2 rounded-xl text-sm transition-colors truncate border ${
                      c.id === activeChatId
                        ? 'bg-primary/15 text-primary dark:bg-primary/25 border-primary/30'
                        : 'text-gray-700 dark:text-[#9cb3ba] hover:bg-gray-200/80 dark:hover:bg-[#283539]/80 border-transparent hover:border-gray-200 dark:hover:border-gray-700'
                    }`}
                  >
                    <div className="truncate">{c.title || 'Conversation'}</div>
                    {c.updated_at || c.created_at ? (
                      <div className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">
                        {formatDate(c.updated_at || c.created_at)}
                      </div>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </aside>
  )
}

export default ChatSidebar
