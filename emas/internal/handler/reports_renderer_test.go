package handler

import "testing"

func TestBuildReportChartPrefersReadableUtilizationSummary(t *testing.T) {
	headers := []string{"Machine ID", "Machine", "Run min", "Down min", "Utilization", "Slots"}
	rows := [][]string{
		{"M-CTG-01", "Coating Station 01", "300.0", "0.0", "62.5%", "5"},
		{"M-PRS-01", "Hydraulic Press 01", "225.0", "15.0", "48.0%", "4"},
	}

	chart := buildReportChart(headers, rows)

	if chart.ValueIndex != 4 {
		t.Fatalf("chart value index = %d, want utilization column", chart.ValueIndex)
	}
	if !chart.IsPercent {
		t.Fatal("chart should treat utilization values as percentages")
	}
	if len(chart.Points) != 2 {
		t.Fatalf("chart points = %d, want 2", len(chart.Points))
	}
	if chart.Points[0].Label != "Coating Station 01" {
		t.Fatalf("first chart label = %q, want machine name", chart.Points[0].Label)
	}
	if chart.Points[0].Display != "62.5%" {
		t.Fatalf("first chart display = %q, want original percent display", chart.Points[0].Display)
	}
}
