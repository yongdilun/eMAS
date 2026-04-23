import { createContext, useContext } from 'react'
import useTheme from '../hooks/useTheme'

const ThemeContext = createContext()

export const ThemeProvider = ({ children }) => {
  const [theme, toggleTheme, setTheme] = useTheme()

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useThemeContext = () => {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useThemeContext must be used within ThemeProvider')
  }
  return context
}


