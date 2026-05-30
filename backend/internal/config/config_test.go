package config

import (
	"testing"
	"time"
)

func TestLoadUsesDefaults(t *testing.T) {
	t.Setenv("PORT", "")
	t.Setenv("DATABASE_URL", "")
	t.Setenv("DEEPSEEK_API_KEY", "")
	t.Setenv("DEEPSEEK_BASE_URL", "")
	t.Setenv("DEEPSEEK_MODEL", "")
	t.Setenv("SEARCH_API_KEY", "")
	t.Setenv("SEARCH_BASE_URL", "")
	t.Setenv("FETCH_ALLOW_PRIVATE", "")
	t.Setenv("HTTP_CLIENT_TIMEOUT_SECONDS", "")

	cfg := Load()

	if cfg.Port != "8081" {
		t.Fatalf("Port = %q, want %q", cfg.Port, "8081")
	}
	if cfg.DatabaseURL != "postgres://investment:investment@postgres:5432/investment?sslmode=disable" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
	if cfg.DeepSeekBaseURL != "https://api.deepseek.com" {
		t.Fatalf("DeepSeekBaseURL = %q", cfg.DeepSeekBaseURL)
	}
	if cfg.DeepSeekModel != "deepseek-v4-pro" {
		t.Fatalf("DeepSeekModel = %q", cfg.DeepSeekModel)
	}
	if cfg.HTTPClientTimeout != 60*time.Second {
		t.Fatalf("HTTPClientTimeout = %s, want %s", cfg.HTTPClientTimeout, 60*time.Second)
	}
}

func TestLoadUsesEnvironmentOverrides(t *testing.T) {
	t.Setenv("PORT", "9090")
	t.Setenv("DATABASE_URL", "postgres://example")
	t.Setenv("DEEPSEEK_API_KEY", "deepseek-key")
	t.Setenv("DEEPSEEK_BASE_URL", "https://example.com")
	t.Setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
	t.Setenv("SEARCH_API_KEY", "search-key")
	t.Setenv("SEARCH_BASE_URL", "https://search.example.com")
	t.Setenv("FETCH_ALLOW_PRIVATE", "true")
	t.Setenv("HTTP_CLIENT_TIMEOUT_SECONDS", "7")

	cfg := Load()

	if cfg.Port != "9090" {
		t.Fatalf("Port = %q, want %q", cfg.Port, "9090")
	}
	if cfg.DatabaseURL != "postgres://example" {
		t.Fatalf("DatabaseURL = %q", cfg.DatabaseURL)
	}
	if cfg.DeepSeekAPIKey != "deepseek-key" {
		t.Fatalf("DeepSeekAPIKey = %q", cfg.DeepSeekAPIKey)
	}
	if cfg.DeepSeekBaseURL != "https://example.com" {
		t.Fatalf("DeepSeekBaseURL = %q", cfg.DeepSeekBaseURL)
	}
	if cfg.DeepSeekModel != "deepseek-reasoner" {
		t.Fatalf("DeepSeekModel = %q", cfg.DeepSeekModel)
	}
	if cfg.SearchAPIKey != "search-key" {
		t.Fatalf("SearchAPIKey = %q", cfg.SearchAPIKey)
	}
	if cfg.SearchBaseURL != "https://search.example.com" {
		t.Fatalf("SearchBaseURL = %q", cfg.SearchBaseURL)
	}
	if !cfg.FetchAllowPrivate {
		t.Fatal("FetchAllowPrivate = false, want true")
	}
	if cfg.HTTPClientTimeout != 7*time.Second {
		t.Fatalf("HTTPClientTimeout = %s, want %s", cfg.HTTPClientTimeout, 7*time.Second)
	}
}
