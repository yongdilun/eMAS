const ProductionOutputChart = () => {
  return (
    <div className="flex min-h-[120px] flex-1 flex-col gap-3 py-2">
      <svg
        fill="none"
        height="100"
        preserveAspectRatio="none"
        viewBox="-3 0 478 150"
        width="100%"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M0 109C18.1538 109 18.1538 21 36.3077 21C54.4615 21 54.4615 41 72.6154 41C90.7692 41 90.7692 93 108.923 93C127.077 93 127.077 33 145.231 33C163.385 33 163.385 101 181.538 101C199.692 101 199.692 61 217.846 61C236 61 236 45 254.154 45C272.308 45 272.308 121 290.462 121C308.615 121 308.615 149 326.769 149C344.923 149 344.923 1 363.077 1C381.231 1 381.231 81 399.385 81C417.538 81 417.538 129 435.692 129C453.846 129 453.846 25 472 25V149H326.769H0V109Z"
          fill="url(#paint0_linear_1131_5935)"
        />
        <path
          d="M0 109C18.1538 109 18.1538 21 36.3077 21C54.4615 21 54.4615 41 72.6154 41C90.7692 41 90.7692 93 108.923 93C127.077 93 127.077 33 145.231 33C163.385 33 163.385 101 181.538 101C199.692 101 199.692 61 217.846 61C236 61 236 45 254.154 45C272.308 45 272.308 121 290.462 121C308.615 121 308.615 149 326.769 149C344.923 149 344.923 1 363.077 1C381.231 1 381.231 81 399.385 81C417.538 81 417.538 129 435.692 129C453.846 129 453.846 25 472 25"
          stroke="#00c3ff"
          strokeLinecap="round"
          strokeWidth="3.5"
        />
        <defs>
          <linearGradient
            gradientUnits="userSpaceOnUse"
            id="paint0_linear_1131_5935"
            x1="236"
            x2="236"
            y1="1"
            y2="149"
          >
            <stop stopColor="#00c3ff" stopOpacity="0.4" />
            <stop offset="1" stopColor="#00c3ff" stopOpacity="0.05" />
          </linearGradient>
        </defs>
      </svg>
      <div className="flex justify-around mt-1">
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day) => (
          <p
            key={day}
            className="text-gray-500 dark:text-gray-400 text-xs font-semibold leading-normal tracking-[0.015em]"
          >
            {day}
          </p>
        ))}
      </div>
    </div>
  )
}

export default ProductionOutputChart

