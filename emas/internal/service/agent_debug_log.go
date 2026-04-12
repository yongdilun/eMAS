package service

import (
	"encoding/json"
	"os"
	"time"
)

// #region agent log
const agentDebugLogPath = `c:\Users\dilun\OneDrive\Documents\eMas APi\.cursor\debug.log`

func agentDebugNDJSON(hypothesisID, location, message string, data map[string]any) {
	payload := map[string]any{
		"hypothesisId": hypothesisID,
		"location":     location,
		"message":      message,
		"data":         data,
		"timestamp":    time.Now().UnixMilli(),
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return
	}
	f, err := os.OpenFile(agentDebugLogPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	_, _ = f.Write(append(b, '\n'))
	_ = f.Close()
}

// #endregion
