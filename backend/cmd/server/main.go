package main

import (
	"context"
	"log"
	"net/http"
	"time"

	"ai-investment-assistant/backend/internal/agent"
	"ai-investment-assistant/backend/internal/api"
	"ai-investment-assistant/backend/internal/chat"
	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/conversation"
	"ai-investment-assistant/backend/internal/store"
	"ai-investment-assistant/backend/internal/tools"
)

func main() {
	cfg := config.Load()
	log.Printf("backend chat api listening on :%s", cfg.Port)

	db, err := store.OpenPostgres(context.Background(), cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("open database: %v", err)
	}

	conversationService := conversation.NewService(db)
	toolRegistry := tools.NewRegistry(cfg)
	chatService := chat.NewService(conversationService, agent.NewEinoAgent(cfg, toolRegistry))
	router := api.NewRouter(conversationService, chatService)
	if err := newHTTPServer(cfg, router).ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("run server: %v", err)
	}
}

func newHTTPServer(cfg config.Config, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		// Keep WriteTimeout disabled so SSE streaming responses are not cut off.
		WriteTimeout: 0,
		IdleTimeout:  120 * time.Second,
	}
}
