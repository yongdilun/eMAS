package domain

import "time"

// QualityResult values
const (
	QualityResultPass = "pass"
	QualityResultFail = "fail"
)

// QualityInspectionRecords - QC inspection results
type QualityInspectionRecords struct {
	InspectionID   string    `gorm:"column:inspection_id;primaryKey;size:50"`
	JobStepID      string    `gorm:"column:job_step_id;size:50;index"`
	InspectionTime time.Time `gorm:"column:inspection_time"`
	InspectorName  string    `gorm:"column:inspector_name;size:100"`
	Result         string    `gorm:"column:result;size:20"` // pass, fail
	DefectCount    int       `gorm:"column:defect_count"`
	Notes          string    `gorm:"column:notes;type:text"`
}

func (QualityInspectionRecords) TableName() string { return "quality_inspection_records" }
