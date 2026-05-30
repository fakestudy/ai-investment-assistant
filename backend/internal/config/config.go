package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port              string
	DatabaseURL       string
	DeepSeekAPIKey    string
	DeepSeekBaseURL   string
	DeepSeekModel     string
	SearchAPIKey      string
	HTTPClientTimeout time.Duration
}

func Load() Config {
	return Config{
		Port:              getEnv("PORT", "8080"),
		DatabaseURL:       getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/ai_assistant?sslmode=disable"),
		DeepSeekAPIKey:    os.Getenv("DEEPSEEK_API_KEY"),
		DeepSeekBaseURL:   getEnv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
		DeepSeekModel:     getEnv("DEEPSEEK_MODEL", "deepseek-chat"),
		SearchAPIKey:      os.Getenv("SEARCH_API_KEY"),
		HTTPClientTimeout: time.Duration(getEnvInt("HTTP_CLIENT_TIMEOUT_SECONDS", 30)) * time.Second,
	}
}

func getEnv(key string, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}
