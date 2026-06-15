package schedulereval

const (
	SchedulerProfileV1Current               = "v1-current"
	SchedulerProfileV2MaterialAwarePriority = "v2-material-aware-priority"
	SchedulerProfileV3WeightedTardiness     = "v3-weighted-tardiness-material"
	SchedulerProfileV4ProductDeadlineFIFO   = "v4-product-deadline-fifo"
)

type SchedulerProfileDefinition struct {
	ID          string `json:"id"`
	Description string `json:"description"`
	OrderBy     string `json:"order_by"`
}

func SchedulerProfiles() []SchedulerProfileDefinition {
	return []SchedulerProfileDefinition{
		{
			ID:          SchedulerProfileV1Current,
			Description: "Current production-style priority/deadline order.",
			OrderBy:     "epo",
		},
		{
			ID:          SchedulerProfileV2MaterialAwarePriority,
			Description: "Priority-first order that uses material readiness before deadline inside the same priority.",
			OrderBy:     "material_priority",
		},
		{
			ID:          SchedulerProfileV3WeightedTardiness,
			Description: "Age/material-pressure order that treats older released jobs as higher tardiness risk.",
			OrderBy:     "weighted_tardiness_material",
		},
		{
			ID:          SchedulerProfileV4ProductDeadlineFIFO,
			Description: "FIFO/material order that pulls tighter-deadline work forward inside the same product family.",
			OrderBy:     "product_deadline_fifo",
		},
	}
}

func SchedulerProfileByID(id string) (SchedulerProfileDefinition, bool) {
	for _, profile := range SchedulerProfiles() {
		if profile.ID == id {
			return profile, true
		}
	}
	return SchedulerProfileDefinition{}, false
}

func SchedulerProfileIDs() []string {
	profiles := SchedulerProfiles()
	ids := make([]string, 0, len(profiles))
	for _, profile := range profiles {
		ids = append(ids, profile.ID)
	}
	return ids
}
