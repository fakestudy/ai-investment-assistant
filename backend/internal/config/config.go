package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr          string
	DatabaseURL       string
	DeepSeekAPIKey    string
	DeepSeekBaseURL   string
	DeepSeekModel     string
	SearchAPIKey      string
	SearchBaseURL     string
	TavilyAPIKey      string
	TavilyBaseURL     string
	FetchAllowPrivate bool
	HTTPClientTimeout time.Duration
}

func Load() Config {
	return Config{
		HTTPAddr:          getEnv("BFF_HTTP_ADDR", ":8081"),
		DatabaseURL:       getEnv("DATABASE_URL", "postgres://investment:investment@postgres:5432/investment?sslmode=disable"),
		DeepSeekAPIKey:    os.Getenv("DEEPSEEK_API_KEY"),
		DeepSeekBaseURL:   getEnv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
		DeepSeekModel:     getEnv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
		SearchAPIKey:      os.Getenv("SEARCH_API_KEY"),
		SearchBaseURL:     os.Getenv("SEARCH_BASE_URL"),
		TavilyAPIKey:      os.Getenv("TAVILY_API_KEY"),
		TavilyBaseURL:     getEnv("TAVILY_BASE_URL", "https://api.tavily.com"),
		FetchAllowPrivate: getEnvBool("FETCH_ALLOW_PRIVATE", false),
		HTTPClientTimeout: time.Duration(getEnvInt("DEEPSEEK_TIMEOUT_SECONDS", 60)) * time.Second,
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

func getEnvBool(key string, fallback bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}
