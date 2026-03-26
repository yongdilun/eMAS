package dto

// AICommandResponse is the response shape for POST /ai/command and POST /ai/chats/:id/messages.
type AICommandResponse struct {
	Intent         string                 `json:"intent"`
	Action         string                 `json:"action"`
	Entities       map[string]interface{} `json:"entities"`
	Confidence     float64                `json:"confidence,omitempty"`
	Ambiguous      bool                   `json:"ambiguous,omitempty"`
	Clarifications []string               `json:"clarifications,omitempty"`
	Message        string                 `json:"message"`
	ExecutionMode  string                 `json:"execution_mode,omitempty"`
	Executed       bool                   `json:"executed"`
	ExecutedCall   *AISuggestedCall       `json:"executed_call,omitempty"`
	SuggestedCalls []AISuggestedCall      `json:"suggested_calls,omitempty"`
	Insights       interface{}            `json:"insights,omitempty"`
	Guidance       []string               `json:"guidance,omitempty"`
	ResultCards    []AIResultCard         `json:"result_cards,omitempty"`
	BDIResult      *BDIResult             `json:"bdi_result,omitempty"`
}

// BDIResult - Belief-Desire-Intention structured output.
type BDIResult struct {
	Beliefs   BDIBeliefs   `json:"beliefs"`
	Desire    BDIDesire    `json:"desire"`
	Intention BDIIntention `json:"intention"`
}

type BDIBeliefs struct {
	Entities map[string]interface{} `json:"entities"`
	Resource string                 `json:"resource,omitempty"`
}

type BDIDesire struct {
	Intent     string  `json:"intent"`
	Confidence float64 `json:"confidence"`
}

type BDIIntention struct {
	Action          string                 `json:"action"`
	ExecutableCalls []BDIExecutableCall    `json:"executable_calls"`
}

type BDIExecutableCall struct {
	Method           string                 `json:"method"`
	Path             string                 `json:"path"`
	Body             map[string]interface{} `json:"body,omitempty"`
	Purpose          string                 `json:"purpose"`
	RequiresApproval bool                   `json:"requires_approval"`
}

// AISuggestedCall describes a suggested API call.
// RequiresApproval: true for POST/PUT/PATCH/DELETE (data-changing); false for GET (read-only, can execute immediately).
type AISuggestedCall struct {
	Method           string                 `json:"method"`
	Path             string                 `json:"path"`
	Body             map[string]interface{} `json:"body,omitempty"`
	Purpose          string                 `json:"purpose"`
	RequiresApproval bool                   `json:"requires_approval"`
	UI               *AISuggestedCallUI     `json:"ui,omitempty"`
}

// AISuggestedCallUI provides frontend display hints for suggested calls.
type AISuggestedCallUI struct {
	Display  string `json:"display,omitempty"`  // primary | secondary | hidden_if_result_card_exists
	Priority string `json:"priority,omitempty"` // high | normal | low
}

// AIResultCard is a UI card for display.
type AIResultCard struct {
	Kind    string           `json:"kind"`
	Title   string           `json:"title"`
	Tone    string           `json:"tone,omitempty"`
	Summary string           `json:"summary"`
	Metrics []AIResultMetric `json:"metrics,omitempty"`
	Bullets []string         `json:"bullets,omitempty"`
	Actions []AISuggestedCall `json:"actions,omitempty"`
}

// AIResultMetric is a label/value metric.
type AIResultMetric struct {
	Label string `json:"label"`
	Value string `json:"value"`
}
