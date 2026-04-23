const Pagination = ({ currentPage = 1, totalPages = 10, onPageChange }) => {
  const handlePrev = () => {
    if (currentPage > 1 && onPageChange) {
      onPageChange(currentPage - 1)
    }
  }

  const handleNext = () => {
    if (currentPage < totalPages && onPageChange) {
      onPageChange(currentPage + 1)
    }
  }

  const handlePageClick = (page) => {
    if (onPageChange) {
      onPageChange(page)
    }
  }

  // Generate page numbers to show
  const getPageNumbers = () => {
    const pages = []
    
    // Always show first page
    pages.push(1)
    
    // Show pages around current page
    if (currentPage > 3) {
      pages.push('...')
    }
    
    for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
      if (!pages.includes(i)) {
        pages.push(i)
      }
    }
    
    // Show last pages
    if (currentPage < totalPages - 2) {
      pages.push('...')
    }
    
    if (totalPages > 1 && !pages.includes(totalPages)) {
      pages.push(totalPages)
    }
    
    return pages
  }

  const pageNumbers = getPageNumbers()

  return (
    <div className="flex items-center justify-center p-4 mt-4">
      <button
        onClick={handlePrev}
        disabled={currentPage === 1}
        className={`flex size-10 items-center justify-center ${
          currentPage === 1
            ? 'text-gray-600 cursor-not-allowed'
            : 'text-gray-400 hover:text-white'
        }`}
      >
        <span className="material-symbols-outlined text-lg">chevron_left</span>
      </button>

      {pageNumbers.map((page, index) => {
        if (page === '...') {
          return (
            <span
              key={`ellipsis-${index}`}
              className="text-sm font-normal leading-normal flex size-10 items-center justify-center text-white"
            >
              ...
            </span>
          )
        }

        const isActive = page === currentPage

        return (
          <button
            key={page}
            onClick={() => handlePageClick(page)}
            className={`text-sm leading-normal flex size-10 items-center justify-center rounded-full transition-colors ${
              isActive
                ? 'text-black bg-primary font-bold'
                : 'text-white hover:bg-white/10 font-normal'
            }`}
          >
            {page}
          </button>
        )
      })}

      <button
        onClick={handleNext}
        disabled={currentPage === totalPages}
        className={`flex size-10 items-center justify-center ${
          currentPage === totalPages
            ? 'text-gray-600 cursor-not-allowed'
            : 'text-gray-400 hover:text-white'
        }`}
      >
        <span className="material-symbols-outlined text-lg">chevron_right</span>
      </button>
    </div>
  )
}

export default Pagination

