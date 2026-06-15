package featureflags

import "testing"

func TestBatchOrderByDefaultsToProductDeadlineFIFO(t *testing.T) {
	t.Setenv("AI_BATCH_ORDER_BY", "")

	if got := BatchOrderBy(); got != DefaultBatchOrderBy {
		t.Fatalf("BatchOrderBy()=%q, want %q", got, DefaultBatchOrderBy)
	}
}

func TestBatchOrderByHonorsEnvOverride(t *testing.T) {
	t.Setenv("AI_BATCH_ORDER_BY", "FIFO")

	if got := BatchOrderBy(); got != "fifo" {
		t.Fatalf("BatchOrderBy()=%q, want fifo", got)
	}
}
