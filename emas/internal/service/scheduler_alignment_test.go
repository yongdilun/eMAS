package service

import (
	"emas/internal/domain"
	"testing"
	"time"
)

func TestRoundUpToHalfHourAndAlignSuccessorStart(t *testing.T) {
	base := time.Date(2026, 4, 3, 10, 10, 0, 0, time.UTC)
	got := roundUpToHalfHour(base)
	want := time.Date(2026, 4, 3, 10, 30, 0, 0, time.UTC)
	if !got.Equal(want) {
		t.Fatalf("roundUpToHalfHour: want %s, got %s", want, got)
	}
	if !alignSuccessorStart(base).Equal(want) {
		t.Fatalf("alignSuccessorStart: want %s, got %s", want, alignSuccessorStart(base))
	}
}

func TestCeilDurationTo30MinAndMetrics(t *testing.T) {
	actual := 31 * time.Minute
	got := ceilDurationTo30Min(actual)
	if got != 60*time.Minute {
		t.Fatalf("ceilDurationTo30Min: want 60m, got %s", got)
	}
	metrics := stepDurationMetrics(domain.ProcessSteps{DefaultProcessingTime: 31}, nil, 1)
	if metrics.ActualDuration != 31*time.Minute {
		t.Fatalf("actual duration: want 31m, got %s", metrics.ActualDuration)
	}
	if metrics.ReservedDuration != 60*time.Minute {
		t.Fatalf("reserved duration: want 60m, got %s", metrics.ReservedDuration)
	}
	if metrics.RoundingOverhead != 29*time.Minute {
		t.Fatalf("rounding overhead: want 29m, got %s", metrics.RoundingOverhead)
	}
}

func TestNextAlignedWorkStartSkipsBlockedIntervalsAndOffShift(t *testing.T) {
	work := []BusyInterval{
		{Start: time.Date(2026, 4, 3, 8, 0, 0, 0, time.UTC), End: time.Date(2026, 4, 3, 12, 0, 0, 0, time.UTC)},
		{Start: time.Date(2026, 4, 3, 13, 0, 0, 0, time.UTC), End: time.Date(2026, 4, 3, 17, 0, 0, 0, time.UTC)},
	}
	blocked := []BusyInterval{
		{Start: time.Date(2026, 4, 3, 8, 30, 0, 0, time.UTC), End: time.Date(2026, 4, 3, 9, 0, 0, 0, time.UTC)},
	}
	got, ok := nextAlignedWorkStart(time.Date(2026, 4, 3, 8, 40, 0, 0, time.UTC), work, blocked, time.UTC)
	if !ok {
		t.Fatal("expected aligned work start to be found")
	}
	want := time.Date(2026, 4, 3, 9, 0, 0, 0, time.UTC)
	if !got.Equal(want) {
		t.Fatalf("blocked interval skip: want %s, got %s", want, got)
	}

	got, ok = nextAlignedWorkStart(time.Date(2026, 4, 3, 12, 10, 0, 0, time.UTC), work, nil, time.UTC)
	if !ok {
		t.Fatal("expected afternoon aligned work start to be found")
	}
	want = time.Date(2026, 4, 3, 13, 0, 0, 0, time.UTC)
	if !got.Equal(want) {
		t.Fatalf("off-shift skip: want %s, got %s", want, got)
	}
}

func TestRepairOverlapsInProposalsAlignsShiftedSlots(t *testing.T) {
	base := time.Date(2026, 4, 3, 8, 0, 0, 0, time.UTC)
	p1 := &SchedulingProposal{
		JobID: "J1",
		ProposedSlots: []ProposedSlot{
			{MachineID: "M1", ScheduledStart: base, ScheduledEnd: base.Add(60 * time.Minute)},
		},
	}
	p2 := &SchedulingProposal{
		JobID:         "J2",
		EarliestStart: base.Add(45 * time.Minute),
		ProposedSlots: []ProposedSlot{
			{MachineID: "M1", ScheduledStart: base.Add(45 * time.Minute), ScheduledEnd: base.Add(105 * time.Minute)},
		},
	}
	if !repairOverlapsInProposals([]*SchedulingProposal{p1, p2}) {
		t.Fatal("expected overlap repair to modify proposals")
	}
	if !isHalfHourAligned(p2.ProposedSlots[0].ScheduledStart) || !isHalfHourAligned(p2.ProposedSlots[0].ScheduledEnd) {
		t.Fatalf("expected repaired slot to stay on half-hour grid, got %s -> %s", p2.ProposedSlots[0].ScheduledStart, p2.ProposedSlots[0].ScheduledEnd)
	}
	if p2.ProposedSlots[0].ScheduledStart.Before(p1.ProposedSlots[0].ScheduledEnd) {
		t.Fatalf("expected repaired slot to avoid overlap, got %s before %s", p2.ProposedSlots[0].ScheduledStart, p1.ProposedSlots[0].ScheduledEnd)
	}
}
