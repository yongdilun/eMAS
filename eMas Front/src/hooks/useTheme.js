import { useEffect, useCallback } from 'react'
import useLocalStorage from './useLocalStorage'

const useTheme = () => {
  const [theme, setTheme] = useLocalStorage('theme', 'light')

  useEffect(() => {
    const root = window.document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
      root.classList.remove('light')
    } else {
      root.classList.add('light')
      root.classList.remove('dark')
    }
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }, [setTheme])

  const setThemeValue = useCallback((value) => {
    if (value === 'light' || value === 'dark') setTheme(value)
  }, [setTheme])

  return [theme, toggleTheme, setThemeValue]
}

export default useTheme


