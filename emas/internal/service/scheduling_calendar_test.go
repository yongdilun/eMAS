package service

import (
	"emas/internal/domain"
	"emas/internal/repository"
	"emas/internal/testutil"
	"testing"
	"time"
)

func Test_settingsWorkWindows_ExcludesNonWorkday(t *testing.T) {
	db := testutil.NewTestDB(t)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	_ = settingsRepo.PutString("scheduling.work_start_time", "08:00")
	_ = settingsRepo.PutString("scheduling.work_end_time", "17:00")
	_ = settingsRepo.PutString("scheduling.work_days", "1,2,3,4,5")

	svc := &SchedulingService{settingsRepo: settingsRepo}
	// Sunday in local time.
	from := time.Date(2026, 3, 29, 0, 0, 0, 0, time.Local)
	to := from.Add(24 * time.Hour)
	windows := svc.settingsWorkWindows(from, to)
	if len(windows) != 0 {
		t.Fatalf("expected no work windows on non-workday, got %d", len(windows))
	}
}

func Test_machineWorkWindows_IntersectsWithGlobalHoliday(t *testing.T) {
	db := testutil.NewTestDB(t)
	machineRepo := repository.NewMachineRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)

	holidayDate := "2026-04-01"
	_ = settingsRepo.PutString("scheduling.work_start_time", "08:00")
	_ = settingsRepo.PutString("scheduling.work_end_time", "17:00")
	_ = settingsRepo.PutString("scheduling.work_days", "0,1,2,3,4,5,6")
	_ = settingsRepo.PutString("scheduling.public_holidays", "[\""+holidayDate+"\"]")

	m := &domain.Machine{
		MachineID:       "M-CAL-01",
		MachineName:     "Calendar Test Machine",
		MachineType:     "CNC",
		Status:          domain.MachineStatusIdle,
		CapacityPerHour: 10,
	}
	if err := machineRepo.Create(m); err != nil {
		t.Fatalf("create machine: %v", err)
	}
	workStart := time.Date(2026, 4, 1, 8, 0, 0, 0, time.Local)
	workEnd := time.Date(2026, 4, 1, 17, 0, 0, 0, time.Local)
	if err := machineRepo.CreateCalendar(domain.MachineCalendar{
		CalendarID:       "MCAL-1",
		MachineID:        m.MachineID,
		StartTime:        workStart,
		EndTime:          workEnd,
		AvailabilityType: "work",
		ShiftName:        "A",
	}); err != nil {
		t.Fatalf("create machine calendar: %v", err)
	}

	svc := &SchedulingService{machineRepo: machineRepo, settingsRepo: settingsRepo}
	windows := svc.machineWorkWindows(m.MachineID, workStart, workEnd)
	if len(windows) != 0 {
		t.Fatalf("expected zero windows due to global holiday intersection, got %d", len(windows))
	}
}

