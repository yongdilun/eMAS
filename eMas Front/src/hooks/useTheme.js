import { useState, useEffect } from 'react'
import useLocalStorage from './useLocalStorage'

const useTheme = () => {
  const [theme, setTheme] = useLocalStorage('theme', 'dark')

  useEffect(() => {
    const root = window.document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }

  const setThemeValue = (value) => {
    if (value === 'light' || value === 'dark') setTheme(value)
  }

  return [theme, toggleTheme, setThemeValue]
}

export default useTheme


