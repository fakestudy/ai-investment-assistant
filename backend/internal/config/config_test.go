package config

import (
	"testing"
	"time"
)

func TestLoadUsesDefaults(t *testing.T) {
	t.Setenv("BFF_HTTP_ADDR", "")
	t.Setenv("DATABASE_URL", "")
	t.Setenv("DEEPSEEK_API_KEY", "")
	t.Setenv("DEEPSEEK_BASE_URL", "")
	t.Setenv("DEEPSEEK_MODEL", "")
	t.Setenv("DEEPSEEK_TIMEOUT_SECONDS", "")
	t.Setenv("SEARCH_API_KEY", "")
	t.Setenv("SEARCH_BASE_URL", "")
	t.Setenv("FETCH_ALLOW_PRIVATE", "")

	cfg := Load()

	if cfg.HTTPAddr != ":8081" {
		t.Fatalf("HTTPAddr = %q, want %q", cfg.HTTPAddr, ":8081")
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
	t.Setenv("BFF_HTTP_ADDR", ":9090")
	t.Setenv("DATABASE_URL", "postgres://example")
	t.Setenv("DEEPSEEK_API_KEY", "deepseek-key")
	t.Setenv("DEEPSEEK_BASE_URL", "https://example.com")
	t.Setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
	t.Setenv("DEEPSEEK_TIMEOUT_SECONDS", "7")
	t.Setenv("SEARCH_API_KEY", "search-key")
	t.Setenv("SEARCH_BASE_URL", "https://search.example.com")
	t.Setenv("FETCH_ALLOW_PRIVATE", "true")

	cfg := Load()

	if cfg.HTTPAddr != ":9090" {
		t.Fatalf("HTTPAddr = %q, want %q", cfg.HTTPAddr, ":9090")
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
	if cfg.DeepSeekModel != "deepseek-v4-pro" {
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

func TestLoadIgnoresLegacyHTTPClientTimeout(t *testing.T) {
	t.Setenv("DEEPSEEK_TIMEOUT_SECONDS", "")
	t.Setenv("HTTP_CLIENT_TIMEOUT_SECONDS", "7")

	cfg := Load()

	if cfg.HTTPClientTimeout != 60*time.Second {
		t.Fatalf("HTTPClientTimeout = %s, want default %s", cfg.HTTPClientTimeout, 60*time.Second)
	}
}
