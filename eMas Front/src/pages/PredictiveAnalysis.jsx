import { useState } from 'react'
import ForecastChart from '../components/features/predictive/ForecastChart'
import HighRiskJobsTable from '../components/features/predictive/HighRiskJobsTable'
import ConfidenceLevel from '../components/features/predictive/ConfidenceLevel'
import AIRecommendations from '../components/features/predictive/AIRecommendations'
import PageHeader from '../components/shared/PageHeader'

const PredictiveAnalysis = () => {
  const [chartMode, setChartMode] = useState('Delays')

  return (
    <div className="flex-1 p-8 overflow-y-auto">
        <PageHeader
          title="Predictive Analysis"
          subtitle="AI-driven insights into potential production issues."
        >
          <button className="flex h-10 items-center gap-2 rounded-lg bg-gray-200 dark:bg-gray-700 px-4 text-gray-900 dark:text-white text-sm font-bold hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors">
            <span className="material-symbols-outlined text-lg">calendar_today</span>
            <span>Set Date Range</span>
          </button>
        </PageHeader>

        {/* Main Grid */}
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left Column */}
          <div className="col-span-1 flex flex-col gap-6 lg:col-span-2">
            {/* Chart Card */}
            <div className="rounded-xl border border-zinc-200 bg-white p-6 dark:border-[#394f56] dark:bg-[#101718]">
              {/* Chart Header */}
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-col">
                  <p className="text-lg font-medium leading-normal text-zinc-900 dark:text-white">
                    Delay & Failure Forecast
                  </p>
                  <p className="text-sm text-zinc-500 dark:text-[#9ab4bc]">
                    Predicted events for the next 24 hours
                  </p>
                </div>

                {/* SegmentedButtons */}
                <div className="flex h-10 w-full shrink-0 items-center justify-center rounded-lg bg-zinc-200 p-1 dark:bg-[#27363a] sm:w-auto">
                  {['Delays', 'Failures'].map((mode) => (
                    <label
                      key={mode}
                      className={`flex h-full grow cursor-pointer items-center justify-center overflow-hidden rounded-lg px-4 text-sm font-medium leading-normal transition-all ${
                        chartMode === mode
                          ? 'bg-white dark:bg-[#101718] text-zinc-900 dark:text-white'
                          : 'text-zinc-500 dark:text-[#9ab4bc]'
                      }`}
                    >
                      <span className="truncate">{mode}</span>
                      <input
                        type="radio"
                        name="chart-toggle"
                        value={mode}
                        checked={chartMode === mode}
                        onChange={(e) => setChartMode(e.target.value)}
                        className="invisible w-0"
                      />
                    </label>
                  ))}
                </div>
              </div>

              {/* Chart Body */}
              <ForecastChart mode={chartMode} />
            </div>

            {/* High-Risk Jobs List */}
            <HighRiskJobsTable />
          </div>

          {/* Right Column */}
          <div className="col-span-1 flex flex-col gap-6">
            {/* Confidence Level */}
            <ConfidenceLevel percentage={85} />

            {/* AI Recommendations */}
            <AIRecommendations />
          </div>
        </div>
    </div>
  )
}

export default PredictiveAnalysis


