# eMas - Manufacturing Management System

A modern manufacturing management system built with React, Vite, and Tailwind CSS.

## Features

- Dashboard with KPIs, Alerts, and Charts
- AI Assistant Chat
- Job Scheduling with Gantt Chart
- Production Data Visualization
- Predictive Analysis
- Reports Generation
- Machine & Resources Management
- Storage & Inventory Management
- Forms for Jobs/Users/Data
- Settings (Theme, Language)

## Getting Started

### Prerequisites

- Node.js 18+ 
- npm or yarn

### Installation

```bash
npm install
```

### Development

```bash
npm run dev
```

### Build

```bash
npm run build
```

### Tests

Component and utility tests:

```bash
npm test
```

Deterministic browser chatbot validation:

```bash
npm run test:e2e -- --project=chromium
```

The Playwright chatbot suite replaces manual browser typing, waiting, and final DOM checking for the Factory Agent chat modal. It runs the Vite app against a mocked Factory Agent REST/SSE server, so it does not require the real Go API, real Factory Agent, Docker, RAG, or LLM calls.

For a quick smoke against a real Factory Agent HTTP endpoint, use:

```bash
npm run factory-agent-smoke
```

That smoke script remains API-only. Use Playwright for browser/modal validation.

## Project Structure

```
src/
├── components/       # Reusable components
├── pages/           # Page components
├── hooks/           # Custom React hooks
├── services/        # API services
├── utils/           # Utility functions
├── types/           # TypeScript types
├── context/         # React Context providers
├── assets/          # Static assets
└── styles/          # Global styles
```


