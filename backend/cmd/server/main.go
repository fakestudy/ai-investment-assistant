package main

import (
	"context"
	"log"

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
	if err := router.Run(":" + cfg.Port); err != nil {
		log.Fatalf("run server: %v", err)
	}
}
