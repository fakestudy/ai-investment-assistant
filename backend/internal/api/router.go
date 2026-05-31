package api

import (
	"net/http"
	"strings"

	"ai-investment-assistant/backend/internal/chat"
	"ai-investment-assistant/backend/internal/conversation"
	"github.com/gin-gonic/gin"
)

type Router struct {
	conversations *conversation.Service
	chats         *chat.Service
}

type renameConversationRequest struct {
	Title string `json:"title"`
}

type editMessageRequest struct {
	Content string `json:"content"`
}

func NewRouter(conversations *conversation.Service, chatServices ...*chat.Service) *gin.Engine {
	chats := chat.NewService(conversations, nil)
	if len(chatServices) > 0 && chatServices[0] != nil {
		chats = chatServices[0]
	}
	handler := &Router{conversations: conversations, chats: chats}
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(corsForLocalhost())

	api := router.Group("/api")
	api.GET("/health", handler.health)
	api.GET("/conversations", handler.listConversations)
	api.POST("/conversations", handler.createConversation)
	api.PATCH("/conversations/:conversationId", handler.renameConversation)
	api.DELETE("/conversations/:conversationId", handler.deleteConversation)
	api.GET("/conversations/:conversationId/messages", handler.listMessages)
	api.PATCH("/messages/:messageId", handler.editMessage)
	api.POST("/chat/stream", handler.streamChat)
	api.GET("/chat/streams/:messageId", handler.resumeChatStream)
	api.POST("/chat/streams/:messageId/cancel", handler.cancelChatStream)

	return router
}

func corsForLocalhost() gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if isLocalhostOrigin(origin) {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Vary", "Origin")
			c.Header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
			c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization, Last-Event-ID")
			c.Header("Access-Control-Allow-Credentials", "true")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func isLocalhostOrigin(origin string) bool {
	if origin == "" {
		return false
	}
	return strings.HasPrefix(origin, "http://localhost:") ||
		strings.HasPrefix(origin, "https://localhost:") ||
		strings.HasPrefix(origin, "http://127.0.0.1:") ||
		strings.HasPrefix(origin, "https://127.0.0.1:")
}

func (r *Router) health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (r *Router) listConversations(c *gin.Context) {
	conversations, err := r.conversations.ListConversations(c.Request.Context())
	if err != nil {
		respondError(c, err)
		return
	}
	c.JSON(http.StatusOK, conversations)
}

func (r *Router) createConversation(c *gin.Context) {
	created, err := r.conversations.CreateConversation(c.Request.Context())
	if err != nil {
		respondError(c, err)
		return
	}
	c.JSON(http.StatusCreated, created)
}

func (r *Router) renameConversation(c *gin.Context) {
	var request renameConversationRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		respondBadRequest(c, "invalid JSON")
		return
	}
	title := strings.TrimSpace(request.Title)
	if title == "" {
		respondBadRequest(c, "title is required")
		return
	}

	renamed, err := r.conversations.RenameConversation(c.Request.Context(), c.Param("conversationId"), title)
	if err != nil {
		respondError(c, err)
		return
	}
	c.JSON(http.StatusOK, renamed)
}

func (r *Router) deleteConversation(c *gin.Context) {
	if err := r.conversations.DeleteConversation(c.Request.Context(), c.Param("conversationId")); err != nil {
		respondError(c, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (r *Router) listMessages(c *gin.Context) {
	conversationID := c.Param("conversationId")
	exists, err := r.conversationExists(c, conversationID)
	if err != nil {
		respondError(c, err)
		return
	}
	if !exists {
		respondNotFound(c)
		return
	}

	messages, err := r.conversations.ListMessages(c.Request.Context(), conversationID)
	if err != nil {
		respondError(c, err)
		return
	}
	c.JSON(http.StatusOK, messages)
}

func (r *Router) editMessage(c *gin.Context) {
	var request editMessageRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		respondBadRequest(c, "invalid JSON")
		return
	}
	content := strings.TrimSpace(request.Content)
	if content == "" {
		respondBadRequest(c, "content is required")
		return
	}

	edited, err := r.conversations.EditMessage(c.Request.Context(), c.Param("messageId"), content)
	if err != nil {
		respondError(c, err)
		return
	}
	c.JSON(http.StatusOK, edited)
}

func (r *Router) streamChat(c *gin.Context) {
	var request chat.StreamChatRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		respondBadRequest(c, "invalid JSON")
		return
	}

	events, err := r.chats.Stream(c.Request.Context(), request)
	if err != nil {
		if chat.IsValidation(err) {
			respondBadRequest(c, chat.ValidationMessage(err))
			return
		}
		respondError(c, err)
		return
	}

	writeSSEEvents(c.Writer, c.Request, events)
}

func (r *Router) resumeChatStream(c *gin.Context) {
	events, err := r.chats.ResumeStream(c.Request.Context(), c.Param("messageId"))
	if err != nil {
		if chat.IsValidation(err) {
			respondBadRequest(c, chat.ValidationMessage(err))
			return
		}
		respondError(c, err)
		return
	}

	writeSSEEvents(c.Writer, c.Request, events)
}

func (r *Router) cancelChatStream(c *gin.Context) {
	if err := r.chats.CancelStream(c.Request.Context(), c.Param("messageId")); err != nil {
		if chat.IsValidation(err) {
			respondBadRequest(c, chat.ValidationMessage(err))
			return
		}
		respondError(c, err)
		return
	}
	c.Status(http.StatusNoContent)
}

func (r *Router) conversationExists(c *gin.Context, conversationID string) (bool, error) {
	conversations, err := r.conversations.ListConversations(c.Request.Context())
	if err != nil {
		return false, err
	}
	for _, item := range conversations {
		if item.ID == conversationID {
			return true, nil
		}
	}
	return false, nil
}

func respondError(c *gin.Context, err error) {
	if conversation.IsNotFound(err) {
		respondNotFound(c)
		return
	}
	c.JSON(http.StatusInternalServerError, gin.H{"message": "internal server error"})
}

func respondBadRequest(c *gin.Context, message string) {
	c.JSON(http.StatusBadRequest, gin.H{"message": message})
}

func respondNotFound(c *gin.Context) {
	c.JSON(http.StatusNotFound, gin.H{"message": "not found"})
}
