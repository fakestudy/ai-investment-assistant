package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"

	"ai-investment-assistant/backend/internal/config"
)

const tavilySearchPath = "/search"

type tavilySearchRequest struct {
	Query       string `json:"query"`
	SearchDepth string `json:"search_depth"`
	MaxResults  int    `json:"max_results"`
}

type tavilySearchResponse struct {
	Answer  string               `json:"answer"`
	Results []tavilySearchResult `json:"results"`
}

type tavilySearchResult struct {
	Title   string `json:"title"`
	URL     string `json:"url"`
	Content string `json:"content"`
}

func newWebSearchTool(cfg config.Config, client HTTPDoer) Tool {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		query := strings.TrimSpace(stringArg(args, "query"))
		if query == "" {
			return nil, errors.New("query is required")
		}
		if strings.TrimSpace(cfg.TavilyAPIKey) == "" {
			return map[string]any{
				"query":      query,
				"configured": false,
				"results":    []any{},
				"message":    "web_search is not configured because TAVILY_API_KEY is empty",
			}, nil
		}

		endpoint, err := tavilySearchEndpoint(cfg.TavilyBaseURL)
		if err != nil {
			return nil, err
		}
		payload, err := json.Marshal(tavilySearchRequest{
			Query:       query,
			SearchDepth: "basic",
			MaxResults:  5,
		})
		if err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(payload))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+cfg.TavilyAPIKey)
		req.Header.Set("Content-Type", "application/json")

		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("web_search upstream status %d", resp.StatusCode)
		}

		var decoded tavilySearchResponse
		if err := json.Unmarshal(body, &decoded); err != nil {
			return nil, fmt.Errorf("decode Tavily response: %w", err)
		}
		return map[string]any{
			"query":      query,
			"configured": true,
			"answer":     decoded.Answer,
			"results":    normalizeTavilyResults(decoded.Results),
			"raw":        string(body),
		}, nil
	}
}

func tavilySearchEndpoint(rawBaseURL string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(rawBaseURL))
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("TAVILY_BASE_URL must be an absolute URL")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/") + tavilySearchPath
	parsed.RawQuery = ""
	return parsed.String(), nil
}

func normalizeTavilyResults(results []tavilySearchResult) []any {
	normalized := make([]any, 0, len(results))
	for _, result := range results {
		normalized = append(normalized, map[string]any{
			"title":   result.Title,
			"url":     result.URL,
			"content": result.Content,
		})
	}
	return normalized
}
