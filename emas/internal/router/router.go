package router

import (
	"emas/internal/handler"
	"emas/internal/middleware"
	"emas/internal/repository"
	"emas/internal/service"
	"emas/pkg/featureflags"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	swaggerFiles "github.com/swaggo/files"
	ginSwagger "github.com/swaggo/gin-swagger"
	"gorm.io/gorm"

	_ "emas/docs"
)

func Setup(db *gorm.DB) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Length", "Content-Type", "Authorization", "X-User-Id", "X-User-Role", "X-Request-Id", "X-Correlation-Id"},
		ExposeHeaders:    []string{"X-Request-Id", "X-Correlation-Id"},
		AllowCredentials: false,
		MaxAge:           12 * 60 * 60,
	}))
	r.Use(middleware.RequestContext())

	// Swagger endpoint
	r.GET("/swagger/*any", ginSwagger.WrapHandler(swaggerFiles.Handler))

	// Repositories
	jobRepo := repository.NewJobRepository(db)
	stepRepo := repository.NewJobStepRepository(db)
	slotRepo := repository.NewJobSlotRepository(db)
	processRepo := repository.NewProcessRepository(db)
	formulaRepo := repository.NewFormulaRepository(db)
	productRepo := repository.NewProductRepository(db)
	machineRepo := repository.NewMachineRepository(db)
	capRepo := repository.NewMachineCapabilityRepository(db)
	downtimeRepo := repository.NewMachineDowntimeRepository(db)
	maintenanceRepo := repository.NewMaintenanceRepository(db)
	bomRepo := repository.NewProductBOMRepository(db)
	invRepo := repository.NewInventoryRepository(db)
	logRepo := repository.NewProductionLogRepository(db)
	qualityRepo := repository.NewQualityRepository(db)
	proposalRepo := repository.NewAIProposalRepository(db)
	setupRepo := repository.NewSetupRepository(db)
	trainingRepo := repository.NewMLTrainingEventRepository(db)
	resourceRepo := repository.NewResourceRepository(db)
	wipRepo := repository.NewWIPRepository(db)
	psmRepo := repository.NewProcessStepMaterialRepository(db)
	eventRepo := repository.NewSchedulingEventRepository(db)
	settingsRepo := repository.NewSystemSettingsRepository(db)
	convRepo := repository.NewAIConversationRepository(db)
	msgRepo := repository.NewAIChatMessageRepository(db)

	// Services
	schedulingSvc := service.NewSchedulingService(productRepo, bomRepo, formulaRepo, processRepo, jobRepo, stepRepo, slotRepo, machineRepo, capRepo, downtimeRepo, maintenanceRepo, invRepo, logRepo, proposalRepo, setupRepo, trainingRepo, resourceRepo, wipRepo, psmRepo, settingsRepo)
	jobSvc := service.NewJobService(jobRepo, stepRepo, slotRepo, processRepo, productRepo, schedulingSvc)
	slotSvc := service.NewJobSlotService(slotRepo, stepRepo, processRepo, jobRepo, schedulingSvc)
	processSvc := service.NewProcessService(processRepo)
	formulaSvc := service.NewFormulaService(formulaRepo, productRepo)
	machineSvc := service.NewMachineService(machineRepo, capRepo, downtimeRepo, maintenanceRepo)
	productSvc := service.NewProductService(productRepo, bomRepo, formulaRepo, processRepo)
	invSvc := service.NewInventoryService(invRepo)
	logSvc := service.NewProductionLogService(db, logRepo, slotRepo, stepRepo, jobRepo, proposalRepo, schedulingSvc)
	qualitySvc := service.NewQualityService(qualityRepo)
	maintenanceSvc := service.NewMaintenanceService(maintenanceRepo, machineRepo)
	aiPredictiveSvc := service.NewAIPredictiveService(db, jobRepo, stepRepo, slotRepo, proposalRepo, machineRepo, maintenanceRepo, settingsRepo, schedulingSvc, slotSvc, eventRepo)
	aiOrchestrator := service.NewAICommandOrchestrator()
	aiCommandProcessor := service.NewAICommandProcessor(aiOrchestrator, aiPredictiveSvc, jobSvc)
	aiChatSvc := service.NewAIChatService(convRepo, msgRepo, aiCommandProcessor)
	agentTransactionSvc := service.NewAgentTransactionService(db)

	// Phase 0 chatbot (new foundation, read-only tool execution only).
	chatPlanner := service.NewKeywordChatPlanner()
	chatRegistry := service.NewStaticChatToolRegistry(db, jobSvc, machineSvc, invSvc, aiPredictiveSvc, machineRepo, invRepo)
	chatTurnRepo := repository.NewChatbotTurnAuditRepository(db)
	chatSnapRepo := repository.NewChatbotToolExecutionSnapshotRepository(db)
	chatExecutor := service.NewRegistryBackedReadOnlyExecutor(chatRegistry, chatSnapRepo)

	chatApprovalRepo := repository.NewChatbotApprovalRepository(db)
	chatApprovalExec := service.NewApprovalExecutor(chatApprovalRepo, chatSnapRepo, chatRegistry)

	chatbotSvc := service.NewChatbotService(convRepo, msgRepo, chatTurnRepo, chatApprovalRepo, chatPlanner, chatExecutor, chatRegistry)

	// Handlers
	jobH := handler.NewJobHandler(jobSvc)
	slotH := handler.NewJobSlotHandler(slotSvc)
	processH := handler.NewProcessHandler(processSvc)
	formulaH := handler.NewFormulaHandler(formulaSvc)
	machineH := handler.NewMachineHandler(machineSvc, aiPredictiveSvc)
	productH := handler.NewProductHandler(productSvc)
	invH := handler.NewInventoryHandler(invSvc)
	logH := handler.NewProductionLogHandler(logSvc)
	qualityH := handler.NewQualityHandler(qualitySvc)
	maintenanceH := handler.NewMaintenanceHandler(maintenanceSvc)
	schedulingH := handler.NewSchedulingHandler(schedulingSvc)
	reportsH := handler.NewReportsHandler(db)
	dashboardH := handler.NewDashboardHandler(db, machineRepo, invRepo)
	predictiveH := handler.NewPredictiveHandler(aiPredictiveSvc)
	aiH := handler.NewAIHandler(aiCommandProcessor)
	agentTransactionH := handler.NewAgentTransactionHandler(agentTransactionSvc)
	settingsH := handler.NewSettingsHandler(settingsRepo)
	schedulingSettingsH := handler.NewSchedulingSettingsHandler(settingsRepo, schedulingSvc)
	refH := handler.NewReferenceHandler(db)

	chatApprovalH := handler.NewChatbotApprovalHandler(chatApprovalRepo, chatApprovalExec)

	var chatService service.ChatConversationService = aiChatSvc
	if featureflags.ChatbotV2Enabled() {
		chatService = chatbotSvc
	}
	aiChatH := handler.NewAIChatHandler(chatService)
	aiSchedulingH := handler.NewAISchedulingHandler(aiPredictiveSvc)

	// API v1
	v1 := r.Group("/api/v1")
	v1.Use(middleware.IdempotencyMiddleware(db))
	{
		// Jobs
		v1.POST("/jobs", jobH.Create)
		v1.GET("/jobs", jobH.List)
		v1.GET("/jobs/:id", jobH.GetByID)
		v1.GET("/jobs/:id/steps", jobH.ListSteps)
		v1.PUT("/jobs/:id", jobH.Update)
		v1.DELETE("/jobs/:id", jobH.Delete)
		v1.POST("/jobs/:id/duplicate", jobH.Duplicate)

		// Job Steps & Slots
		v1.POST("/job-steps", slotH.CreateJobSteps)
		v1.POST("/job-steps/split", slotH.SplitStep)
		v1.GET("/jobs/:id/slots", slotH.ListSlotsByJob)
		v1.GET("/job-steps/:id/slots", slotH.ListSlotsByJobStep)
		v1.GET("/slots/:id", slotH.GetSlot)
		v1.PUT("/slots/:id", slotH.UpdateSlot)
		v1.PATCH("/slots/:id", slotH.UpdateSlot)
		v1.DELETE("/slots/:id", slotH.CancelSlot)

		// Machines
		v1.POST("/machines", machineH.Create)
		v1.GET("/machines", machineH.List)
		v1.GET("/machines/utilization", machineH.Utilization)
		v1.GET("/machines/:id", machineH.GetByID)
		v1.PUT("/machines/:id", machineH.Update)
		v1.POST("/machines/:id/capabilities", machineH.AssignCapability)
		v1.POST("/machines/downtime", machineH.RecordDowntime)
		v1.GET("/machines/maintenance-alerts", machineH.MaintenanceAlerts)
		v1.GET("/machines/reroute-recommendations", machineH.RerouteRecommendations)

		// Process (routing - UC-P01)
		v1.POST("/processes", processH.Create)
		v1.GET("/processes", processH.List)
		v1.GET("/processes/:id", processH.GetByID)
		v1.GET("/products/:id/process", processH.GetByProduct)
		v1.GET("/processes/:id/steps", processH.ListSteps)
		v1.POST("/processes/:id/steps", processH.AddStep)
		v1.DELETE("/processes/:id", processH.Delete)

		// Process steps (materials per step - INTERFACE_DESIGN 2.1, 5.5)
		processStepH := handler.NewProcessStepHandler(psmRepo, invRepo, processRepo)
		v1.GET("/process-steps/:step_id/materials", processStepH.ListMaterials)
		v1.POST("/process-steps/:step_id/materials", processStepH.AddMaterial)
		v1.DELETE("/process-steps/:step_id/materials/:id", processStepH.DeleteMaterial)

		// Formula (UC-P01)
		v1.POST("/formulas", formulaH.Create)
		v1.GET("/formulas", formulaH.List)
		v1.GET("/formulas/:id", formulaH.GetByID)
		v1.GET("/formulas/:id/ingredients", formulaH.ListIngredients)
		v1.POST("/formulas/:id/ingredients", formulaH.AddIngredient)
		v1.DELETE("/formulas/:id", formulaH.Delete)

		// Products
		v1.POST("/products", productH.Create)
		v1.GET("/products", productH.List)
		v1.GET("/products/:id", productH.GetByID)
		v1.GET("/products/:id/scheduling-definition", productH.GetSchedulingDefinition)
		v1.PUT("/products/:id/bom", productH.LinkBOM)

		// Inventory
		v1.POST("/inventory/materials", invH.CreateMaterial)
		v1.GET("/inventory/materials", invH.ListMaterials)
		v1.GET("/inventory/materials/:id", invH.GetMaterial)
		v1.POST("/inventory/consume", invH.Consume)
		v1.POST("/inventory/receive", invH.Receive)
		v1.POST("/inventory/expected-arrivals", invH.ScheduleExpectedArrival)
		v1.GET("/inventory/expected-arrivals", invH.ListExpectedArrivals)
		v1.POST("/inventory/product-stock", invH.CreateProductInventory)
		v1.GET("/inventory/product-stock", invH.ListProductInventory)
		v1.POST("/inventory/reservations", invH.CreateReservation)
		v1.GET("/inventory/reservations", invH.ListReservations)

		// Scheduling
		v1.GET("/scheduling/products/:id/explosion", schedulingH.Explosion)
		v1.GET("/scheduling/products/:id/readiness", schedulingH.Readiness)
		v1.GET("/scheduling/steps/:id/candidate-machines", schedulingH.CandidateMachines)
		v1.POST("/scheduling/slots/validate", schedulingH.ValidateSlot)
		v1.GET("/scheduling/jobs/:id/earliest-completion", schedulingH.EstimateJobCompletion)
		v1.GET("/scheduling/jobs/:id/solver-preview", schedulingH.SolverPreview)
		v1.GET("/scheduling/training-dataset", schedulingH.TrainingDataset)
		v1.GET("/scheduling/training-dataset/stats", schedulingH.TrainingDatasetStats)
		v1.POST("/scheduling/training-dataset/backfill", middleware.RequireRoles("planner", "manager", "admin"), schedulingH.BackfillTrainingDataset)

		// Production Logs
		v1.POST("/production-logs", logH.LogProduction)

		// Quality
		v1.POST("/quality/inspections", qualityH.RecordInspection)

		// Maintenance
		v1.POST("/maintenance", maintenanceH.RecordMaintenance)

		// Reports & Analytics
		v1.GET("/reports/production-output", reportsH.ProductionOutputPerSlot)
		v1.GET("/reports/machine-utilization", reportsH.MachineUtilization)
		v1.GET("/reports/job-completion", reportsH.JobCompletion)
		v1.GET("/reports/inventory-trends", reportsH.InventoryTrends)
		v1.GET("/reports/quality-trends", reportsH.QualityTrends)
		v1.GET("/reports/oee", reportsH.OEETrends)
		v1.GET("/reports/bottlenecks", reportsH.BottleneckForecast)
		v1.GET("/reports/maintenance-efficiency", reportsH.MaintenanceEfficiency)

		// Dashboard
		v1.GET("/dashboard/kpis", dashboardH.GetKPIs)
		v1.GET("/alerts", dashboardH.GetAlerts)

		// Predictive
		v1.GET("/predictive/high-risk-jobs", predictiveH.HighRiskJobs)
		v1.GET("/predictive/recommendations", predictiveH.Recommendations)
		v1.GET("/predictive/forecast", predictiveH.Forecast)
		v1.GET("/predictive/confidence", predictiveH.Confidence)

		// AI / NLP
		v1.POST("/ai/command", aiH.ParseCommand)
		v1.POST("/agent/transaction/bundle-dry-run", agentTransactionH.BundleDryRun)
		v1.POST("/agent/transaction/commit", agentTransactionH.Commit)

		// AI Chat (persisted conversations)
		// By default this routes through the new Phase 0 chatbot stack (read-only tools only).
		// Set AI_CHAT_LEGACY_ENABLED=false to disable these endpoints entirely.
		if featureflags.LegacyChatEndpointsEnabled() {
			v1.GET("/ai/chats", aiChatH.List)
			v1.POST("/ai/chats", aiChatH.Create)
			v1.GET("/ai/chats/:id", aiChatH.Get)
			v1.POST("/ai/chats/:id/messages", aiChatH.SendMessage)
			v1.GET("/ai/chats/:id/approvals", chatApprovalH.ListPending)
		}

		v1.POST("/ai/chatbot/approvals", chatApprovalH.Approve) // For testing creation? Not needed if created internally
		v1.GET("/ai/chatbot/approvals/:id", chatApprovalH.Get)
		v1.POST("/ai/chatbot/approvals/:id/approve", chatApprovalH.Approve)
		v1.POST("/ai/chatbot/approvals/:id/reject", chatApprovalH.Reject)
		v1.GET("/ai/scheduling/jobs/:id/assist", aiSchedulingH.Assist)
		v1.GET("/ai/scheduling/jobs/:id/delay-risk", aiSchedulingH.DelayRisk)
		v1.GET("/ai/scheduling/jobs/:id/explanation", aiSchedulingH.Explanation)
		v1.GET("/ai/scheduling/jobs/:id/proposal", aiSchedulingH.Proposal)
		v1.POST("/ai/scheduling/jobs/:id/apply-proposal", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ApplyProposal)
		v1.POST("/ai/scheduling/jobs/:id/proposals", aiSchedulingH.GenerateProposal)
		v1.POST("/ai/scheduling/batch-proposals", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.GenerateBatchProposals)
		v1.POST("/ai/scheduling/reschedule-all", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.RescheduleAll)
		v1.POST("/ai/scheduling/verify-overlaps", aiSchedulingH.VerifyOverlaps)
		v1.POST("/scheduling/events", aiSchedulingH.EmitSchedulingEvent)
		v1.GET("/ai/scheduling/jobs/:id/proposals", aiSchedulingH.ListProposals)
		v1.GET("/ai/scheduling/proposals/:id", aiSchedulingH.GetProposal)
		v1.POST("/ai/scheduling/proposals/:id/approve", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ApproveProposal)
		v1.POST("/ai/scheduling/proposals/:id/reject", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.RejectProposal)
		v1.POST("/ai/scheduling/proposals/:id/apply", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ApplyProposalByID)
		v1.GET("/ai/scheduling/jobs/:id/shortage-analysis", aiSchedulingH.ShortageAnalysis)
		v1.POST("/ai/scheduling/proposals/:id/apply-replenishment", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ApplyReplenishment)
		v1.POST("/ai/scheduling/apply-replenishment-batch", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ApplyReplenishmentBatch)
		v1.POST("/ai/scheduling/jobs/:id/replenish-and-replan", middleware.RequireRoles("planner", "manager", "admin"), aiSchedulingH.ReplenishAndReplan)
		v1.GET("/ai/scheduling/job-steps/:id/split-suggestion", aiSchedulingH.SplitSuggestion)
		v1.GET("/ai/scheduling/job-steps/:id/machine-ranking", aiSchedulingH.MachineRanking)
		v1.GET("/ai/scheduling/bottleneck-forecast", aiSchedulingH.BottleneckForecast)
		v1.GET("/ai/metrics", aiSchedulingH.Metrics)

		// Settings
		v1.GET("/settings", settingsH.Get)
		v1.PUT("/settings", settingsH.Update)
		v1.GET("/scheduling/settings", schedulingSettingsH.Get)
		v1.PUT("/scheduling/settings", middleware.RequireRoles("planner", "manager", "admin"), schedulingSettingsH.Update)
		v1.POST("/scheduling/refresh-work-calendars", middleware.RequireRoles("planner", "manager", "admin"), schedulingH.RefreshWorkCalendars)

		// Reference / lookup data
		v1.GET("/reference/machine-types", refH.ListMachineTypes)
		v1.POST("/reference/machine-types", refH.CreateMachineType)
		v1.PUT("/reference/machine-types/:id", refH.UpdateMachineType)
		v1.DELETE("/reference/machine-types/:id", refH.DeleteMachineType)
		v1.GET("/reference/product-types", refH.ListProductTypes)
		v1.POST("/reference/product-types", refH.CreateProductType)
		v1.DELETE("/reference/product-types/:id", refH.DeleteProductType)
		v1.GET("/reference/locations", refH.ListLocations)
		v1.POST("/reference/locations", refH.CreateLocation)
		v1.DELETE("/reference/locations/:id", refH.DeleteLocation)
		v1.GET("/reference/storage-locations", refH.ListStorageLocations)
		v1.POST("/reference/storage-locations", refH.CreateStorageLocation)
		v1.DELETE("/reference/storage-locations/:id", refH.DeleteStorageLocation)
		v1.GET("/reference/step-types", refH.ListStepTypes)
		v1.POST("/reference/step-types", refH.CreateStepType)
		v1.DELETE("/reference/step-types/:id", refH.DeleteStepType)
	}

	return r
}
