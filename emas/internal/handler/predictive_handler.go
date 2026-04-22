package handler

import (
	"emas/internal/handler/dto"
	"emas/internal/service"
	"net/http"

	"github.com/gin-gonic/gin"
)

type PredictiveHandler struct {
	service *service.AIPredictiveService
}

func NewPredictiveHandler(service *service.AIPredictiveService) *PredictiveHandler {
	return &PredictiveHandler{service: service}
}

type HighRiskJob struct {
	JobID       string `json:"job_id"`
	MachineName string `json:"machine_name"`
	Issue       string `json:"issue"`
	RiskLevel   string `json:"risk_level"`
}

// @Summary List high-risk jobs
// @Description List high-risk jobs
// @Tags predictive
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.HighRiskJob}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /predictive/high-risk-jobs [get]
func (h *PredictiveHandler) HighRiskJobs(c *gin.Context) {
	results, err := h.service.ListHighRiskJobs(10)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: results})
}

type Recommendation struct {
	Icon     string `json:"icon"`
	Title    string `json:"title"`
	Action   string `json:"action"`
	Severity string `json:"severity,omitempty"`
}

// @Summary List recommendations
// @Description List recommendations
// @Tags predictive
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=[]domain.Recommendation}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /predictive/recommendations [get]
func (h *PredictiveHandler) Recommendations(c *gin.Context) {
	recs, err := h.service.Recommendations()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: recs})
}

type ForecastPoint struct {
	Label string  `json:"label"`
	Value float64 `json:"value"`
}

// @Summary Forecast
// @Description Forecast
// @Tags predictive
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=map[string]interface{}}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /predictive/forecast [get]
func (h *PredictiveHandler) Forecast(c *gin.Context) {
	forecastType := c.DefaultQuery("type", "delays")
	series, err := h.service.Forecast(forecastType)
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: map[string]interface{}{
		"type": series.Type,
		"data": series.Data,
	}})
}

// @Summary Confidence
// @Description Confidence
// @Tags predictive
// @Accept json
// @Produce json
// @Success 200 {object} dto.Response{data=domain.ConfidenceSummary}
// @Failure 400 {object} dto.Response
// @Failure 500 {object} dto.Response
// @Router /predictive/confidence [get]
func (h *PredictiveHandler) Confidence(c *gin.Context) {
	summary, err := h.service.Confidence()
	if err != nil {
		c.JSON(http.StatusInternalServerError, dto.Response{Success: false, Error: err.Error()})
		return
	}
	c.JSON(http.StatusOK, dto.Response{Success: true, Data: summary})
}
