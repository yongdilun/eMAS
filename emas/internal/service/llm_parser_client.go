package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// LLMParserClient calls a local Ollama-compatible endpoint to parse natural
// language commands into AICommandPlan JSON. All outputs are treated as
// untrusted and must be validated by callers.
type LLMParserClient struct {
	httpClient *http.Client
	baseURL    string
	model      string
	provider   string
	mu         sync.Mutex
	cache      map[string]cacheEntry
}

type cacheEntry struct {
	value     []byte
	expiresAt time.Time
}

type ollamaRequest struct {
	Model   string      `json:"model"`
	Prompt  string      `json:"prompt"`
	Stream  bool        `json:"stream"`
	Options interface{} `json:"options,omitempty"`
}

type ollamaResponse struct {
	Response string `json:"response"`
	// Other fields are ignored.
}

type openAIRequest struct {
	Model          string            `json:"model"`
	Messages       []openAIMessage   `json:"messages"`
	Temperature    float64           `json:"temperature,omitempty"`
	MaxTokens      int               `json:"max_tokens,omitempty"`
	ResponseFormat map[string]string `json:"response_format,omitempty"`
}

type openAIMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type openAIResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

// semaphore channel for limiting concurrent Ollama calls. Initialized lazily
// based on LLM_MAX_CONCURRENCY env (default 2, min 1, max 4).
var llmConcurrencyCh chan struct{}

func acquireLLMSlot(ctx context.Context) error {
	ch := llmConcurrencyCh
	if ch == nil {
		// Lazy, racy init is fine; capacity will converge to the same value.
		maxConc := 2
		if v := strings.TrimSpace(os.Getenv("LLM_MAX_CONCURRENCY")); v != "" {
			if n, err := strconv.Atoi(v); err == nil && n > 0 {
				if n > 4 {
					n = 4
				}
				maxConc = n
			}
		}
		ch = make(chan struct{}, maxConc)
		llmConcurrencyCh = ch
	}

	// Short, bounded wait so we fail fast under saturation instead of
	// silently timing out on the HTTP client.
	waitCtx, cancel := context.WithTimeout(ctx, 250*time.Millisecond)
	defer cancel()

	select {
	case ch <- struct{}{}:
		return nil
	case <-waitCtx.Done():
		return fmt.Errorf("llm parser busy, retry shortly")
	}
}

func releaseLLMSlot() {
	ch := llmConcurrencyCh
	if ch == nil {
		return
	}
	select {
	case <-ch:
	default:
	}
}

// NewLLMParserClient constructs a client with sane defaults. It reads
// OLAMA_BASE_URL and OLLAMA_MODEL (optional); otherwise falls back to
// localhost and a generic model name.
func NewLLMParserClient() *LLMParserClient {
	base := os.Getenv("OLLAMA_BASE_URL")
	if base == "" {
		base = "http://localhost:11434"
	}
	model := os.Getenv("OLLAMA_MODEL")
	if model == "" {
		model = "llama3.1:8b-instruct"
	}
	provider := strings.ToLower(strings.TrimSpace(os.Getenv("LLM_PARSER_PROVIDER")))
	if provider == "" {
		provider = "ollama"
	}
	return &LLMParserClient{
		httpClient: &http.Client{
			Timeout: 2 * time.Second,
		},
		baseURL:  base,
		model:    model,
		provider: provider,
		cache:    make(map[string]cacheEntry),
	}
}

// ParseCommand sends the raw natural-language command to the LLM and returns
// the raw JSON bytes. It does NOT attempt to decode into AICommandPlan.
func (c *LLMParserClient) ParseCommand(ctx context.Context, raw string) ([]byte, error) {
	if c == nil {
		return nil, fmt.Errorf("llm client is nil")
	}
	cacheKey := "parse:" + strings.TrimSpace(raw)
	if v, ok := c.getCache(cacheKey); ok {
		return v, nil
	}
	prompt := buildParserPrompt(raw)
	b, err := c.generate(ctx, prompt)
	if err != nil {
		return nil, err
	}
	c.setCache(cacheKey, b, 15*time.Minute)
	return b, nil
}

// RepairCommand asks the LLM to repair a previously parsed command by filling
// missing required fields. The caller must still strictly decode/validate.
func (c *LLMParserClient) RepairCommand(ctx context.Context, raw string, missingFields []string) ([]byte, error) {
	if c == nil {
		return nil, fmt.Errorf("llm client is nil")
	}
	key := "repair:" + strings.TrimSpace(raw) + ":" + strings.Join(missingFields, ",")
	if v, ok := c.getCache(key); ok {
		return v, nil
	}
	prompt := buildRepairPrompt(raw, missingFields)
	b, err := c.generate(ctx, prompt)
	if err != nil {
		return nil, err
	}
	c.setCache(key, b, 15*time.Minute)
	return b, nil
}

func (c *LLMParserClient) generate(ctx context.Context, prompt string) ([]byte, error) {
	if err := acquireLLMSlot(ctx); err != nil {
		return nil, err
	}
	defer releaseLLMSlot()

	var (
		reqBody []byte
		url     string
		err     error
	)
	if c.provider == "openai" {
		reqBody, err = json.Marshal(openAIRequest{
			Model: c.model,
			Messages: []openAIMessage{
				{Role: "user", Content: prompt},
			},
			Temperature: 0.1,
			MaxTokens:   256,
			ResponseFormat: map[string]string{
				"type": "json_object",
			},
		})
		if err != nil {
			return nil, err
		}
		url = fmt.Sprintf("%s/chat/completions", strings.TrimRight(c.baseURL, "/"))
	} else {
		reqBody, err = json.Marshal(ollamaRequest{
			Model:  c.model,
			Prompt: prompt,
			Stream: false,
			Options: map[string]interface{}{
				"temperature": 0.1,
				"num_predict": 256,
			},
		})
		if err != nil {
			return nil, err
		}
		url = fmt.Sprintf("%s/api/generate", c.baseURL)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(reqBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("llm parser http %d: %s", resp.StatusCode, string(b))
	}

	// Enforce a hard response limit even if the backend misbehaves.
	limited := io.LimitReader(resp.Body, 16*1024)
	var rawContent string
	if c.provider == "openai" {
		var or openAIResponse
		if err := json.NewDecoder(limited).Decode(&or); err != nil {
			return nil, fmt.Errorf("decode openai response: %w", err)
		}
		if len(or.Choices) == 0 {
			return nil, fmt.Errorf("openai parser response missing choices")
		}
		rawContent = or.Choices[0].Message.Content
	} else {
		var or ollamaResponse
		if err := json.NewDecoder(limited).Decode(&or); err != nil {
			return nil, fmt.Errorf("decode ollama response: %w", err)
		}
		rawContent = or.Response
	}

	sanitized, err := sanitizeLLMJSON(rawContent)
	if err != nil {
		return nil, err
	}
	return sanitized, nil
}

func (c *LLMParserClient) getCache(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cache == nil {
		return nil, false
	}
	if e, ok := c.cache[key]; ok {
		if time.Now().Before(e.expiresAt) && len(e.value) > 0 {
			return e.value, true
		}
		delete(c.cache, key)
	}
	return nil, false
}

func (c *LLMParserClient) setCache(key string, value []byte, ttl time.Duration) {
	if ttl <= 0 || len(value) == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cache == nil {
		c.cache = make(map[string]cacheEntry)
	}
	c.cache[key] = cacheEntry{value: value, expiresAt: time.Now().Add(ttl)}
}

// buildParserPrompt constructs a strict system-style prompt instructing the
// model to emit ONLY a single JSON object matching AICommandPlan.
func buildParserPrompt(raw string) string {
	return fmt.Sprintf(`You are a zero-trust command parser for a factory scheduling assistant.

You MUST output exactly ONE JSON object and NOTHING else (no markdown, no commentary).

The JSON schema:
{
  "intent": "string",
  "action": "string",
  "entities": { "key": value, ... },
  "confidence": number,
  "ambiguous": boolean,
  "clarifications": ["string", ...],
  "message": "string"
}

Allowed actions/intents (must match exactly):
- propose_schedule (requires entities.job_id)
- explain_job (requires entities.job_id)
- delay_risk (requires entities.job_id)
- machine_ranking (requires entities.job_step_id)
- approve_proposal (requires entities.proposal_id)
- reject_proposal (requires entities.proposal_id)
- apply_proposal (requires entities.proposal_id OR entities.job_id)
- create_job (requires entities.product AND entities.quantity)
- reschedule (requires entities.job_id)
- cancel (requires entities.job_id)
- query_status (optional entities.resource=jobs|machines|inventory|general; optional entities.job_id)
- consume_material (requires entities.quantity AND entities.material; optional entities.job_id)
- receive_material (requires entities.material_id AND entities.quantity)
- record_downtime (requires entities.machine_id; optional entities.cause)
- maintenance_alerts (no required entities)
- list_products (no required entities)
- high_risk_jobs (no required entities)
- dashboard_kpis (no required entities)
- split_step (requires entities.job_step_id)
- generate_report (optional entities.report_type)
- schedule_all_jobs (no required entities)
- unknown (use action=\"none\")

CRITICAL ENTITY RULES:
- entities must be a JSON object and MUST ONLY use these keys (if present):
  - job_id, proposal_id, job_step_id, quantity, product, material, material_id, machine_id, deadline, resource, report_type, target_time, cause
- Do NOT invent IDs. Only set job_id / proposal_id / job_step_id / machine_id if you can see them in the user text (e.g. JOB-1234, AIPROP-42, JS-4001).
- For create_job you may infer quantity and product from phrases like "200 units of Widget A", but if you are not sure set ambiguous=true and ask for clarification.
- target_time is an optional, free-text description such as "later today" or "tomorrow morning" and is mostly used for reschedule.
- confidence must be between 0 and 1.

CRITICAL INTENT RULES:
- If the user asks about prediction or risk (e.g. "delay risk", "late?", "risk score") WITHOUT asking to change the plan, use action="delay_risk".
- If the user asks to reschedule, move, shift, postpone, push, or "do it later today", you MUST use action="reschedule" (NOT "delay_risk").
- If the user clearly cancels a job (cancel/remove/delete job JOB-1234), you MUST use action="cancel".
- If the user approves, rejects, or applies a proposal with an ID like AIPROP-123, use approve_proposal / reject_proposal / apply_proposal.
- If you cannot clearly map to one of the allowed actions, use intent="unknown" and action="none".
- If a required field is missing, DO NOT guess. Set ambiguous=true and add clarifications asking for the missing ID/field.

Output rules:
- Output must be valid JSON (double quotes, no trailing commas).
- Output MUST NOT be wrapped in markdown fences (code blocks) and MUST NOT contain any commentary.

Examples (format must stay JSON-only):
{"intent":"propose_schedule","action":"propose_schedule","entities":{"job_id":"JOB-1234"},"confidence":0.86,"ambiguous":false,"clarifications":[],"message":"Propose schedule for job JOB-1234."}
{"intent":"delay_risk","action":"delay_risk","entities":{"job_id":"JOB-3001"},"confidence":0.84,"ambiguous":false,"clarifications":[],"message":"Estimate delay risk for job JOB-3001."}
{"intent":"reschedule","action":"reschedule","entities":{"job_id":"JOB-8001","target_time":"later today"},"confidence":0.87,"ambiguous":false,"clarifications":[],"message":"Reschedule job JOB-8001 to later today."}
{"intent":"create_job","action":"create_job","entities":{"quantity":"200","product":"Widget A"},"confidence":0.83,"ambiguous":false,"clarifications":[],"message":"Create a job for 200 units of Widget A."}
{"intent":"schedule_all_jobs","action":"schedule_all_jobs","entities":{},"confidence":0.9,"ambiguous":false,"clarifications":[],"message":"Schedule all unscheduled jobs."}
{"intent":"approve_proposal","action":"approve_proposal","entities":{"proposal_id":"AIPROP-123"},"confidence":0.9,"ambiguous":false,"clarifications":[],"message":"Approve proposal AIPROP-123."}
{"intent":"reject_proposal","action":"reject_proposal","entities":{"proposal_id":"AIPROP-9101"},"confidence":0.89,"ambiguous":false,"clarifications":[],"message":"Reject proposal AIPROP-9101."}
{"intent":"apply_proposal","action":"apply_proposal","entities":{"proposal_id":"AIPROP-9201"},"confidence":0.88,"ambiguous":false,"clarifications":[],"message":"Apply proposal AIPROP-9201."}
{"intent":"create_job","action":"create_job","entities":{"product":"Widget Z"},"confidence":0.55,"ambiguous":true,"clarifications":["Specify the quantity, for example: 200 units."],"message":"Missing quantity for job creation."}
{"intent":"unknown","action":"none","entities":{},"confidence":0.20,"ambiguous":true,"clarifications":["Include a target like job JOB-1234 or proposal AIPROP-42."],"message":"Could not confidently parse."}

Now parse this user command:
%s`, raw)
}

func buildRepairPrompt(raw string, missingFields []string) string {
	return fmt.Sprintf(`You previously parsed a command but missed required fields.

You MUST output exactly ONE JSON object and NOTHING else (no markdown, no commentary).
Output must match the AICommandPlan schema from the previous instructions.

Missing required fields: %s

Rules:
- Fill ONLY from the user command text. Do not invent IDs or entities.
- You MAY infer quantity and product for create_job from phrases like "200 units of Widget A", but only if they are clearly present.
- Never invent job_id, proposal_id, or job_step_id; only use them if you see IDs like JOB-1234, AIPROP-42, or JS-4001 in the text.
- If you cannot find the missing fields in the text, keep ambiguous=true and add clarifications explaining what is missing.
- entities must only use the allowed keys: job_id, proposal_id, job_step_id, quantity, product, material, machine_id, deadline, resource, report_type, target_time.
- Do NOT wrap the JSON in markdown fences or add any commentary.

User command:
%s`, strings.Join(missingFields, ", "), raw)
}

// sanitizeLLMJSON normalizes the raw model response into a JSON object byte
// slice by trimming whitespace, removing markdown fences, and, if necessary,
// slicing from the first '{' to the last '}' within a bounded window.
func sanitizeLLMJSON(resp string) ([]byte, error) {
	s := strings.TrimSpace(resp)
	if s == "" {
		return nil, fmt.Errorf("empty llm response")
	}

	// Strip common markdown fences like ```json ... ``` or ``` ... ```.
	if strings.HasPrefix(s, "```") {
		// Drop leading fence line.
		s = strings.TrimPrefix(s, "```json")
		s = strings.TrimPrefix(s, "```JSON")
		if strings.HasPrefix(s, "```") {
			s = strings.TrimPrefix(s, "```")
		}
		// Remove a trailing ``` if present.
		if idx := strings.LastIndex(s, "```"); idx >= 0 {
			s = s[:idx]
		}
		s = strings.TrimSpace(s)
	}

	// Best-effort slice from first '{' to last '}' to drop any stray pre/post text.
	const maxLen = 16 * 1024
	if len(s) > maxLen {
		s = s[:maxLen]
	}
	start := strings.IndexByte(s, '{')
	end := strings.LastIndexByte(s, '}')
	if start >= 0 && end > start {
		s = s[start : end+1]
	}

	s = strings.TrimSpace(s)
	if !strings.HasPrefix(s, "{") || !strings.HasSuffix(s, "}") {
		return nil, fmt.Errorf("llm response did not contain a valid JSON object")
	}

	return []byte(s), nil
}
