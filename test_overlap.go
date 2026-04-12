package main

import (
	"fmt"
	"time"
)

type ProposedSlot struct {
	MachineID      string
	ScheduledStart time.Time
	ScheduledEnd   time.Time
}

type SchedulingProposal struct {
	JobID         string
	ProposedSlots []ProposedSlot
}

func alignSuccessorStart(ts time.Time) time.Time {
	if ts.IsZero() {
		return ts
	}
	step := 30 * time.Minute
	base := ts.Truncate(step)
	if base.Equal(ts) {
		return ts
	}
	return base.Add(step)
}

func ceilDurationTo30Min(d time.Duration) time.Duration {
	if d <= 0 {
		return 30 * time.Minute
	}
	if d%(30*time.Minute) == 0 {
		return d
	}
	return ((d / (30 * time.Minute)) + 1) * (30 * time.Minute)
}

func main() {
	now := time.Now().UTC().Truncate(time.Hour)
	proposals := []*SchedulingProposal{
		{
			JobID: "job1",
			ProposedSlots: []ProposedSlot{
				{MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(2 * time.Hour)},
			},
		},
		{
			JobID: "job2",
			ProposedSlots: []ProposedSlot{
				{MachineID: "M1", ScheduledStart: now, ScheduledEnd: now.Add(30 * time.Minute)},
			},
		},
	}

	machineCursor := map[string]time.Time{}
	for _, p := range proposals {
		for i := range p.ProposedSlots {
			slot := &p.ProposedSlots[i]
			cursor := machineCursor[slot.MachineID]
			if cursor.IsZero() || !slot.ScheduledStart.Before(cursor) {
				if slot.ScheduledEnd.After(cursor) {
					machineCursor[slot.MachineID] = slot.ScheduledEnd
				}
				continue
			}
			delta := cursor.Sub(slot.ScheduledStart)
			duration := ceilDurationTo30Min(slot.ScheduledEnd.Sub(slot.ScheduledStart))
			slot.ScheduledStart = alignSuccessorStart(slot.ScheduledStart.Add(delta))
			slot.ScheduledEnd = slot.ScheduledStart.Add(duration)
			machineCursor[slot.MachineID] = slot.ScheduledEnd
		}
	}

	type slotRef struct {
		start time.Time
		end   time.Time
		job   string
	}
	var slots []slotRef
	for _, p := range proposals {
		for _, ps := range p.ProposedSlots {
			slots = append(slots, slotRef{start: ps.ScheduledStart, end: ps.ScheduledEnd, job: p.JobID})
		}
	}
	for i := 1; i < len(slots); i++ {
		fmt.Printf("%s: %v -> %v\n", slots[i-1].job, slots[i-1].start, slots[i-1].end)
		fmt.Printf("%s: %v -> %v\n", slots[i].job, slots[i].start, slots[i].end)
		if slots[i].start.Before(slots[i-1].end) {
			fmt.Println("OVERLAP DETECTED!")
		} else {
			fmt.Println("No overlap")
		}
	}
}
