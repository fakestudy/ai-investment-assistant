package main

import (
	"log"

	"ai-investment-assistant/backend/internal/config"
)

func main() {
	cfg := config.Load()
	log.Printf("backend chat api listening on :%s", cfg.Port)
}
