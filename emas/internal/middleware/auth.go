package middleware

import (
	"emas/pkg/featureflags"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

const (
	ContextUserIDKey   = "user_id"
	ContextUserRoleKey = "user_role"
)

func RequireRoles(roles ...string) gin.HandlerFunc {
	allowed := make(map[string]struct{}, len(roles))
	for _, role := range roles {
		allowed[strings.ToLower(strings.TrimSpace(role))] = struct{}{}
	}
	return func(c *gin.Context) {
		userID := strings.TrimSpace(c.GetHeader("X-User-Id"))
		role := strings.ToLower(strings.TrimSpace(c.GetHeader("X-User-Role")))
		if userID == "" {
			userID = "system"
		}
		if role == "" {
			role = "planner"
		}
		c.Set(ContextUserIDKey, userID)
		c.Set(ContextUserRoleKey, role)
		if !featureflags.SchedulingWriteAuthRequired() {
			c.Next()
			return
		}
		if _, ok := allowed[role]; !ok {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"success": false,
				"error":   "insufficient role for this action",
			})
			return
		}
		c.Next()
	}
}
