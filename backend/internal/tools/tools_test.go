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
	if !strings.Contains(result["message"].(string), "TAVILY_API_KEY") {
		t.Fatalf("message = %q, want not configured explanation", result["message"])
	}
}

func TestCurrentTimeUsesShanghaiTimezone(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	result, err := registry.Execute(context.Background(), "current_time", map[string]any{})
	if err != nil {
		t.Fatalf("Execute(current_time) error = %v", err)
	}

	if result["timezone"] != "Asia/Shanghai" {
		t.Fatalf("timezone = %v, want Asia/Shanghai", result["timezone"])
	}
	if _, ok := result["unix"].(int64); !ok {
		t.Fatalf("unix = %T, want int64", result["unix"])
	}
	if !strings.Contains(result["iso8601"].(string), "+08:00") {
		t.Fatalf("iso8601 = %q, want +08:00 offset", result["iso8601"])
	}
	if len(result["date"].(string)) != len("2006-01-02") {
		t.Fatalf("date = %q, want YYYY-MM-DD", result["date"])
	}
	if len(result["time"].(string)) != len("15:04:05") {
		t.Fatalf("time = %q, want HH:mm:ss", result["time"])
	}
}

func TestWebSearchUsesTavilySearchAPI(t *testing.T) {
	var sawAPIKey bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/search" {
			t.Fatalf("path = %s, want /search", r.URL.Path)
		}
		sawAPIKey = r.Header.Get("Authorization") == "Bearer tavily-key"

		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request body: %v", err)
		}
		if body["query"] != "AI investment moats" {
			t.Fatalf("query = %v, want AI investment moats", body["query"])
		}
		if body["search_depth"] != "basic" {
			t.Fatalf("search_depth = %v, want basic", body["search_depth"])
		}
		if body["max_results"] != float64(5) {
			t.Fatalf("max_results = %v, want 5", body["max_results"])
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"answer": "AI infrastructure demand is rising.",
			"results": []map[string]string{{
				"title":   "AI Infrastructure Result",
				"url":     "https://example.com/ai",
				"content": "AI infrastructure companies are investing in accelerators.",
			}},
		})
	}))
	defer server.Close()
	registry := tools.NewRegistry(config.Config{
		TavilyAPIKey:      "tavily-key",
		TavilyBaseURL:     server.URL,
		HTTPClientTimeout: time.Second,
		FetchAllowPrivate: true,
	})

	result, err := registry.Execute(context.Background(), "web_search", map[string]any{
		"query": "AI investment moats",
	})
	if err != nil {
		t.Fatalf("Execute(web_search) error = %v", err)
	}

	if !sawAPIKey {
		t.Fatal("Authorization header missing, want Bearer tavily-key")
	}
	if result["configured"] != true {
		t.Fatalf("configured = %v, want true", result["configured"])
	}
	if result["answer"] != "AI infrastructure demand is rising." {
		t.Fatalf("answer = %v, want Tavily answer", result["answer"])
	}
	results := result["results"].([]any)
	if len(results) != 1 {
		t.Fatalf("results len = %d, want 1", len(results))
	}
	first := results[0].(map[string]any)
	if first["title"] != "AI Infrastructure Result" || first["url"] != "https://example.com/ai" {
		t.Fatalf("first result = %+v, want normalized Tavily result", first)
	}
	if !strings.Contains(result["raw"].(string), "AI Infrastructure Result") {
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
