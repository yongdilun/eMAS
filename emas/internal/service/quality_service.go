package service

import (
	"emas/internal/domain"
	"emas/internal/handler/dto"
	"emas/internal/repository"
	"emas/pkg/id"
	"time"
)

type QualityService struct {
	qualityRepo *repository.QualityRepository
}

func NewQualityService(qualityRepo *repository.QualityRepository) *QualityService {
	return &QualityService{qualityRepo: qualityRepo}
}

func (s *QualityService) RecordInspection(req dto.RecordInspectionRequest) (*domain.QualityInspectionRecords, error) {
	r := &domain.QualityInspectionRecords{
		InspectionID:   id.NewPrefixed("QC-"),
		JobStepID:      req.JobStepID,
		InspectionTime: time.Now(),
		InspectorName:  req.InspectorName,
		Result:         req.Result,
		DefectCount:    req.DefectCount,
		Notes:          req.Notes,
	}
	if r.Result == "" {
		r.Result = domain.QualityResultPass
	}
	if err := s.qualityRepo.Create(r); err != nil {
		return nil, err
	}
	return r, nil
}
