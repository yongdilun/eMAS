package schedulereval

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"time"
)

type ScenarioSetupResult struct {
	ScenarioID string            `json:"scenario_id"`
	JobIDs     map[string]string `json:"job_ids,omitempty"`
	Notes      []string          `json:"notes,omitempty"`
}

func SetupScenarioFixture(ctx context.Context, handler http.Handler, scenarioID string, headers map[string]string) (ScenarioSetupResult, error) {
	if handler == nil {
		return ScenarioSetupResult{}, fmt.Errorf("scenario fixture setup requires an HTTP handler")
	}
	switch scenarioID {
	case ScenarioCanonicalSeed:
		return ScenarioSetupResult{
			ScenarioID: scenarioID,
			Notes:      []string{"canonical_seed is created by seeddata.SeedCanonical or the CLI -reset-canonical flag"},
		}, nil
	case ScenarioNoShortageControl:
		return setupNoShortageControl(ctx, handler, headers)
	case ScenarioTrueMaterialShortage:
		return setupTrueShortageAndUnaffected(ctx, handler, headers)
	case ScenarioDelayedMaterialWait:
		return setupDelayedMaterialOnly(ctx, handler, headers)
	case ScenarioChildBOMShortage:
		return setupChildBOMShortage(ctx, handler, headers)
	case ScenarioResourceOverload:
		return setupResourceOverload(ctx, handler, headers)
	case ScenarioOneShotResolution:
		return setupDelayedAndStarvedMaterial(ctx, handler, headers)
	default:
		return ScenarioSetupResult{}, fmt.Errorf("unknown scenario fixture %q", scenarioID)
	}
}

func setupNoShortageControl(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-OK", ProductName: "Eval No Shortage Product",
		ProcessID: "PRC-EVAL-OK", ProcessName: "Eval No Shortage Process",
		StepID: "STEP-EVAL-OK", StepName: "Eval machine step",
		MachineID: "M-EVAL-OK", MachineName: "Eval OK Machine", MachineType: "EVAL_OK",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	jobs := map[string]string{}
	for i := 0; i < 2; i++ {
		id, err := createEvalJob(ctx, h, headers, "P-EVAL-OK", "medium", scenarioNow().Add(time.Duration(24+i)*time.Hour), fmt.Sprintf("eval no shortage %d", i))
		if err != nil {
			return ScenarioSetupResult{}, err
		}
		jobs[fmt.Sprintf("job_%d", i+1)] = id
	}
	return ScenarioSetupResult{ScenarioID: ScenarioNoShortageControl, JobIDs: jobs}, nil
}

func setupDelayedAndStarvedMaterial(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-MAT", ProductName: "Eval Material Product",
		ProcessID: "PRC-EVAL-MAT", ProcessName: "Eval Material Process",
		StepID: "STEP-EVAL-MAT", StepName: "Eval material constrained step",
		MachineID: "M-EVAL-MAT", MachineName: "Eval Material Machine", MachineType: "EVAL_MAT",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "material_name": "Eval Limited Material", "current_stock": 10, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/process-steps/STEP-EVAL-MAT/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/inventory/expected-arrivals", map[string]interface{}{
		"material_id": "MAT-EVAL-LIMIT", "quantity": 10, "expected_arrive_at": scenarioNow().Add(4 * time.Hour).Format(time.RFC3339),
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	jobs := map[string]string{}
	var err error
	jobs["current_material"], err = createEvalJob(ctx, h, headers, "P-EVAL-MAT", "high", scenarioNow().Add(48*time.Hour), "eval current material")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	jobs["wait_material"], err = createEvalJob(ctx, h, headers, "P-EVAL-MAT", "medium", scenarioNow().Add(49*time.Hour), "eval wait material")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	jobs["starved_material"], err = createEvalJob(ctx, h, headers, "P-EVAL-MAT", "low", scenarioNow().Add(50*time.Hour), "eval starved material")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	return ScenarioSetupResult{ScenarioID: ScenarioOneShotResolution, JobIDs: jobs}, nil
}

func setupDelayedMaterialOnly(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-WAIT", ProductName: "Eval Wait Material Product",
		ProcessID: "PRC-EVAL-WAIT", ProcessName: "Eval Wait Process",
		StepID: "STEP-EVAL-WAIT", StepName: "Eval wait material step",
		MachineID: "M-EVAL-WAIT", MachineName: "Eval Wait Machine", MachineType: "EVAL_WAIT",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "material_name": "Eval Future Material", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/process-steps/STEP-EVAL-WAIT/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	arrivalAt := scenarioNow().Add(4 * time.Hour)
	if err := postOK(ctx, h, headers, "/api/v1/inventory/expected-arrivals", map[string]interface{}{
		"material_id": "MAT-EVAL-WAIT", "quantity": 10, "expected_arrive_at": arrivalAt.Format(time.RFC3339),
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	jobID, err := createEvalJob(ctx, h, headers, "P-EVAL-WAIT", "medium", scenarioNow().Add(48*time.Hour), "eval future material should wait")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	return ScenarioSetupResult{
		ScenarioID: ScenarioDelayedMaterialWait,
		JobIDs:     map[string]string{"wait_job": jobID},
		Notes:      []string{"expected arrival at " + arrivalAt.Format(time.RFC3339)},
	}, nil
}

func setupTrueShortageAndUnaffected(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-BLOCKED", ProductName: "Eval Blocked Material Product",
		ProcessID: "PRC-EVAL-BLOCKED", ProcessName: "Eval Blocked Process",
		StepID: "STEP-EVAL-BLOCKED", StepName: "Eval blocked material step",
		MachineID: "M-EVAL-BLOCKED", MachineName: "Eval Blocked Machine", MachineType: "EVAL_BLOCKED",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-NONE", "material_name": "Eval Missing Material", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/process-steps/STEP-EVAL-BLOCKED/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-NONE", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-FREE", ProductName: "Eval Unaffected Product",
		ProcessID: "PRC-EVAL-FREE", ProcessName: "Eval Unaffected Process",
		StepID: "STEP-EVAL-FREE", StepName: "Eval unaffected step",
		MachineID: "M-EVAL-FREE", MachineName: "Eval Free Machine", MachineType: "EVAL_FREE",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	deadline := scenarioNow().Add(48 * time.Hour)
	blockedID, err := createEvalJob(ctx, h, headers, "P-EVAL-BLOCKED", "high", deadline, "eval true material shortage")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	unaffectedID, err := createEvalJob(ctx, h, headers, "P-EVAL-FREE", "medium", deadline, "eval unaffected by shortage")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	return ScenarioSetupResult{
		ScenarioID: ScenarioTrueMaterialShortage,
		JobIDs:     map[string]string{"blocked": blockedID, "unaffected": unaffectedID},
	}, nil
}

func setupResourceOverload(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-LOAD", ProductName: "Eval Resource Load Product",
		ProcessID: "PRC-EVAL-LOAD", ProcessName: "Eval Resource Load Process",
		StepID: "STEP-EVAL-LOAD", StepName: "Eval overloaded machine step",
		MachineID: "M-EVAL-LOAD", MachineName: "Eval Single Load Machine", MachineType: "EVAL_LOAD",
		DurationMins: 180, CapacityPerHour: 10,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	jobs := map[string]string{}
	for i := 0; i < 5; i++ {
		id, err := createEvalJob(ctx, h, headers, "P-EVAL-LOAD", "medium", scenarioNow().Add(time.Duration(2+i)*time.Hour), fmt.Sprintf("eval resource overload %d", i))
		if err != nil {
			return ScenarioSetupResult{}, err
		}
		jobs[fmt.Sprintf("load_%d", i+1)] = id
	}
	return ScenarioSetupResult{ScenarioID: ScenarioResourceOverload, JobIDs: jobs}, nil
}

func setupChildBOMShortage(ctx context.Context, h http.Handler, headers map[string]string) (ScenarioSetupResult, error) {
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-CHILD", ProductName: "Eval Child Product",
		ProcessID: "PRC-EVAL-CHILD", ProcessName: "Eval Child Process",
		StepID: "STEP-EVAL-CHILD", StepName: "Eval child raw step",
		MachineID: "M-EVAL-CHILD", MachineName: "Eval Child Machine", MachineType: "EVAL_CHILD",
		DurationMins: 30, CapacityPerHour: 60,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/inventory/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-CHILD-RAW", "material_name": "Eval Missing Child Raw", "current_stock": 0, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/process-steps/STEP-EVAL-CHILD/materials", map[string]interface{}{
		"material_id": "MAT-EVAL-CHILD-RAW", "role": "input", "quantity_per_unit": 10, "unit": "kg",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/products", map[string]interface{}{
		"product_id": "P-EVAL-PARENT", "product_name": "Eval Parent Product",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := requestOK(ctx, h, headers, http.MethodPut, "/api/v1/products/P-EVAL-PARENT/bom", map[string]interface{}{
		"bom_items": []map[string]interface{}{{"product_id": "P-EVAL-CHILD", "quantity_per_unit": 1, "unit": "pcs"}},
	}, http.StatusOK); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := createSingleStepProduct(ctx, h, headers, singleStepProductSpec{
		ProductID: "P-EVAL-PARENT", ProductName: "Eval Parent Product",
		ProcessID: "PRC-EVAL-PARENT", ProcessName: "Eval Parent Process",
		StepID: "STEP-EVAL-PARENT", StepName: "Eval parent assembly step",
		MachineID: "M-EVAL-PARENT", MachineName: "Eval Parent Machine", MachineType: "EVAL_PARENT",
		DurationMins: 30, CapacityPerHour: 60, SkipProductCreate: true,
	}); err != nil {
		return ScenarioSetupResult{}, err
	}
	if err := postOK(ctx, h, headers, "/api/v1/process-steps/STEP-EVAL-PARENT/materials", map[string]interface{}{
		"product_id": "P-EVAL-CHILD", "role": "input", "quantity_per_unit": 1, "unit": "pcs",
	}, http.StatusCreated); err != nil {
		return ScenarioSetupResult{}, err
	}
	parentID, err := createEvalJob(ctx, h, headers, "P-EVAL-PARENT", "high", scenarioNow().Add(48*time.Hour), "eval child bom raw shortage")
	if err != nil {
		return ScenarioSetupResult{}, err
	}
	return ScenarioSetupResult{
		ScenarioID: ScenarioChildBOMShortage,
		JobIDs:     map[string]string{"parent": parentID},
	}, nil
}

type singleStepProductSpec struct {
	ProductID, ProductName string
	ProcessID, ProcessName string
	StepID, StepName       string
	MachineID, MachineName string
	MachineType            string
	DurationMins           int
	CapacityPerHour        int
	SkipProductCreate      bool
}

func createSingleStepProduct(ctx context.Context, h http.Handler, headers map[string]string, spec singleStepProductSpec) error {
	if !spec.SkipProductCreate {
		if err := postOK(ctx, h, headers, "/api/v1/products", map[string]interface{}{
			"product_id": spec.ProductID, "product_name": spec.ProductName,
		}, http.StatusCreated); err != nil {
			return err
		}
	}
	if err := postOK(ctx, h, headers, "/api/v1/processes", map[string]interface{}{
		"process_id": spec.ProcessID, "product_id": spec.ProductID, "process_name": spec.ProcessName,
	}, http.StatusCreated); err != nil {
		return err
	}
	if err := postOK(ctx, h, headers, "/api/v1/processes/"+spec.ProcessID+"/steps", map[string]interface{}{
		"step_id": spec.StepID, "step_sequence": 1, "step_name": spec.StepName,
		"machine_type_required": spec.MachineType, "default_processing_time": spec.DurationMins,
	}, http.StatusCreated); err != nil {
		return err
	}
	return postOK(ctx, h, headers, "/api/v1/machines", map[string]interface{}{
		"machine_id": spec.MachineID, "machine_name": spec.MachineName, "machine_type": spec.MachineType, "capacity_per_hour": spec.CapacityPerHour,
	}, http.StatusCreated)
}

func createEvalJob(ctx context.Context, h http.Handler, headers map[string]string, productID, priority string, deadline time.Time, notes string) (string, error) {
	raw, err := requestRaw(ctx, h, headers, http.MethodPost, "/api/v1/jobs", map[string]interface{}{
		"product_id": productID, "quantity_total": 1, "deadline": deadline.Format(time.RFC3339),
		"priority": priority, "notes": notes, "allow_auto_plan": true,
	}, http.StatusCreated)
	if err != nil {
		return "", err
	}
	var resp struct {
		Success bool                   `json:"success"`
		Data    map[string]interface{} `json:"data"`
		Error   string                 `json:"error"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return "", err
	}
	if !resp.Success {
		return "", fmt.Errorf("create eval job success=false: %s", resp.Error)
	}
	jobID, _ := resp.Data["job_id"].(string)
	if jobID == "" {
		return "", fmt.Errorf("create eval job response missing job_id: %s", string(raw))
	}
	return jobID, nil
}

func postOK(ctx context.Context, h http.Handler, headers map[string]string, path string, body interface{}, status int) error {
	return requestOK(ctx, h, headers, http.MethodPost, path, body, status)
}

func requestOK(ctx context.Context, h http.Handler, headers map[string]string, method, path string, body interface{}, status int) error {
	_, err := requestRaw(ctx, h, headers, method, path, body, status)
	return err
}

func requestRaw(ctx context.Context, h http.Handler, headers map[string]string, method, path string, body interface{}, status int) ([]byte, error) {
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = bytes.NewReader(payload)
	}
	req := httptest.NewRequest(method, path, reader).WithContext(ctx)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != status {
		return nil, fmt.Errorf("%s %s status=%d, want %d, body=%s", method, path, w.Code, status, w.Body.String())
	}
	var resp struct {
		Success bool   `json:"success"`
		Error   string `json:"error"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err == nil && !resp.Success {
		return nil, fmt.Errorf("%s %s success=false: %s", method, path, resp.Error)
	}
	return w.Body.Bytes(), nil
}

func scenarioNow() time.Time {
	return time.Now().UTC().Truncate(time.Hour)
}
