package tools

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"golang.org/x/net/html"
)

type HTTPDoer interface {
	Do(req *http.Request) (*http.Response, error)
}

type Tool func(ctx context.Context, args map[string]any) (map[string]any, error)

type Registry struct {
	tools map[string]Tool
}

func NewRegistry(cfg config.Config) Registry {
	timeout := cfg.HTTPClientTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	client := &http.Client{Timeout: timeout}
	return Registry{tools: map[string]Tool{
		"web_search": newWebSearchTool(cfg, client),
		"fetch_url":  newFetchURLTool(client),
	}}
}

func (r Registry) Execute(ctx context.Context, name string, args map[string]any) (map[string]any, error) {
	tool, ok := r.tools[name]
	if !ok {
		return nil, fmt.Errorf("unknown tool %q", name)
	}
	return tool(ctx, args)
}

func newWebSearchTool(cfg config.Config, client HTTPDoer) Tool {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		query := strings.TrimSpace(stringArg(args, "query"))
		if query == "" {
			return nil, errors.New("query is required")
		}
		if cfg.SearchAPIKey == "" {
			return map[string]any{
				"query":      query,
				"configured": false,
				"results":    []any{},
				"message":    "web_search is not configured because SEARCH_API_KEY is empty",
			}, nil
		}
		if strings.TrimSpace(cfg.SearchBaseURL) == "" {
			return map[string]any{
				"query":      query,
				"configured": false,
				"results":    []any{},
				"message":    "web_search is not configured because SEARCH_BASE_URL is empty",
			}, nil
		}

		endpoint, err := appendQuery(cfg.SearchBaseURL, "q", query)
		if err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+cfg.SearchAPIKey)
		req.Header.Set("X-Subscription-Token", cfg.SearchAPIKey)
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 16*1024))
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("web_search upstream status %d", resp.StatusCode)
		}
		return map[string]any{
			"query":      query,
			"configured": true,
			"raw":        string(body),
		}, nil
	}
}

func appendQuery(rawURL string, key string, value string) (string, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", errors.New("SEARCH_BASE_URL must be an absolute URL")
	}
	query := parsed.Query()
	query.Set(key, value)
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func newFetchURLTool(client HTTPDoer) Tool {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		rawURL := strings.TrimSpace(stringArg(args, "url"))
		parsed, err := url.Parse(rawURL)
		if err != nil || parsed.Scheme == "" || parsed.Host == "" {
			return nil, errors.New("url must be a valid http:// or https:// URL")
		}
		if parsed.Scheme != "http" && parsed.Scheme != "https" {
			return nil, errors.New("url must use http:// or https://")
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("User-Agent", "ai-investment-assistant/1.0")
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("fetch_url status %d", resp.StatusCode)
		}
		body, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
		if err != nil {
			return nil, err
		}
		title, text := extractHTMLText(string(body))
		return map[string]any{
			"url":   parsed.String(),
			"title": title,
			"text":  text,
		}, nil
	}
}

func stringArg(args map[string]any, key string) string {
	if args == nil {
		return ""
	}
	value, ok := args[key]
	if !ok || value == nil {
		return ""
	}
	switch typed := value.(type) {
	case string:
		return typed
	default:
		return fmt.Sprint(typed)
	}
}

func extractHTMLText(raw string) (string, string) {
	doc, err := html.Parse(strings.NewReader(raw))
	if err != nil {
		return "", collapseWhitespace(stripTags(raw))
	}
	var title string
	var parts []string
	var walk func(*html.Node, bool)
	walk = func(n *html.Node, hidden bool) {
		if n.Type == html.ElementNode {
			name := strings.ToLower(n.Data)
			if name == "script" || name == "style" || name == "noscript" {
				hidden = true
			}
			if name == "title" {
				title = strings.TrimSpace(nodeText(n))
				hidden = true
			}
		}
		if !hidden && n.Type == html.TextNode {
			if text := strings.TrimSpace(n.Data); text != "" {
				parts = append(parts, text)
			}
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			walk(child, hidden)
		}
	}
	walk(doc, false)
	return title, collapseWhitespace(strings.Join(parts, " "))
}

func nodeText(n *html.Node) string {
	var parts []string
	var walk func(*html.Node)
	walk = func(current *html.Node) {
		if current.Type == html.TextNode {
			parts = append(parts, current.Data)
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(n)
	return strings.Join(parts, " ")
}

var tagPattern = regexp.MustCompile(`<[^>]+>`)
var whitespacePattern = regexp.MustCompile(`\s+`)

func stripTags(raw string) string {
	return tagPattern.ReplaceAllString(raw, " ")
}

func collapseWhitespace(raw string) string {
	return strings.TrimSpace(whitespacePattern.ReplaceAllString(raw, " "))
}
