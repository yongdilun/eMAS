package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	"emas/config"
	"emas/internal/domain"
	"emas/internal/repository"

	"gorm.io/gorm"
)

type verifyIssue struct {
	JobID    string  `json:"job_id,omitempty"`
	Subject  string  `json:"subject"`
	Expected float64 `json:"expected,omitempty"`
	Actual   float64 `json:"actual,omitempty"`
	Message  string  `json:"message"`
}

type verifyResult struct {
	JobPrefix string        `json:"job_prefix"`
	OK        bool          `json:"ok"`
	JobCount  int           `json:"job_count"`
	Issues    []verifyIssue `json:"issues,omitempty"`
}

func main() {
	jobPrefix := flag.String("job-prefix", "JOB-RPT-", "job_id prefix to verify")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		log.Fatal("config:", err)
	}
	db, err := repository.InitDB(cfg)
	if err != nil {
		log.Fatal("db:", err)
	}

	result := verifyProductionFlow(db, strings.TrimSpace(*jobPrefix))
	out, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		log.Fatal("encode result:", err)
	}
	fmt.Println(string(out))
	if !result.OK {
		os.Exit(1)
	}
}

func verifyProductionFlow(db *gorm.DB, jobPrefix string) verifyResult {
	result := verifyResult{JobPrefix: jobPrefix}
	var jobs []domain.Job
	if err := db.Where("job_id LIKE ?", jobPrefix+"%").Order("job_id ASC").Find(&jobs).Error; err != nil {
		result.Issues = append(result.Issues, verifyIssue{Subject: "jobs", Message: err.Error()})
		result.OK = false
		return result
	}
	result.JobCount = len(jobs)
	if len(jobs) == 0 {
		result.Issues = append(result.Issues, verifyIssue{Subject: "jobs", Message: "no matching jobs"})
		result.OK = false
		return result
	}

	var activeSlots int64
	if err := db.Table("job_step_schedule_slots AS s").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Where("js.job_id LIKE ?", jobPrefix+"%").
		Where("s.status IN ?", []string{domain.SlotStatusPlanned, domain.SlotStatusRunning, domain.SlotStatusPaused}).
		Count(&activeSlots).Error; err != nil {
		result.Issues = append(result.Issues, verifyIssue{Subject: "active_slots", Message: err.Error()})
	} else if activeSlots != 0 {
		result.Issues = append(result.Issues, verifyIssue{Subject: "active_slots", Expected: 0, Actual: float64(activeSlots), Message: "matching jobs still have active slots"})
	}

	for _, job := range jobs {
		if job.Status != domain.JobStatusCompleted {
			result.Issues = append(result.Issues, verifyIssue{JobID: job.JobID, Subject: "job.status", Message: "job is not completed"})
		}
		if job.QuantityCompleted < job.QuantityTotal {
			result.Issues = append(result.Issues, verifyIssue{JobID: job.JobID, Subject: "job.quantity_completed", Expected: float64(job.QuantityTotal), Actual: float64(job.QuantityCompleted), Message: "job quantity is not fully completed"})
		}
		var logCount int64
		if err := db.Table("production_logs AS pl").
			Joins("JOIN job_step_schedule_slots s ON s.slot_id = pl.slot_id").
			Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
			Where("js.job_id = ?", job.JobID).
			Count(&logCount).Error; err != nil {
			result.Issues = append(result.Issues, verifyIssue{JobID: job.JobID, Subject: "production_logs", Message: err.Error()})
		} else if logCount == 0 {
			result.Issues = append(result.Issues, verifyIssue{JobID: job.JobID, Subject: "production_logs", Message: "job has no production logs"})
		}
		verifyMaterialConsumption(db, job.JobID, &result)
	}
	verifyFinishedGoods(db, jobPrefix, &result)
	result.OK = len(result.Issues) == 0
	return result
}

func verifyMaterialConsumption(db *gorm.DB, jobID string, result *verifyResult) {
	type materialNeed struct {
		MaterialID string
		Required   float64
	}
	var needs []materialNeed
	if err := db.Table("production_logs AS pl").
		Select("psm.material_id, COALESCE(SUM((pl.quantity_produced + pl.quantity_scrap) * psm.quantity_per_unit), 0) AS required").
		Joins("JOIN job_step_schedule_slots s ON s.slot_id = pl.slot_id").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Joins("JOIN process_step_materials psm ON psm.step_id = js.step_id AND psm.role = ? AND psm.material_id IS NOT NULL", domain.ProcessStepMaterialRoleInput).
		Where("js.job_id = ?", jobID).
		Group("psm.material_id").
		Scan(&needs).Error; err != nil {
		result.Issues = append(result.Issues, verifyIssue{JobID: jobID, Subject: "material.required", Message: err.Error()})
		return
	}
	for _, need := range needs {
		var consumed float64
		if err := db.Model(&domain.InventoryTransactions{}).
			Where("reference_job_id = ? AND material_id = ? AND transaction_type = ?", jobID, need.MaterialID, domain.TransactionTypeConsume).
			Select("COALESCE(SUM(quantity), 0)").
			Scan(&consumed).Error; err != nil {
			result.Issues = append(result.Issues, verifyIssue{JobID: jobID, Subject: "material.consumed", Message: err.Error()})
			continue
		}
		if !closeEnough(consumed, need.Required) {
			result.Issues = append(result.Issues, verifyIssue{JobID: jobID, Subject: "material." + need.MaterialID, Expected: need.Required, Actual: consumed, Message: "consume transaction quantity does not match production log material requirement"})
		}
	}
}

func verifyFinishedGoods(db *gorm.DB, jobPrefix string, result *verifyResult) {
	type productOutput struct {
		ProductID string
		Produced  float64
	}
	var outputs []productOutput
	if err := db.Table("production_logs AS pl").
		Select("psm.product_id, COALESCE(SUM(pl.quantity_produced * psm.quantity_per_unit), 0) AS produced").
		Joins("JOIN job_step_schedule_slots s ON s.slot_id = pl.slot_id").
		Joins("JOIN job_steps js ON js.job_step_id = s.job_step_id").
		Joins("JOIN process_step_materials psm ON psm.step_id = js.step_id AND psm.role = ? AND psm.product_id IS NOT NULL", domain.ProcessStepMaterialRoleOutput).
		Where("js.job_id LIKE ?", jobPrefix+"%").
		Group("psm.product_id").
		Scan(&outputs).Error; err != nil {
		result.Issues = append(result.Issues, verifyIssue{Subject: "finished_goods.produced", Message: err.Error()})
		return
	}
	for _, output := range outputs {
		var onHand float64
		q := db.Model(&domain.ProductInventory{}).Where("product_id = ?", output.ProductID)
		if strings.HasPrefix(jobPrefix, "JOB-RPT-") {
			q = q.Where("storage_location = ?", "FG-RPT")
		}
		if err := q.Select("COALESCE(SUM(quantity_on_hand), 0)").Scan(&onHand).Error; err != nil {
			result.Issues = append(result.Issues, verifyIssue{Subject: "finished_goods." + output.ProductID, Message: err.Error()})
			continue
		}
		if onHand+0.001 < output.Produced {
			result.Issues = append(result.Issues, verifyIssue{Subject: "finished_goods." + output.ProductID, Expected: output.Produced, Actual: onHand, Message: "finished goods inventory is less than logged product output"})
		}
	}
}

func closeEnough(a, b float64) bool {
	diff := a - b
	if diff < 0 {
		diff = -diff
	}
	return diff <= 0.001
}
