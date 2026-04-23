const EmptyState = ({ message, icon, action }) => {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center">
      {icon && <div className="text-6xl mb-4">{icon}</div>}
      <p className="text-gray-600 text-lg mb-4">{message}</p>
      {action && action}
    </div>
  )
}

export default EmptyState


