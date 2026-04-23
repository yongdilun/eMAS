const Button = ({ children, variant = 'primary', className = '', ...props }) => {
  const baseClasses = 'px-4 py-2 rounded-lg font-medium transition-all duration-200 hover:scale-105 active:scale-95'
  const variants = {
    primary: 'bg-primary text-dark-blue hover:bg-primary/90 font-bold',
    secondary: 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-white hover:bg-gray-200 dark:hover:bg-gray-700',
    danger: 'bg-red-600 text-white hover:bg-red-700',
    outline: 'border-2 border-primary text-primary hover:bg-primary/10',
  }

  return (
    <button className={`${baseClasses} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  )
}

export default Button


