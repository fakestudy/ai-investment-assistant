package tools_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestWebSearchWithoutAPIKeyReturnsDeterministicResult(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	result, err := registry.Execute(context.Background(), "web_search", map[string]any{
		"query": "AI investment moats",
	})
	if err != nil {
		t.Fatalf("Execute(web_search) error = %v", err)
	}

	if result["query"] != "AI investment moats" {
		t.Fatalf("query = %v, want AI investment moats", result["query"])
	}
	if result["configured"] != false {
		t.Fatalf("configured = %v, want false", result["configured"])
	}
	if !strings.Contains(result["message"].(string), "not configured") {
		t.Fatalf("message = %q, want not configured explanation", result["message"])
	}
}

func TestWebSearchUsesConfiguredHTTPAdapter(t *testing.T) {
	var sawAuthorization bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawAuthorization = r.Header.Get("Authorization") == "Bearer search-key"
		if r.URL.Query().Get("q") != "AI investment moats" {
			t.Fatalf("query = %q, want AI investment moats", r.URL.Query().Get("q"))
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"results": []map[string]string{{"title": "Result"}},
		})
	}))
	defer server.Close()
	registry := tools.NewRegistry(config.Config{
		SearchAPIKey:      "search-key",
		SearchBaseURL:     server.URL + "/search",
		HTTPClientTimeout: time.Second,
	})

	result, err := registry.Execute(context.Background(), "web_search", map[string]any{
		"query": "AI investment moats",
	})
	if err != nil {
		t.Fatalf("Execute(web_search) error = %v", err)
	}

	if !sawAuthorization {
		t.Fatal("Authorization header missing, want Bearer search-key")
	}
	if result["configured"] != true {
		t.Fatalf("configured = %v, want true", result["configured"])
	}
	if !strings.Contains(result["raw"].(string), "Result") {
		t.Fatalf("raw = %q, want upstream response", result["raw"])
	}
}

func TestFetchURLRejectsNonHTTPURL(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	_, err := registry.Execute(context.Background(), "fetch_url", map[string]any{
		"url": "file:///etc/passwd",
	})
	if err == nil {
		t.Fatal("Execute(fetch_url) error = nil, want validation error")
	}
	if !strings.Contains(err.Error(), "http:// or https://") {
		t.Fatalf("error = %q, want http/https validation message", err.Error())
	}
}

func TestFetchURLRejectsLoopbackAddress(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html><body>private data</body></html>"))
	}))
	defer server.Close()
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	_, err := registry.Execute(context.Background(), "fetch_url", map[string]any{
		"url": server.URL,
	})
	if err == nil {
		t.Fatal("Execute(fetch_url) error = nil, want SSRF validation error")
	}
	if !strings.Contains(err.Error(), "private") {
		t.Fatalf("error = %q, want private address validation message", err.Error())
	}
}

func TestFetchURLExtractsTitleAndVisibleText(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`<!doctype html>
<html>
<head>
  <title>Example Page</title>
  <style>.hidden { display: none; }</style>
  <script>window.secret = "ignore me";</script>
</head>
<body>
  <h1>Visible heading</h1>
  <p>Useful body text for investors.</p>
</body>
</html>`))
	}))
	defer server.Close()
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second, FetchAllowPrivate: true})

	result, err := registry.Execute(context.Background(), "fetch_url", map[string]any{
		"url": server.URL,
	})
	if err != nil {
		t.Fatalf("Execute(fetch_url) error = %v", err)
	}

	if result["url"] != server.URL {
		t.Fatalf("url = %v, want %s", result["url"], server.URL)
	}
	if result["title"] != "Example Page" {
		t.Fatalf("title = %v, want Example Page", result["title"])
	}
	text := result["text"].(string)
	if !strings.Contains(text, "Visible heading") || !strings.Contains(text, "Useful body text") {
		t.Fatalf("text = %q, want visible page text", text)
	}
	if strings.Contains(text, "ignore me") || strings.Contains(text, "display: none") {
		t.Fatalf("text = %q, must not contain script/style content", text)
	}
}
