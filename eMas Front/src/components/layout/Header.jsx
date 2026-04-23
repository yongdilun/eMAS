import { Link } from 'react-router-dom'
import MobileMenu from './MobileMenu'
import logoHori from '../../assets/logoHori.png'

const Header = () => {
  return (
    <header className="bg-background-light dark:bg-[#0A192F] border-b border-gray-200 dark:border-gray-800 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <MobileMenu />
          <Link to="/" className="flex items-center group lg:hidden">
            <img
              src={logoHori}
              alt="eMAS Logo"
              className="h-8 w-auto object-contain transition-transform group-hover:scale-105"
            />
          </Link>
        </div>
        <div className="flex items-center space-x-4">
          {/* User profile, notifications, theme toggle, etc. */}
        </div>
      </div>
    </header>
  )
}

export default Header


