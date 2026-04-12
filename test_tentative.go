package main

import "fmt"

type TentativeSlot struct {
	MachineID string
	Start     int
	End       int
}

type ProposedSlot struct {
	MachineID string
	Start     int
	End       int
}

type SchedulingProposal struct {
	JobID string
	Slots []ProposedSlot
}

func tentativesForChainRepair(proposals []*SchedulingProposal, currentProposal *SchedulingProposal, currentIndex int) []TentativeSlot {
	n := 0
	for _, p := range proposals {
		if p == nil { continue }
		limit := len(p.Slots)
		if p == currentProposal {
			if currentIndex < 0 { limit = 0 } else if currentIndex < limit { limit = currentIndex }
		}
		for i := 0; i < limit; i++ {
			if p.Slots[i].MachineID == "" { continue }
			n++
		}
	}
	out := make([]TentativeSlot, 0, n)
	for _, p := range proposals {
		if p == nil { continue }
		limit := len(p.Slots)
		if p == currentProposal {
			if currentIndex < 0 { limit = 0 } else if currentIndex < limit { limit = currentIndex }
		}
		for i := 0; i < limit; i++ {
			if p.Slots[i].MachineID == "" { continue }
			out = append(out, TentativeSlot{
				MachineID: p.Slots[i].MachineID,
				Start:     p.Slots[i].Start,
				End:       p.Slots[i].End,
			})
		}
	}
	return out
}

func main() {
	p1 := &SchedulingProposal{JobID: "p1", Slots: []ProposedSlot{{MachineID: "M1", Start: 1, End: 2}, {MachineID: "M2", Start: 2, End: 3}}}
	p2 := &SchedulingProposal{JobID: "p2", Slots: []ProposedSlot{{MachineID: "M1", Start: 5, End: 6}}}
	
	proposals := []*SchedulingProposal{p1, p2}
	
	res := tentativesForChainRepair(proposals, p1, 1) // Repairing p1's slot 1 (M2) 
	fmt.Printf("Repairing P1 Slot 1:\n")
	for _, r := range res {
		fmt.Printf(" - %s: %d -> %d\n", r.MachineID, r.Start, r.End)
	}

	res2 := tentativesForChainRepair(proposals, p2, 0) // Repairing p2's slot 0 (M1)
	fmt.Printf("Repairing P2 Slot 0:\n")
	for _, r := range res2 {
		fmt.Printf(" - %s: %d -> %d\n", r.MachineID, r.Start, r.End)
	}
}
