package schedulereval

import (
	"encoding/json"
	"fmt"
)

func DecodeReport(data []byte) (Report, error) {
	var report Report
	if err := json.Unmarshal(data, &report); err == nil && len(report.Scorecards) > 0 {
		if report.SchemaVersion == 0 {
			report.SchemaVersion = 1
		}
		return report, nil
	}
	var scorecards []Scorecard
	if err := json.Unmarshal(data, &scorecards); err == nil && len(scorecards) > 0 {
		return NewReport(scorecards), nil
	}
	var score Scorecard
	if err := json.Unmarshal(data, &score); err == nil && score.Metadata.ScenarioID != "" {
		return NewReport([]Scorecard{score}), nil
	}
	return Report{}, fmt.Errorf("baseline JSON must be a scheduler eval report, scorecard array, or single scorecard")
}

func ApplyBaseline(scorecards []Scorecard, baseline Report) []Scorecard {
	if len(scorecards) == 0 || len(baseline.Scorecards) == 0 {
		return scorecards
	}
	byKey := map[string]Scorecard{}
	for _, score := range baseline.Scorecards {
		byKey[baselineKey(score)] = score
		if score.Metadata.SchedulerProfile != "" {
			byKey[baselineKeyWithoutProfile(score)] = score
		}
	}
	out := make([]Scorecard, len(scorecards))
	for i, score := range scorecards {
		out[i] = score
		prior, ok := byKey[baselineKey(score)]
		if !ok {
			prior, ok = byKey[baselineKeyWithoutProfile(score)]
		}
		if ok {
			out[i].Stability.BaselineHash = prior.Stability.ScheduleHash
			out[i].Stability.MetricDeltas = metricDeltas(prior, score)
		}
	}
	return out
}

func baselineKey(score Scorecard) string {
	return baselineKeyWithoutProfile(score) + "\x00" + score.Metadata.SchedulerProfile
}

func baselineKeyWithoutProfile(score Scorecard) string {
	return score.Metadata.ScenarioID + "\x00" + score.Metadata.Endpoint
}
