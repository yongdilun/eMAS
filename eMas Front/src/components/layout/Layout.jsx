import Sidebar from './Sidebar'

const Layout = ({ children }) => {
  return (
    <div className="relative flex h-screen w-full overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col bg-background-light dark:bg-background-dark overflow-hidden">
        {children}
      </main>
    </div>
  )
}

export default Layout


