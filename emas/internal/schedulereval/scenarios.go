package schedulereval

import "sort"

const (
	ScenarioCanonicalSeed        = "canonical_seed"
	ScenarioTrueMaterialShortage = "true_material_shortage"
	ScenarioDelayedMaterialWait  = "delayed_material_wait"
	ScenarioChildBOMShortage     = "child_bom_shortage"
	ScenarioNoShortageControl    = "no_shortage_control"
	ScenarioResourceOverload     = "resource_overload"
	ScenarioOneShotResolution    = "one_shot_resolution"
)

type ScenarioDefinition struct {
	ID          string              `json:"id"`
	Description string              `json:"description"`
	Tags        []string            `json:"tags,omitempty"`
	Expect      ScenarioExpectation `json:"expect"`
}

type ScenarioExpectation struct {
	AllowHardFailures            bool     `json:"allow_hard_failures"`
	ExpectAllFeasible            bool     `json:"expect_all_feasible"`
	ExpectSomeInfeasible         bool     `json:"expect_some_infeasible"`
	ExpectNoMaterialShortage     bool     `json:"expect_no_material_shortage"`
	ExpectMaterialShortage       bool     `json:"expect_material_shortage"`
	ExpectNoAggregateRows        bool     `json:"expect_no_aggregate_rows"`
	ExpectAggregateRows          bool     `json:"expect_aggregate_rows"`
	RequiredAggregateMaterialIDs []string `json:"required_aggregate_material_ids,omitempty"`
	RequireShortageEvidence      bool     `json:"require_shortage_evidence"`
	RequireAllFeasibleHaveSlots  bool     `json:"require_all_feasible_have_slots"`
}

func V1Scenarios() []ScenarioDefinition {
	return []ScenarioDefinition{
		{
			ID:          ScenarioCanonicalSeed,
			Description: "Exact cmd/seed canonical dataset; used as the broad baseline scorecard.",
			Tags:        []string{"canonical", "baseline"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectAllFeasible:           true,
				ExpectNoMaterialShortage:    true,
				ExpectNoAggregateRows:       true,
				RequireShortageEvidence:     true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioTrueMaterialShortage,
			Description: "Demand exceeds current plus future material supply; affected jobs must be infeasible with actionable material evidence.",
			Tags:        []string{"material", "shortage"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectSomeInfeasible:        true,
				ExpectMaterialShortage:      true,
				ExpectAggregateRows:         true,
				RequireShortageEvidence:     true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioDelayedMaterialWait,
			Description: "Material exists later; scheduler should wait rather than falsely mark the job infeasible.",
			Tags:        []string{"material", "wait"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				RequireShortageEvidence:     true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioChildBOMShortage,
			Description: "Parent needs a child product whose raw materials are missing; evidence must trace to raw materials.",
			Tags:        []string{"material", "bom", "child-product"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectMaterialShortage:      true,
				ExpectAggregateRows:         true,
				RequireShortageEvidence:     true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioNoShortageControl,
			Description: "Enough material and capacity; no proposals should be material-infeasible.",
			Tags:        []string{"control"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectAllFeasible:           true,
				ExpectNoMaterialShortage:    true,
				ExpectNoAggregateRows:       true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioResourceOverload,
			Description: "Enough materials but limited machines; late work is allowed, material false positives are not.",
			Tags:        []string{"resource", "capacity"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectNoMaterialShortage:    true,
				ExpectNoAggregateRows:       true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
		{
			ID:          ScenarioOneShotResolution,
			Description: "Apply recommended material rows, rerun scheduler, and require no remaining material infeasible jobs.",
			Tags:        []string{"material", "resolution", "regression"},
			Expect: ScenarioExpectation{
				AllowHardFailures:           false,
				ExpectAllFeasible:           true,
				ExpectNoMaterialShortage:    true,
				ExpectNoAggregateRows:       true,
				RequireShortageEvidence:     true,
				RequireAllFeasibleHaveSlots: true,
			},
		},
	}
}

func ScenarioByID(id string) (ScenarioDefinition, bool) {
	for _, scenario := range V1Scenarios() {
		if scenario.ID == id {
			return scenario, true
		}
	}
	return ScenarioDefinition{}, false
}

func ScenarioIDs() []string {
	scenarios := V1Scenarios()
	ids := make([]string, 0, len(scenarios))
	for _, scenario := range scenarios {
		ids = append(ids, scenario.ID)
	}
	sort.Strings(ids)
	return ids
}

func ValidateScenarioExpectation(score Scorecard, expect ScenarioExpectation) []Finding {
	var findings []Finding
	add := func(code, message string) {
		findings = append(findings, Finding{Code: code, Severity: SeverityError, Message: message})
	}
	if !expect.AllowHardFailures && len(score.Failures) > 0 {
		add("hard_failures_present", "scorecard contains hard correctness failures")
	}
	if expect.ExpectAllFeasible && score.Feasibility.InfeasibleJobs > 0 {
		add("expected_all_feasible", "scenario expected all jobs feasible")
	}
	if expect.ExpectSomeInfeasible && score.Feasibility.InfeasibleJobs == 0 {
		add("expected_some_infeasible", "scenario expected at least one infeasible job")
	}
	if expect.ExpectNoMaterialShortage && hasMaterialShortage(score) {
		add("unexpected_material_shortage", "scenario expected no material shortage evidence or aggregate rows")
	}
	if expect.ExpectMaterialShortage && !hasMaterialShortage(score) {
		add("expected_material_shortage", "scenario expected material shortage evidence")
	}
	if expect.ExpectNoAggregateRows && score.Material.AggregateReplenishmentCount > 0 {
		add("unexpected_aggregate_rows", "scenario expected no material replenishment aggregate rows")
	}
	if expect.ExpectAggregateRows && score.Material.AggregateReplenishmentCount == 0 {
		add("expected_aggregate_rows", "scenario expected material replenishment aggregate rows")
	}
	if expect.RequireShortageEvidence && score.Feasibility.InfeasibleWithoutShortageEvidence > 0 {
		add("shortage_evidence_required", "material-shortage infeasible jobs must include actionable evidence")
	}
	if expect.RequireAllFeasibleHaveSlots && score.Feasibility.FeasibleWithoutSlots > 0 {
		add("feasible_slots_required", "feasible jobs must have scheduled slots")
	}
	if len(expect.RequiredAggregateMaterialIDs) > 0 {
		missing := missingStrings(expect.RequiredAggregateMaterialIDs, score.Material.AggregateMaterialIDs)
		if len(missing) > 0 {
			add("missing_required_aggregate_materials", "aggregate rows missing required materials: "+joinComma(missing))
		}
	}
	return findings
}

func hasMaterialShortage(score Scorecard) bool {
	return score.Material.MaterialShortageProposalCount > 0 ||
		score.Material.MaterialShortageCount > 0 ||
		score.Material.AggregateReplenishmentCount > 0
}

func missingStrings(required, got []string) []string {
	seen := map[string]struct{}{}
	for _, value := range got {
		seen[value] = struct{}{}
	}
	missing := make([]string, 0)
	for _, value := range required {
		if _, ok := seen[value]; !ok {
			missing = append(missing, value)
		}
	}
	sort.Strings(missing)
	return missing
}

func joinComma(values []string) string {
	sort.Strings(values)
	out := ""
	for i, value := range values {
		if i > 0 {
			out += ", "
		}
		out += value
	}
	return out
}
