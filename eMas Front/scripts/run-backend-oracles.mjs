import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontRoot = resolve(scriptDir, '..');
const workspaceRoot = resolve(frontRoot, '..');
const factoryAgentRoot = resolve(workspaceRoot, 'factory-agent');
const pythonCandidates = [
  resolve(workspaceRoot, '.venv', 'Scripts', 'python.exe'),
  resolve(workspaceRoot, '.venv', 'bin', 'python'),
  'python',
];
const python = pythonCandidates.find((candidate) => candidate === 'python' || existsSync(candidate));

const tests = [
  'tests/test_stateful_oracle_schema.py',
  'tests/test_phase18_manual_prompt_bank.py',
  'tests/test_stateful_oracle_harness.py',
  'tests/test_planner_owned_graph_state_contract.py',
  'tests/test_snapshot_timeline_final_response_contract.py',
  'tests/test_phase7_api_ui_alignment.py',
  'tests/test_phase19_prompt_workflow_regression.py',
  'tests/test_summary_bundle.py',
  'tests/test_event_stream_runtime.py',
  'tests/test_hardcode_guardrails.py',
  'tests/test_planner_owned_graph_approval_resume.py::test_manual_regression_create_job_query_renders_manual_input_approval_contract',
];

const missing = tests
  .filter((target) => !target.includes('::'))
  .filter((target) => !existsSync(resolve(factoryAgentRoot, target)));
if (missing.length > 0) {
  console.error(`Missing backend oracle test targets:\n${missing.join('\n')}`);
  process.exit(1);
}

const result = spawnSync(
  python,
  ['-m', 'pytest', ...tests, '-q'],
  {
    cwd: factoryAgentRoot,
    stdio: 'inherit',
    env: {
      ...process.env,
      LANGCHAIN_TRACING_V2: 'false',
      LANGSMITH_TRACING: 'false',
    },
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
